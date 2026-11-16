"""
Camada de acesso ao banco de dados PostgreSQL.

Usa um pool de conexoes simples via psycopg2. Todas as funcoes de
rota do app.py devem passar por aqui em vez de abrir conexoes soltas.

Alem do banco principal (sop), ha um segundo pool somente-leitura
para o banco do sistema hospitalar (ISIVITA/SESA - isivitaedb_hm),
usado para consultar unidades e altas. Esse banco e o sistema de
registro oficial do hospital e NUNCA deve ser alterado por aqui.
"""
import os

import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import g, has_request_context, session

from config import SCHEMA_VALIDO

# Tabelas do sistema hospitalar consultadas pela app (todas no schema
# configurado em INTEGRA_SCHEMA).
TABELAS_INTEGRA = (
    "t_clinica", "t_enfermaria", "t_leito", "t_internacao", "t_internacao_leito",
    "t_paciente", "t_destino", "t_exame", "t_exame_solic", "t_admissao", "t_cid10",
    "t_internacao_alta", "t_motivo_alta", "t_profissional", "t_conselho",
)

_pool = None
_pool_integra = None

# Segundos para desistir de conectar (evita a app travar se o host nao responder).
CONNECT_TIMEOUT = 5


class BancoIndisponivel(Exception):
    """Nao foi possivel conectar a um dos bancos (mensagem ja legivel)."""


def _mensagem_erro(exc):
    """Mensagem de erro do Postgres em texto legivel.

    No Windows, com o servidor em portugues, o psycopg2 falha ao decodificar
    a mensagem (ex: "autenticacao falhou", em cp1252) e levanta um
    UnicodeDecodeError que esconde o motivo real. Aqui recuperamos o texto."""
    if isinstance(exc, UnicodeDecodeError):
        return exc.object.decode("cp1252", "replace").strip()
    return str(exc).strip()


def testar_conexao(dsn):
    """Tenta conectar. Devolve None se der certo, senao a mensagem de erro."""
    try:
        psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT).close()
        return None
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        return _mensagem_erro(exc)


def preparar_banco(dsn, caminho_schema):
    """Garante que o banco de 'dsn' exista e tenha as tabelas do sistema.

    - Se nao conseguir conectar, conecta no banco de manutencao ("postgres"
      ou "template1") com as mesmas credenciais e, se o banco realmente nao
      existir, cria-o (CREATE DATABASE).
    - Se a tabela "usuarios" nao existir, aplica o schema.sql (idempotente).

    Devolve (erro, acoes): erro = None se deu certo, senao a mensagem;
    acoes = lista do que foi feito (ex: ["banco \"sop\" criado"])."""
    acoes = []
    erro = testar_conexao(dsn)
    if erro:
        criado, erro_criacao = _criar_banco_se_nao_existir(dsn)
        if not criado:
            return (erro_criacao or erro), acoes
        acoes.append(f'banco "{psycopg2.extensions.parse_dsn(dsn).get("dbname")}" criado')

    try:
        conn = psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT)
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        return _mensagem_erro(exc), acoes
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('usuarios') IS NOT NULL")
            if not cur.fetchone()[0]:
                with open(caminho_schema, encoding="utf-8") as arquivo:
                    cur.execute(arquivo.read())
                acoes.append("tabelas criadas")
        conn.commit()
    except (psycopg2.Error, UnicodeDecodeError, OSError) as exc:
        conn.rollback()
        conn.close()
        return f"Erro ao criar as tabelas: {_mensagem_erro(exc)}", acoes

    # Migracoes de estrutura e ajustes de seguranca (idempotentes): rodam a
    # cada inicio. Falha aqui nao derruba a app - ex: usuario do banco sem
    # permissao de ALTER TABLE (caso do usuario restrito de
    # sql/permissoes.sql, que ja encontra tudo pronto).
    pasta_sql = os.path.dirname(caminho_schema)
    try:
        for nome, rotulo in (("migracoes.sql", "migracoes"), ("seguranca.sql", "ajustes de seguranca")):
            try:
                with conn.cursor() as cur, open(os.path.join(pasta_sql, nome), encoding="utf-8") as arquivo:
                    cur.execute(arquivo.read())
                conn.commit()
            except (psycopg2.Error, UnicodeDecodeError, OSError) as exc:
                conn.rollback()
                print(f"[aviso] {rotulo} do banco nao aplicados: {_mensagem_erro(exc)}")
    finally:
        conn.close()
    return None, acoes


def _criar_banco_se_nao_existir(dsn):
    """Devolve (criado, erro). erro = None quando nao da para afirmar que o
    banco falta (ex: senha errada) - nesse caso vale o erro original."""
    from psycopg2 import sql

    nome = psycopg2.extensions.parse_dsn(dsn).get("dbname")
    if not nome:
        return False, None

    conn = None
    for banco_manutencao in ("postgres", "template1"):
        try:
            conn = psycopg2.connect(
                psycopg2.extensions.make_dsn(dsn, dbname=banco_manutencao),
                connect_timeout=CONNECT_TIMEOUT,
            )
            break
        except (psycopg2.Error, UnicodeDecodeError):
            continue
    if conn is None:
        return False, None

    conn.autocommit = True  # CREATE DATABASE nao roda dentro de transacao
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nome,))
            if cur.fetchone():
                return False, None  # o banco existe: o problema e outro
            try:
                cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0")
                            .format(sql.Identifier(nome)))
            except psycopg2.Error:
                # Locale do servidor incompativel com UTF8: usa o padrao do servidor.
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
        return True, None
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        return False, f'Não foi possível criar o banco "{nome}": {_mensagem_erro(exc)}'
    finally:
        conn.close()


def verificar_schema_integra(dsn, schema):
    """Confere se o schema existe no banco do sistema hospitalar e tem todas
    as tabelas usadas pelo sistema. Devolve None se ok, senao a mensagem."""
    try:
        conn = psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT)
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        return _mensagem_erro(exc)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
            if not cur.fetchone():
                return f'O schema "{schema}" não existe neste banco.'
            cur.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = %s AND table_name = ANY(%s)""",
                (schema, list(TABELAS_INTEGRA)),
            )
            encontradas = {linha[0] for linha in cur.fetchall()}
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        return _mensagem_erro(exc)
    finally:
        conn.close()
    faltando = [t for t in TABELAS_INTEGRA if t not in encontradas]
    if faltando:
        return f'O schema "{schema}" não tem as tabelas: {", ".join(faltando)}.'
    return None


def _criar_pool(dsn, maxconn, rotulo, **kwargs):
    try:
        return psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=maxconn, dsn=dsn, connect_timeout=CONNECT_TIMEOUT, **kwargs,
        )
    except (psycopg2.Error, UnicodeDecodeError) as exc:
        raise BancoIndisponivel(f"{rotulo}: {_mensagem_erro(exc)}") from None


def substituir_pools(dsn, dsn_integra, schema_integra):
    """Abre os pools dos dois bancos e passa a usa-los. Se qualquer um falhar
    (ou o schema do sistema hospitalar estiver errado), levanta
    BancoIndisponivel e mantem os pools anteriores.

    As conexoes do sistema hospitalar abrem com search_path = schema_integra,
    por isso as consultas usam o nome das tabelas sem prefixo de schema."""
    global _pool, _pool_integra
    rotulo_integra = "Banco do sistema hospitalar (ISIVITA)"
    if not SCHEMA_VALIDO.match(schema_integra or ""):
        raise BancoIndisponivel(f'{rotulo_integra}: nome de schema inválido: "{schema_integra}".')
    erro_schema = verificar_schema_integra(dsn_integra, schema_integra)
    if erro_schema:
        raise BancoIndisponivel(f"{rotulo_integra}: {erro_schema}")

    novo = _criar_pool(dsn, 10, "Banco principal (sop)")
    try:
        novo_integra = _criar_pool(dsn_integra, 5, rotulo_integra,
                                   options=f'-c search_path="{schema_integra}"')
    except BancoIndisponivel:
        novo.closeall()
        raise
    antigos = (_pool, _pool_integra)
    _pool, _pool_integra = novo, novo_integra
    for pool in antigos:
        if pool is not None:
            _descartar_pool(pool)


def pools_ativos():
    return _pool is not None and _pool_integra is not None


def _descartar_pool(pool):
    """Fecha as conexoes ociosas de um pool substituido. As que estiverem em
    uso por requisicoes em andamento sao fechadas quando forem devolvidas
    (ver _devolver), para nao derrubar consultas no meio."""
    with pool._lock:
        for conn in pool._pool:
            conn.close()
        pool._pool.clear()


def _devolver(pool_origem, pool_atual, conn):
    if pool_origem is pool_atual:
        pool_origem.putconn(conn)
    else:
        conn.close()  # pool antigo (banco reconfigurado durante a requisicao)


def get_conn():
    if "db_conn" not in g:
        g.db_pool = _pool
        g.db_conn = _pool.getconn()
        aplicar_contexto_rls()
    return g.db_conn


def _unidades_da_sessao():
    """Unidades que limitam o acesso do usuario logado ("" = sem restricao:
    admin, usuario sem unidade vinculada ou execucao fora de requisicao)."""
    if not has_request_context() or session.get("perfil") == "admin":
        return ""
    return ",".join(str(int(u)) for u in (session.get("unidade_ids") or []))


def aplicar_contexto_rls():
    """Informa ao Postgres as unidades do usuario da requisicao, lidas pelas
    politicas de row-level security (sql/seguranca.sql) via
    current_setting('app.unidade_ids'). Redefinido a cada requisicao, entao
    uma conexao reaproveitada do pool nunca carrega o valor de outro usuario."""
    conn = g.get("db_conn")
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.unidade_ids', %s, false)", (_unidades_da_sessao(),))
    conn.commit()


def descartar_transacao():
    """Desfaz a transacao em andamento (usado apos um erro inesperado)."""
    conn = g.get("db_conn")
    if conn is not None and not conn.closed:
        conn.rollback()


def get_conn_integra():
    if "db_conn_integra" not in g:
        g.db_pool_integra = _pool_integra
        conn = _pool_integra.getconn()
        conn.set_session(readonly=True, autocommit=True)
        g.db_conn_integra = conn
    return g.db_conn_integra


def close_conn(e=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        _devolver(g.pop("db_pool", None), _pool, conn)

    conn_integra = g.pop("db_conn_integra", None)
    if conn_integra is not None:
        _devolver(g.pop("db_pool_integra", None), _pool_integra, conn_integra)


def query(sql, params=None, fetchone=False, commit=False):
    """Executa uma consulta e retorna linhas como dicionarios."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        rows = None
        if cur.description:
            rows = cur.fetchone() if fetchone else cur.fetchall()
        if commit:
            conn.commit()
        return rows


def query_integra(sql, params=None, fetchone=False):
    """Consulta somente-leitura ao banco do sistema hospitalar (ISIVITA)."""
    conn = get_conn_integra()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        if not cur.description:
            return None
        return cur.fetchone() if fetchone else cur.fetchall()


def execute(sql, params=None):
    """Executa um comando (INSERT/UPDATE/DELETE) e faz commit."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        result = None
        if cur.description:
            result = cur.fetchone()
        conn.commit()
        return result


def register_teardown(app):
    app.teardown_appcontext(close_conn)
