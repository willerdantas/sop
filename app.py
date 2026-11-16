"""
Sistema de Fluxo e Controle de Movimentacao de Prontuarios Fisicos
-------------------------------------------------------------------
Hospital - Setor de Organizacao de Prontuarios (SOP) -> Contas Medicas

Fluxo padrao do prontuario:
    unidade -> sop -> contas_medicas -> pronto_faturamento -> auditoria -> finalizado

Um prontuario so pode ser marcado como "pronto_faturamento" se nao
houver pendencias abertas vinculadas a ele.

Execute com:
    export DATABASE_URL=postgresql://user:pass@host:5432/banco
    export SECRET_KEY=uma-chave-grande
    flask --app app run --debug
"""
import calendar
import os
import re
from datetime import datetime, date, time as dtime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Cada ambiente tem seu proprio arquivo de configuracao (DATABASE_URL,
# INTEGRA_DATABASE_URL, etc.) para nao misturar producao e homologacao.
# AMBIENTE=homolog ja vem definido como variavel de ambiente real (pelo
# docker-compose, via env_file) antes deste load_dotenv rodar.
ARQUIVO_ENV = ".env.homolog" if os.environ.get("AMBIENTE", "").strip().lower() == "homolog" else ".env"
CAMINHO_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_ENV)
# Servidor novo: o arquivo nao vem do git (tem segredos). Cria em branco;
# sem conexao configurada a app sobe no modo de configuracao, e a tela
# /configuracao grava nele a senha do admin e os dados do banco (cifrados).
try:
    os.close(os.open(CAMINHO_ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    print(f"[info] {ARQUIVO_ENV} nao existia: criado em branco (configure em /configuracao).")
except FileExistsError:
    pass
load_dotenv(CAMINHO_ENV)

import psycopg2
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash

import configuracao_inicial
import db
import seguranca
import validacao as v
from config import Config
from crypto_utils import cifrar_campo, decifrar_campos

FLUXO_ORDEM = [
    "unidade",
    "sop",
    "contas_medicas",
    "pronto_faturamento",
    "auditoria",
    "finalizado",
]

STATUS_LABEL = {
    "unidade": "Na Unidade",
    "sop": "SOP",
    "contas_medicas": "Contas Medicas",
    "pronto_faturamento": "Pronto p/ Faturamento",
    "auditoria": "Auditoria",
    "finalizado": "Finalizado",
}

# Altas (sistema hospitalar ISIVITA): isn_destino em t_destino -
# 1 = Residencia, 3 = Outro hospital, 4 = Obito.
ALTAS_DESTINOS_VALIDOS = (1, 3, 4)
ALTAS_DATA_INICIO = "2026-11-01"

# Valores aceitos nos campos de escolha (validados em toda gravacao).
PRIORIDADES = ("normal", "urgente")
CRITICIDADES = ("baixa", "media", "alta")
STATUS_PENDENCIA = ("aberta", "em_analise", "resolvida", "confirmada")
UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)


FUSO_HORARIO_HOSPITAL = ZoneInfo("America/Fortaleza")


def agora_local():
    """Hora atual no fuso do hospital, "naive" (sem tzinfo) para poder ser
    subtraida diretamente dos timestamps do Postgres (tambem naive, mas ja
    gravados nesse mesmo fuso). Sem isso, o relogio do container (que pode
    estar em UTC) fica ate 3h adiantado em relacao ao banco, inflando os
    cronometros de tempo decorrido."""
    return datetime.now(FUSO_HORARIO_HOSPITAL).replace(tzinfo=None)


def horas_uteis_decorridas(inicio, fim):
    """Horas corridas entre 'inicio' e 'fim', descontando sabados e domingos."""
    if fim <= inicio:
        return 0.0
    total = 0.0
    dia = inicio.date()
    while dia <= fim.date():
        inicio_dia = datetime.combine(dia, dtime.min)
        fim_dia = datetime.combine(dia, dtime.max)
        janela_inicio = max(inicio, inicio_dia)
        janela_fim = min(fim, fim_dia)
        if dia.weekday() < 5 and janela_fim > janela_inicio:  # 0-4 = segunda a sexta
            total += (janela_fim - janela_inicio).total_seconds() / 3600
        dia += timedelta(days=1)
    return total

# Unidades (isn_clinica em t_clinica) exibidas na pagina de Unidades.
UNIDADES_PERMITIDAS = (
    15, 17, 18, 20, 21, 22, 23, 24, 34, 35,
    36, 37, 38, 42, 44, 46, 50, 52, 53, 54,
)


def data_br(valor):
    """Data no padrao brasileiro: dd/mm/aa para datas e dd/mm/aa hh:mm para
    data e hora (filtro "data_br" dos templates)."""
    if valor in (None, ""):
        return "-"
    if isinstance(valor, str):
        texto_data = valor.strip()
        try:
            if "T" in texto_data or " " in texto_data:
                valor = datetime.fromisoformat(texto_data)
            else:
                valor = date.fromisoformat(texto_data)
        except ValueError:
            return texto_data
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%y")
    return str(valor)


def primeiras_entradas_internacao(isns_internacao_leito):
    """{isn_internacao_leito: data do primeiro leito da internacao}. A data
    gravada no prontuario e a do ultimo leito; o tempo total de internacao
    conta desde o primeiro. Uma consulta em lote ao sistema hospitalar."""
    isns = sorted({int(i) for i in isns_internacao_leito if i})
    if not isns:
        return {}
    rows = db.query_integra(
        """SELECT ref.isn_internacao_leito, MIN(il.dat_internacao) AS primeira_entrada
           FROM t_internacao_leito ref
           JOIN t_internacao_leito il ON il.isn_internacao = ref.isn_internacao
           WHERE ref.isn_internacao_leito = ANY(%s)
           GROUP BY ref.isn_internacao_leito""",
        (isns,)
    )
    return {int(r["isn_internacao_leito"]): r["primeira_entrada"] for r in rows}


def anexar_internacao_total(linhas):
    """Preenche 'internacao_total_dias' (alta - primeiro leito) nos
    prontuarios. 0 = internacao de menos de um dia (etiqueta "24h")."""
    primeiras = primeiras_entradas_internacao(r.get("integra_isn_internacao_leito") for r in linhas)
    for r in linhas:
        isn = r.get("integra_isn_internacao_leito")
        entrada = (primeiras.get(int(isn)) if isn else None) or r.get("data_internacao")
        alta = r.get("data_alta")
        r["internacao_total_dias"] = (alta - entrada).days if (alta and entrada) else None
    return linhas


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Primeiro: HTTPS, CSRF, cabecalhos e tratamento de erros valem para
    # todas as rotas, inclusive as do modo de configuracao.
    seguranca.init_app(app)
    db.register_teardown(app)

    # Conecta aos bancos. Se nao conseguir, a app sobe em "modo de
    # configuracao" (/configuracao) em vez de cair. Precisa vir antes de
    # register_routes para o bloqueio rodar antes do controle por perfil.
    configuracao_inicial.init_app(app, ao_conectar=_seed_admin)

    app.add_template_filter(data_br, "data_br")
    register_routes(app)
    return app


def _senha_hash_admin_inicial():
    """Hash da senha do primeiro admin, sem nunca usar uma senha fixa:
    1. ADMIN_DEFAULT_SENHA do .env, se definida;
    2. senha criada na configuracao inicial (SETUP_ADMIN_SENHA_HASH);
    3. senha aleatoria, exibida uma unica vez no log do servidor."""
    if Config.ADMIN_DEFAULT_SENHA:
        return generate_password_hash(Config.ADMIN_DEFAULT_SENHA)
    hash_setup = os.environ.get(configuracao_inicial.CHAVE_HASH_SENHA)
    if hash_setup:
        print("[info] admin inicial criado com a senha definida na configuracao inicial.")
        return hash_setup
    import secrets
    senha = secrets.token_urlsafe(12)
    print(f"[IMPORTANTE] admin inicial '{Config.ADMIN_DEFAULT_LOGIN}' criado com a senha "
          f"provisoria: {senha}  (troque-a na tela Usuarios)")
    return generate_password_hash(senha)


def _seed_admin():
    """Cria um usuario admin padrao se a tabela usuarios estiver vazia."""
    try:
        existentes = db.query("SELECT COUNT(*) AS total FROM usuarios", fetchone=True)
        if existentes and existentes["total"] == 0:
            senha_hash = _senha_hash_admin_inicial()
            db.execute(
                """INSERT INTO usuarios (nome, login, senha_hash, perfil, ativo)
                   VALUES (%s, %s, %s, 'admin', TRUE)""",
                ("Administrador", Config.ADMIN_DEFAULT_LOGIN, senha_hash),
            )
    except Exception as exc:
        # Nao derruba a app se o banco ainda nao tiver sido criado/migrado.
        print(f"[aviso] nao foi possivel checar/criar admin padrao: {exc}")


# ---------------------------------------------------------------
# Integracao com o sistema hospitalar (ISIVITA/SESA) - somente leitura
# ---------------------------------------------------------------
def listar_unidades_integra():
    """Unidades (clinicas) ativas, consultadas ao vivo em t_clinica."""
    rows = db.query_integra(
        """SELECT isn_clinica, dsc_clinica
           FROM t_clinica
           WHERE flg_ativo = 'S'
           ORDER BY dsc_clinica"""
    )
    return [{"id": int(r["isn_clinica"]), "nome": r["dsc_clinica"]} for r in rows]


def listar_profissionais_integra():
    """Profissionais do sistema hospitalar (t_profissional), com o conselho
    (t_conselho.cod_conselho), consultados ao vivo."""
    rows = db.query_integra(
        """SELECT p.isn_usuario, TRIM(p.dsc_usuario) AS nome, TRIM(p.num_conselho::text) AS num_conselho,
                  TRIM(c.cod_conselho::text) AS conselho
           FROM t_profissional p
           LEFT JOIN t_conselho c ON c.isn_conselho = p.isn_conselho
           WHERE COALESCE(TRIM(p.dsc_usuario), '') <> ''
           ORDER BY 2"""
    )
    return [{"isn_profissional": r["isn_usuario"], "nome": r["nome"],
             "conselho": r["conselho"], "numero_conselho": r["num_conselho"]} for r in rows]


def nomes_profissionais_integra():
    """Nomes distintos dos profissionais (busca no registro de pendencias)."""
    return sorted({p["nome"] for p in listar_profissionais_integra()})


def listar_unidades_locais_opcoes():
    """Unidades cadastradas localmente (tabela 'unidades'), com id negativo
    para nao colidir com isn_clinica do sistema hospitalar."""
    rows = db.query("SELECT id, nome FROM unidades WHERE ativo = TRUE ORDER BY nome")
    return [{"id": -r["id"], "nome": r["nome"]} for r in rows]


def unidades_do_prontuario(prontuario, historico_leitos):
    """Unidades a que o prontuario pode ser associado (envio para a unidade,
    registro de pendencia): as clinicas do historico de internacao, a unidade
    atual do prontuario e as unidades locais ativas (id negativo)."""
    opcoes, vistas = [], set()
    for h in historico_leitos or []:
        if h.get("isn_clinica") is not None and int(h["isn_clinica"]) not in vistas:
            vistas.add(int(h["isn_clinica"]))
            opcoes.append({"id": int(h["isn_clinica"]), "nome": h["dsc_clinica"]})
    atual = prontuario.get("unidade_id")
    if atual is not None and int(atual) > 0 and int(atual) not in vistas:
        nome = mapa_nomes_unidades([atual]).get(int(atual))
        if nome:
            vistas.add(int(atual))
            opcoes.append({"id": int(atual), "nome": nome})
    return opcoes + listar_unidades_locais_opcoes()


def mapa_nomes_unidades(ids):
    """Recebe uma lista de unidade_id e devolve {id: nome}. IDs positivos sao
    isn_clinica do sistema hospitalar (t_clinica); IDs negativos
    sao unidades cadastradas localmente (tabela 'unidades', id = -unidade_id)."""
    ids_validos = {int(i) for i in ids if i is not None}
    if not ids_validos:
        return {}

    ids_integra = [i for i in ids_validos if i > 0]
    ids_locais = [-i for i in ids_validos if i < 0]

    mapa = {}
    if ids_integra:
        rows = db.query_integra(
            "SELECT isn_clinica, dsc_clinica FROM t_clinica WHERE isn_clinica = ANY(%s)",
            (ids_integra,)
        )
        mapa.update({int(r["isn_clinica"]): r["dsc_clinica"] for r in rows})
    if ids_locais:
        rows = db.query("SELECT id, nome FROM unidades WHERE id = ANY(%s)", (ids_locais,))
        mapa.update({-int(r["id"]): r["nome"] for r in rows})
    return mapa


def anexar_unidade_nome(linhas, campo_id="unidade_id"):
    """Preenche 'unidade_nome' em uma lista (ou linha unica) de dicts, buscando os
    nomes das unidades no sistema hospitalar em uma unica consulta em lote."""
    eh_lista = isinstance(linhas, list)
    itens = linhas if eh_lista else [linhas]
    mapa = mapa_nomes_unidades([item.get(campo_id) for item in itens if item])
    for item in itens:
        if item:
            item["unidade_nome"] = mapa.get(item.get(campo_id))
    return linhas


def unidades_do_usuario(usuario_id):
    """Lista (ints) das unidades vinculadas a um usuario (tabela usuario_unidades)."""
    rows = db.query("SELECT unidade_id FROM usuario_unidades WHERE usuario_id = %s", (usuario_id,))
    return [r["unidade_id"] for r in rows]


def salvar_unidades_usuario(usuario_id, unidade_ids):
    """Substitui as unidades vinculadas a um usuario pela lista recebida."""
    db.execute("DELETE FROM usuario_unidades WHERE usuario_id = %s", (usuario_id,))
    ids_validos = sorted({int(i) for i in (unidade_ids or []) if str(i).strip() != ""})
    for uid in ids_validos:
        db.execute(
            "INSERT INTO usuario_unidades (usuario_id, unidade_id) VALUES (%s, %s)",
            (usuario_id, uid)
        )


def historico_internacao(integra_isn_internacao_leito):
    """Dado o isn_internacao_leito gravado no prontuario (origem: Altas), devolve
    (isn_internacao, historico de clinicas/enfermarias/leitos daquela internacao)."""
    if not integra_isn_internacao_leito:
        return None, []

    referencia = db.query_integra(
        "SELECT isn_internacao FROM t_internacao_leito WHERE isn_internacao_leito = %s",
        (integra_isn_internacao_leito,), fetchone=True
    )
    if not referencia:
        return None, []

    isn_internacao = int(referencia["isn_internacao"])
    registros = db.query_integra(
        """SELECT il.isn_internacao_leito, il.isn_clinica, c.dsc_clinica,
                  e.dsc_enfermaria, l.dsc_leito,
                  il.dat_internacao, il.dat_alta,
                  (COALESCE(il.dat_alta, CURRENT_DATE) - il.dat_internacao) AS dias_clinica
           FROM t_internacao_leito il
           LEFT JOIN t_clinica c ON c.isn_clinica = il.isn_clinica
           LEFT JOIN t_enfermaria e ON e.isn_enfermaria = il.isn_enfermaria
           LEFT JOIN t_leito l ON l.isn_leito = il.isn_leito
           WHERE il.isn_internacao = %s
           ORDER BY il.dat_alta ASC, il.isn_internacao_leito ASC""",
        (isn_internacao,)
    )
    return isn_internacao, registros


def buscar_dados_paciente(isn_internacao):
    """Dados cadastrais do paciente (nascimento, mae, CPF, CNS) e, se a
    internacao terminou em obito (isn_destino = 4 em t_internacao_leito),
    a data dessa alta."""
    if not isn_internacao:
        return {"dat_nascimento": None, "dsc_mae": None, "num_cpf": None,
                "num_cns": None, "data_obito": None}

    paciente = db.query_integra(
        """SELECT p.dat_nascimento, p.dsc_mae, p.num_cpf, p.num_cns
           FROM t_internacao i
           JOIN t_paciente p ON p.isn_paciente = i.isn_paciente
           WHERE i.isn_internacao = %s""",
        (isn_internacao,), fetchone=True
    )
    dat_nascimento = paciente["dat_nascimento"].date() if paciente and paciente["dat_nascimento"] else None

    obito = db.query_integra(
        """SELECT dat_alta FROM t_internacao_leito
           WHERE isn_internacao = %s AND isn_destino = 4
           ORDER BY dat_alta DESC LIMIT 1""",
        (isn_internacao,), fetchone=True
    )
    data_obito = obito["dat_alta"] if obito else None

    return {
        "dat_nascimento": dat_nascimento,
        "dsc_mae": paciente["dsc_mae"] if paciente else None,
        "num_cpf": paciente["num_cpf"] if paciente else None,
        "num_cns": paciente["num_cns"] if paciente else None,
        "data_obito": data_obito,
    }


def listar_cids_internacao(isn_internacao):
    """Lista de CIDs da internacao (t_admissao join t_cid10), com o
    principal (primario='S') primeiro."""
    if not isn_internacao:
        return []
    return db.query_integra(
        """SELECT a.primario, c.cod_cid10, c.dsc_cid10
           FROM t_admissao a
           JOIN t_internacao i ON i.isn_internacao = a.isn_internacao
           LEFT JOIN t_cid10 c ON c.isn_cid10 = a.isn_cid10
           WHERE a.isn_internacao = %s
           ORDER BY a.primario DESC""",
        (isn_internacao,)
    )


def calcular_idade(nascimento, referencia):
    """Idade entre 'nascimento' e 'referencia' (ambos date) em anos, meses e dias."""
    if not nascimento or not referencia or referencia < nascimento:
        return None

    anos = referencia.year - nascimento.year
    meses = referencia.month - nascimento.month
    dias = referencia.day - nascimento.day

    if dias < 0:
        meses -= 1
        mes_anterior = referencia.month - 1 or 12
        ano_mes_anterior = referencia.year if referencia.month > 1 else referencia.year - 1
        dias += calendar.monthrange(ano_mes_anterior, mes_anterior)[1]
    if meses < 0:
        anos -= 1
        meses += 12

    return {"anos": anos, "meses": meses, "dias": dias}


def listar_exames_internacao(isn_internacao):
    """Exames solicitados durante a internacao: t_internacao join t_exame_solic
    (por isn_internacao) join t_exame (por isn_exame) para o nome do exame."""
    if not isn_internacao:
        return []
    return db.query_integra(
        """SELECT es.isn_exame, ex.dsc_exame,
                  es.dat_solicitacao, es.dat_agendamento,
                  es.dat_realizacao, es.dat_cancelamento
           FROM t_internacao i
           JOIN t_exame_solic es ON es.isn_internacao = i.isn_internacao
           LEFT JOIN t_exame ex ON ex.isn_exame = es.isn_exame
           WHERE i.isn_internacao = %s
           ORDER BY es.dat_solicitacao DESC""",
        (isn_internacao,)
    )


def resumir_exames_por_classificacao(exames):
    """Agrupa a lista de exames pela classificacao cadastrada em
    exame_classificacao (local, por isn_exame). Dentro de cada classificacao,
    resume por nome de exame, contando quantas vezes cada um aparece no
    historico (sem trazer datas individuais)."""
    isn_exames = [int(ex["isn_exame"]) for ex in exames if ex.get("isn_exame") is not None]
    mapa_classificacao = {}
    if isn_exames:
        rows = db.query(
            "SELECT isn_exame, classificacao FROM exame_classificacao WHERE isn_exame = ANY(%s)",
            (isn_exames,)
        )
        mapa_classificacao = {r["isn_exame"]: r["classificacao"] for r in rows}

    grupos = {}
    for ex in exames:
        isn = int(ex["isn_exame"]) if ex.get("isn_exame") is not None else None
        classificacao = mapa_classificacao.get(isn) or "Sem classificação"
        nome_exame = ex["dsc_exame"] or "Sem nome"
        contagem_exames = grupos.setdefault(classificacao, {})
        contagem_exames[nome_exame] = contagem_exames.get(nome_exame, 0) + 1

    resultado = []
    for classificacao, contagem_exames in grupos.items():
        exames_resumidos = sorted(
            [{"nome": nome, "quantidade": qtd} for nome, qtd in contagem_exames.items()],
            key=lambda r: r["nome"]
        )
        resultado.append({
            "nome": classificacao,
            "quantidade": sum(contagem_exames.values()),
            "exames": exames_resumidos,
        })
    return sorted(resultado, key=lambda r: r["nome"])


def iniciar_analise(prontuario_id, etapa):
    """Abre uma sessao de analise (SOP ou Contas Medicas) para o usuario
    logado, se ainda nao houver uma em aberto para este prontuario/etapa."""
    aberta = db.query(
        "SELECT id FROM analises_prontuario WHERE prontuario_id = %s AND etapa = %s AND data_fim IS NULL",
        (prontuario_id, etapa), fetchone=True
    )
    if aberta:
        return
    db.execute(
        "INSERT INTO analises_prontuario (prontuario_id, usuario_id, etapa) VALUES (%s,%s,%s)",
        (prontuario_id, session["usuario_id"], etapa)
    )


def encerrar_analises_abertas(prontuario_id):
    """Fecha qualquer sessao de analise em aberto deste prontuario - chamado
    sempre que ele e movido (avanca, e devolvido ou e finalizado)."""
    db.execute(
        "UPDATE analises_prontuario SET data_fim = NOW() WHERE prontuario_id = %s AND data_fim IS NULL",
        (prontuario_id,)
    )


def somar_dias_por_tipo_internacao(historico_leitos):
    """Soma os dias de internacao (dias_clinica) do historico, separando entre
    UTI (clinicas com "UTI" no nome) e enfermaria (as demais)."""
    dias_enfermaria = 0
    dias_uti = 0
    for h in historico_leitos:
        dias = h["dias_clinica"] or 0
        if h["dsc_clinica"] and "uti" in h["dsc_clinica"].lower():
            dias_uti += dias
        else:
            dias_enfermaria += dias
    return dias_enfermaria, dias_uti


def dentro_do_filtro_prazo(dias, filtro):
    """Verifica se 'dias' (dias desde a alta) cai na faixa escolhida no filtro
    de prazo, usando as mesmas faixas da etiqueta colorida (badgeDiasAlta)."""
    if dias is None:
        return False
    if filtro == "30":
        return dias <= 30
    if filtro == "60":
        return 30 < dias <= 60
    if filtro == "80":
        return 60 < dias <= 80
    if filtro == "90":
        return 80 < dias <= 90
    if filtro == "90+":
        return dias > 90
    return True


def listar_altas_pendentes():
    """Altas (destino 1/3/4, internacao real) ainda nao registradas no fluxo,
    com as horas uteis decorridas desde a alta."""
    altas = db.query_integra(
        """SELECT * FROM (
               SELECT DISTINCT ON (il.isn_internacao)
                      il.isn_internacao_leito, il.isn_internacao, il.isn_clinica,
                      il.dat_internacao, il.dat_alta, il.hor_alta,
                      (SELECT MIN(il2.dat_internacao) FROM t_internacao_leito il2
                         WHERE il2.isn_internacao = il.isn_internacao) AS primeira_entrada,
                      il.isn_destino, d.dsc_destino, ma.dsc_motivo_alta,
                      c.dsc_clinica AS unidade_nome,
                      p.num_prontuario, p.dsc_nome AS paciente_nome
               FROM t_internacao_leito il
               JOIN t_internacao i ON i.isn_internacao = il.isn_internacao
               JOIN t_paciente p ON p.isn_paciente = i.isn_paciente
               LEFT JOIN t_clinica c ON c.isn_clinica = il.isn_clinica
               LEFT JOIN t_destino d ON d.isn_destino = il.isn_destino
               LEFT JOIN (
                   SELECT DISTINCT ON (isn_internacao) isn_internacao, cod_tipo_alta
                   FROM t_internacao_alta
                   ORDER BY isn_internacao, dat_cadastro DESC
               ) ia ON ia.isn_internacao = i.isn_internacao
               LEFT JOIN t_motivo_alta ma ON ma.isn_motivo_alta = ia.cod_tipo_alta
               WHERE il.isn_destino = ANY(%s) AND il.dat_alta >= %s
                     AND i.isn_tipo_atendimento = 1
                     AND il.isn_clinica = ANY(%s)
               ORDER BY il.isn_internacao, il.isn_internacao_leito DESC
           ) ultimas_por_internacao
           ORDER BY dat_alta ASC, hor_alta ASC
           LIMIT 500""",
        (list(ALTAS_DESTINOS_VALIDOS), ALTAS_DATA_INICIO, list(UNIDADES_PERMITIDAS))
    )

    ja_importadas = db.query(
        "SELECT integra_isn_internacao_leito FROM prontuarios WHERE integra_isn_internacao_leito IS NOT NULL"
    )
    importadas_ids = {r["integra_isn_internacao_leito"] for r in ja_importadas}

    agora = agora_local()
    pendentes = []
    for a in altas:
        isn = int(a["isn_internacao_leito"])
        if isn in importadas_ids:
            continue

        hor_alta = (a["hor_alta"] or "00:00").strip() or "00:00"
        try:
            hora = datetime.strptime(hor_alta, "%H:%M").time()
        except ValueError:
            hora = dtime.min
        alta_datetime = datetime.combine(a["dat_alta"], hora)
        horas_uteis = horas_uteis_decorridas(alta_datetime, agora)

        pendentes.append({
            "isn_internacao_leito": isn,
            "isn_internacao": int(a["isn_internacao"]) if a["isn_internacao"] is not None else None,
            "isn_clinica": int(a["isn_clinica"]) if a["isn_clinica"] is not None else None,
            "unidade_nome": a["unidade_nome"],
            "dat_internacao": a["dat_internacao"],
            "internacao_total_dias": ((a["dat_alta"] - (a["primeira_entrada"] or a["dat_internacao"])).days
                                      if a["dat_alta"] and (a["primeira_entrada"] or a["dat_internacao"])
                                      else None),
            "dat_alta": a["dat_alta"],
            "hor_alta": a["hor_alta"],
            "isn_destino": int(a["isn_destino"]) if a["isn_destino"] is not None else None,
            "dsc_destino": a["dsc_destino"],
            "dsc_motivo_alta": a["dsc_motivo_alta"],
            "num_prontuario": (a["num_prontuario"] or "").strip(),
            "paciente_nome": a["paciente_nome"],
            "horas_uteis_desde_alta": round(horas_uteis, 2),
            "dias_desde_alta": (agora.date() - a["dat_alta"]).days if a["dat_alta"] else None,
        })
    return pendentes


def validar_pendencia_contra_historico(prontuario, unidade_id, data_ocorrencia):
    """Se o prontuario tiver historico de internacao (importado via Altas), garante
    que a unidade e a data informadas na pendencia pertencem a esse historico.
    Unidades locais (id negativo, tabela 'unidades') nao fazem parte do historico
    do sistema hospitalar, entao sao validadas apenas quanto a existencia/status.
    Sem historico de internacao disponivel, so a unidade local (se houver) e checada."""
    if unidade_id:
        unidade_id = int(unidade_id)
        if unidade_id < 0:
            existe = db.query(
                "SELECT 1 FROM unidades WHERE id = %s AND ativo = TRUE", (-unidade_id,), fetchone=True
            )
            if not existe:
                return "Unidade local informada nao existe ou esta inativa."
            unidade_id = None  # unidade local ja validada, nao faz parte do historico de internacao

    _, historico = historico_internacao(prontuario.get("integra_isn_internacao_leito"))
    if not historico:
        return None

    if unidade_id:
        clinicas_validas = {int(h["isn_clinica"]) for h in historico if h.get("isn_clinica") is not None}
        if prontuario.get("unidade_id") is not None:
            clinicas_validas.add(int(prontuario["unidade_id"]))  # unidade atual (ver unidades_do_prontuario)
        if unidade_id not in clinicas_validas:
            return "Unidade informada nao pertence ao historico de internacao deste prontuario."

    if data_ocorrencia:
        try:
            data = datetime.strptime(data_ocorrencia, "%Y-%m-%d").date()
        except ValueError:
            return "Data da ocorrencia invalida."
        dentro_do_periodo = any(
            h["dat_internacao"] <= data <= (h["dat_alta"] or date.today())
            for h in historico if h.get("dat_internacao")
        )
        if not dentro_do_periodo:
            return "Data da ocorrencia fora dos periodos registrados no historico de internacao."

    return None


# ---------------------------------------------------------------
# Decoradores de autenticacao
# ---------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("usuario_id"):
            if request.path.startswith("/api/"):
                return jsonify({"erro": "nao autenticado"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def perfil_required(*perfis):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("perfil") not in perfis and session.get("perfil") != "admin":
                if request.path.startswith("/api/"):
                    return jsonify({"erro": "sem permissao"}), 403
                flash("Voce nao tem permissao para acessar esta pagina.", "erro")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# Paginas que podem ser atribuidas a um perfil customizado via tela "Perfis".
# "usuarios" e "perfis" ficam de fora de proposito: permanecem exclusivas do
# perfil "admin" (hardcoded), para que nenhum perfil customizado possa se
# autoconceder gestao de usuarios/perfis.
PAGINAS_SELECIONAVEIS = [
    ("dashboard", "Início"),
    ("unidade", "Unidade"),
    ("sop", "SOP"),
    ("contas_medicas", "Contas Médicas"),
    ("pendencias", "Pendências"),
    ("painel", "Painel Tempo Real"),
    ("clinicas", "Clínicas"),
    ("profissionais", "Profissionais"),
    ("procedimentos", "Procedimentos (SIGTAP)"),
    ("painel_monitoramento_sop", "Monitoramento SOP"),
    ("painel_monitoramento_contas_medicas", "Monitoramento Contas Médicas"),
]

# Para cada endpoint controlado, quais paginas (qualquer uma delas) dao acesso.
ENDPOINT_PARA_PAGINAS = {
    "dashboard": ("dashboard",),
    "unidade": ("unidade",),
    "sop": ("sop",),
    "contas_medicas": ("contas_medicas",),
    "pendencias": ("pendencias",),
    "painel": ("painel",),
    "clinicas": ("clinicas",),
    "profissionais": ("profissionais",),
    "procedimentos": ("procedimentos",),
    "painel_monitoramento_sop": ("painel_monitoramento_sop",),
    "painel_monitoramento_contas_medicas": ("painel_monitoramento_contas_medicas",),
    "analise_prontuario": ("sop",),
    "analise_unidade_prontuario": ("unidade",),
    "analise_c_medicas_prontuario": ("contas_medicas",),
    "api_listar_prontuarios": ("sop", "unidade", "contas_medicas"),
    "api_obter_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_buscar_internacoes_prontuario": ("sop",),
    "api_registrar_internacao": ("sop",),
    "api_mover_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_unidades_envio_prontuario": ("sop",),
    "api_confirmar_recebimento_sop": ("sop",),
    "api_confirmar_recebimento_prontuario": ("contas_medicas",),
    "api_editar_valores_faturamento": ("contas_medicas",),
    "api_registrar_analise_auditoria": ("contas_medicas",),
    "api_confirmar_recebimento_unidade": ("unidade",),
    "api_historico_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_listar_altas": ("sop",),
    "api_registrar_alta": ("sop",),
    "api_listar_pendencias": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_criar_pendencia": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_resolver_pendencia": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_confirmar_pendencia": ("sop", "pendencias", "contas_medicas"),
    "api_devolver_pendencia": ("sop", "pendencias", "contas_medicas"),
    "api_painel": ("painel",),
    "api_painel_monitoramento_sop": ("painel_monitoramento_sop",),
    "api_painel_monitoramento_contas_medicas": ("painel_monitoramento_contas_medicas",),
    "api_listar_profissionais": ("profissionais",),
    "api_listar_procedimentos_sigtap": ("procedimentos", "contas_medicas"),
    "api_listar_procedimentos_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_incluir_procedimento_prontuario": ("contas_medicas",),
    "api_excluir_procedimento_prontuario": ("contas_medicas",),
}

# Endpoints de referencia (somente leitura, sem dado sensivel por registro)
# liberados para qualquer usuario autenticado, independente das paginas do perfil.
ENDPOINTS_SEMPRE_PERMITIDOS = {
    "index", "login", "logout", "static",
    "api_unidades", "api_listar_unidades_locais", "api_tipos_pendencia",
}


def paginas_do_perfil(nome_perfil):
    """Lista as paginas liberadas para um perfil (vazio se nao existir/inativo)."""
    perfil_row = db.query(
        "SELECT id FROM perfis WHERE nome = %s AND ativo = TRUE", (nome_perfil,), fetchone=True
    )
    if not perfil_row:
        return []
    rows = db.query("SELECT pagina FROM perfil_paginas WHERE perfil_id = %s", (perfil_row["id"],))
    return [r["pagina"] for r in rows]


def primeira_pagina_permitida(paginas_do_usuario=None):
    """Primeira pagina (na ordem de PAGINAS_SELECIONAVEIS) presente em
    'paginas_do_usuario' (por padrao, as paginas do usuario logado), usada como
    destino seguro apos login ou em bloqueios."""
    if paginas_do_usuario is None:
        paginas_do_usuario = session.get("paginas_permitidas") or []
    for chave, _ in PAGINAS_SELECIONAVEIS:
        if chave in paginas_do_usuario:
            return chave
    return None


def _url_homologacao():
    """Link para a tela de login do ambiente de homologacao (porta 5501),
    mesmo host do ambiente de producao (porta 5500). None fora desse caso
    (ex: acessando ja pela homologacao, ou porta diferente de 5500)."""
    host = request.host
    if ":" not in host:
        return None
    hostname, porta = host.rsplit(":", 1)
    if porta != "5500":
        return None
    return f"//{hostname}:5501/login"


def prontuario_da_unidade_do_usuario(prontuario_row):
    """True se o usuario for admin, se nao tiver nenhuma unidade vinculada
    (sem restricao), ou se o prontuario pertencer a uma das unidades
    vinculadas ao usuario logado."""
    if session.get("perfil") == "admin":
        return True
    unidade_ids = session.get("unidade_ids") or []
    if not unidade_ids:
        return True
    return bool(prontuario_row) and prontuario_row.get("unidade_id") in unidade_ids


def destino_interno(url):
    """Aceita apenas caminhos internos ("/sop"), nunca outro site
    ("//evil.com", "https://evil.com", "/\\evil.com") - evita open redirect."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return None
    if any(ord(c) < 32 for c in url):
        return None
    return url


# Destinos que cada pagina pode dar a um prontuario (os mesmos usados pelos
# botoes de cada tela). Bloqueia, por exemplo, um usuario so da "Unidade"
# de mandar um prontuario direto para "finalizado" chamando a API.
DESTINOS_POR_PAGINA = {
    "unidade": {"sop"},
    "sop": {"sop", "unidade", "contas_medicas"},
    "contas_medicas": {"sop", "pronto_faturamento", "auditoria", "finalizado"},
}


def destinos_permitidos_usuario():
    if session.get("perfil") == "admin":
        return set(FLUXO_ORDEM)
    permitidos = set()
    for pagina in session.get("paginas_permitidas") or []:
        permitidos |= DESTINOS_POR_PAGINA.get(pagina, set())
    return permitidos


def obter_prontuario_autorizado(prontuario_id):
    """(prontuario, None) se existir e for de uma unidade do usuario; senao
    (None, resposta de erro 404/403) - impede acessar registros de outras
    unidades trocando o id na URL."""
    row = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
    if not row:
        return None, (jsonify({"erro": "prontuario nao encontrado"}), 404)
    if not prontuario_da_unidade_do_usuario(row):
        return None, (jsonify({"erro": "sem permissao para acessar este prontuario"}), 403)
    return row, None


def register_routes(app):

    @app.before_request
    def revalidar_sessao():
        """A cada requisicao, confere NO BANCO se o usuario da sessao ainda
        existe e esta ativo, e recarrega perfil, paginas e unidades. Assim
        inativar um usuario, trocar a senha ou mudar o perfil vale na hora,
        e nada do que o navegador guarda e usado para autorizar."""
        if not session.get("usuario_id") or request.endpoint == "static" or not db.pools_ativos():
            return None
        usuario = db.query(
            """SELECT u.nome, u.perfil, u.ativo, u.sessao_versao,
                      ARRAY(SELECT uu.unidade_id FROM usuario_unidades uu
                            WHERE uu.usuario_id = u.id ORDER BY 1) AS unidade_ids,
                      ARRAY(SELECT pp.pagina FROM perfis pf
                            JOIN perfil_paginas pp ON pp.perfil_id = pf.id
                            WHERE pf.nome = u.perfil AND pf.ativo ORDER BY 1) AS paginas
               FROM usuarios u WHERE u.id = %s""",
            (session["usuario_id"],), fetchone=True
        )
        if not usuario or not usuario["ativo"] or usuario["sessao_versao"] != session.get("sessao_versao"):
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"erro": "sessao encerrada - entre novamente"}), 401
            flash("Sua sessão foi encerrada. Entre novamente.", "erro")
            return redirect(url_for("login"))
        atual = {
            "nome": usuario["nome"],
            "perfil": usuario["perfil"],
            "unidade_ids": list(usuario["unidade_ids"]),
            "paginas_permitidas": [] if usuario["perfil"] == "admin" else list(usuario["paginas"]),
        }
        for chave, valor in atual.items():
            if session.get(chave) != valor:
                session[chave] = valor
        db.aplicar_contexto_rls()
        return None

    @app.before_request
    def restringir_acesso_por_perfil():
        if not session.get("usuario_id") or session.get("perfil") == "admin":
            return None
        if request.endpoint is None or request.endpoint in ENDPOINTS_SEMPRE_PERMITIDOS:
            return None

        paginas_requeridas = ENDPOINT_PARA_PAGINAS.get(request.endpoint)
        if paginas_requeridas is None:
            return None  # endpoint nao mapeado: protegido por @perfil_required("admin") no proprio handler

        paginas_do_usuario = session.get("paginas_permitidas") or []
        if any(p in paginas_do_usuario for p in paginas_requeridas):
            return None

        if request.path.startswith("/api/"):
            return jsonify({"erro": "seu perfil nao tem acesso a este recurso"}), 403

        destino = primeira_pagina_permitida()
        if destino is None:
            flash("Seu perfil não tem acesso a nenhuma página do sistema. Contate um administrador.", "erro")
            return redirect(url_for("logout"))
        flash("Seu perfil não tem acesso a esta página.", "erro")
        return redirect(url_for(destino))

    # -----------------------------------------------------------
    # AUTENTICACAO
    # -----------------------------------------------------------
    @app.route("/", methods=["GET"])
    def index():
        if session.get("usuario_id"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    # Hash usado quando o login nao existe: a verificacao leva o mesmo tempo
    # e a resposta nao revela quais logins sao validos.
    hash_falso = generate_password_hash(os.urandom(16).hex())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            login_usuario = request.form.get("login", "").strip()[:60]
            senha = request.form.get("senha", "")[:128]

            espera = seguranca.segundos_bloqueio_login(login_usuario)
            if espera:
                flash(f"Muitas tentativas de login. Aguarde {(espera + 59) // 60} minuto(s) "
                      "e tente novamente.", "erro")
                return render_template("login.html"), 429

            usuario = None
            # Campo isca preenchido = robo: trata como falha, sem avisar.
            if not request.form.get(seguranca.CAMPO_ISCA):
                usuario = db.query(
                    "SELECT * FROM usuarios WHERE login = %s AND ativo = TRUE",
                    (login_usuario,), fetchone=True
                )
            senha_ok = check_password_hash(usuario["senha_hash"] if usuario else hash_falso, senha)

            if usuario and senha_ok:
                seguranca.limpar_falhas_login(login_usuario)
                if not usuario["senha_hash"].startswith("scrypt:"):
                    # Hash antigo/mais fraco: regrava com o algoritmo atual.
                    db.execute("UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                               (generate_password_hash(senha), usuario["id"]))
                session.clear()  # nova sessao: evita fixacao de sessao
                session.permanent = True
                session["usuario_id"] = usuario["id"]
                session["sessao_versao"] = usuario.get("sessao_versao", 0)
                session["nome"] = usuario["nome"]
                session["perfil"] = usuario["perfil"]
                session["unidade_ids"] = unidades_do_usuario(usuario["id"])
                session["paginas_permitidas"] = (
                    [] if usuario["perfil"] == "admin" else paginas_do_perfil(usuario["perfil"])
                )
                db.execute(
                    "UPDATE usuarios SET ultimo_login = NOW() WHERE id = %s",
                    (usuario["id"],)
                )
                if usuario["perfil"] == "admin":
                    paginas_do_usuario = [chave for chave, _ in PAGINAS_SELECIONAVEIS]
                else:
                    paginas_do_usuario = session["paginas_permitidas"]
                tela_inicial = usuario.get("tela_inicial") or "dashboard"
                if tela_inicial not in paginas_do_usuario:
                    tela_inicial = primeira_pagina_permitida(paginas_do_usuario)
                destino_padrao = url_for(tela_inicial or "dashboard")
                destino = destino_interno(request.args.get("next")) or destino_padrao
                return redirect(destino)

            seguranca.registrar_falha_login(login_usuario)
            flash("Login ou senha invalidos.", "erro")

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # -----------------------------------------------------------
    # PAGINAS
    # -----------------------------------------------------------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", active_page="dashboard")

    @app.route("/sop")
    @login_required
    def sop():
        return render_template("sop.html", active_page="sop")

    @app.route("/contas-medicas")
    @login_required
    def contas_medicas():
        return render_template("contas_medicas.html", active_page="contas_medicas")

    @app.route("/clinicas")
    @login_required
    def clinicas():
        POR_PAGINA = 10
        try:
            pagina = max(1, int(request.args.get("pagina", 1)))
        except ValueError:
            pagina = 1

        total = db.query_integra(
            "SELECT COUNT(*) AS total FROM t_clinica WHERE isn_clinica = ANY(%s)",
            (list(UNIDADES_PERMITIDAS),), fetchone=True
        )["total"]
        total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
        pagina = min(pagina, total_paginas)

        unidades = db.query_integra(
            """SELECT isn_clinica, dsc_clinica
               FROM t_clinica
               WHERE isn_clinica = ANY(%s)
               ORDER BY isn_clinica ASC
               LIMIT %s OFFSET %s""",
            (list(UNIDADES_PERMITIDAS), POR_PAGINA, (pagina - 1) * POR_PAGINA)
        )
        tipos_cadastrados = db.query(
            "SELECT isn_clinica, tipo FROM clinicas_tipo WHERE isn_clinica = ANY(%s)",
            ([int(u["isn_clinica"]) for u in unidades],)
        )
        mapa_tipos = {t["isn_clinica"]: t["tipo"] for t in tipos_cadastrados}
        for u in unidades:
            u["tipo"] = mapa_tipos.get(int(u["isn_clinica"]))
        return render_template(
            "clinicas.html", unidades=unidades, active_page="clinicas",
            pagina=pagina, total_paginas=total_paginas, total=total
        )

    @app.route("/unidade")
    @login_required
    def unidade():
        return render_template("unidade.html", active_page="unidade")

    @app.route("/usuarios")
    @login_required
    @perfil_required("admin")
    def usuarios():
        unidades = listar_unidades_integra() + listar_unidades_locais_opcoes()
        perfis = db.query("SELECT nome FROM perfis WHERE ativo = TRUE ORDER BY nome")
        return render_template("usuarios.html", unidades=unidades, perfis=perfis,
                               paginas_disponiveis=PAGINAS_SELECIONAVEIS, active_page="usuarios")

    @app.route("/perfis")
    @login_required
    @perfil_required("admin")
    def perfis():
        return render_template("perfis.html", paginas_disponiveis=PAGINAS_SELECIONAVEIS, active_page="perfis")

    @app.route("/pendencias")
    @login_required
    def pendencias():
        return render_template("pendencias.html", active_page="pendencias")

    def montar_contexto_analise(prontuario_id, destino_erro):
        """Monta o contexto compartilhado pelas paginas de analise de
        prontuario (SOP, Unidade, Contas Medicas). Retorna None (apos
        flash+redirect ja resolvidos pelo chamador) se o acesso for negado."""
        prontuario = db.query(
            "SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True
        )
        if not prontuario:
            flash("Prontuário não encontrado.", "erro")
            return None
        if not prontuario_da_unidade_do_usuario(prontuario):
            flash("Você não tem permissão para acessar este prontuário.", "erro")
            return None
        anexar_unidade_nome(prontuario)
        isn_internacao, historico_leitos = historico_internacao(prontuario.get("integra_isn_internacao_leito"))
        exames = listar_exames_internacao(isn_internacao)
        resumo_exames = resumir_exames_por_classificacao(exames)

        unidades_pendencia = unidades_do_prontuario(prontuario, historico_leitos)

        min_data_ocorrencia = None
        max_data_ocorrencia = None
        if historico_leitos:
            min_data_ocorrencia = min(h["dat_internacao"] for h in historico_leitos if h["dat_internacao"])
            max_data_ocorrencia = max((h["dat_alta"] or date.today()) for h in historico_leitos)

        dias_enfermaria_calc, dias_uti_calc = somar_dias_por_tipo_internacao(historico_leitos)

        dados_paciente = buscar_dados_paciente(isn_internacao)
        idade = calcular_idade(dados_paciente["dat_nascimento"], dados_paciente["data_obito"] or date.today())
        cids = listar_cids_internacao(isn_internacao)

        tipos = db.query("SELECT id, descricao, criticidade FROM tipos_pendencia WHERE ativo = TRUE ORDER BY descricao")
        profissionais = [{"nome": n} for n in nomes_profissionais_integra()]
        return dict(
            prontuario=prontuario, tipos=tipos, profissionais=profissionais,
            isn_internacao=isn_internacao, historico_leitos=historico_leitos,
            exames=exames, resumo_exames=resumo_exames,
            dat_nascimento=dados_paciente["dat_nascimento"], idade=idade,
            dsc_mae=dados_paciente["dsc_mae"], num_cpf=dados_paciente["num_cpf"],
            num_cns=dados_paciente["num_cns"], cids=cids,
            dias_enfermaria_calc=dias_enfermaria_calc, dias_uti_calc=dias_uti_calc,
            internacao_24h=(anexar_internacao_total([dict(prontuario)])[0]["internacao_total_dias"] == 0),
            unidades_pendencia=unidades_pendencia,
            min_data_ocorrencia=min_data_ocorrencia, max_data_ocorrencia=max_data_ocorrencia,
        )

    @app.route("/analise/<int:prontuario_id>")
    @login_required
    def analise_prontuario(prontuario_id):
        contexto = montar_contexto_analise(prontuario_id, "sop")
        if contexto is None:
            return redirect(url_for("sop"))
        iniciar_analise(prontuario_id, "sop")
        return render_template("analise.html", active_page="sop", **contexto)

    @app.route("/analise_unidade/<int:prontuario_id>")
    @login_required
    def analise_unidade_prontuario(prontuario_id):
        contexto = montar_contexto_analise(prontuario_id, "unidade")
        if contexto is None:
            return redirect(url_for("unidade"))
        return render_template("analise_unidade.html", active_page="unidade", **contexto)

    @app.route("/analise_c_medicas/<int:prontuario_id>")
    @login_required
    def analise_c_medicas_prontuario(prontuario_id):
        contexto = montar_contexto_analise(prontuario_id, "contas_medicas")
        if contexto is None:
            return redirect(url_for("contas_medicas"))
        iniciar_analise(prontuario_id, "contas_medicas")
        return render_template("analise_c_medicas.html", active_page="contas_medicas", **contexto)

    @app.route("/painel")
    @login_required
    def painel():
        return render_template("painel.html", active_page="painel")

    @app.route("/painel-monitoramento-sop")
    @login_required
    def painel_monitoramento_sop():
        return render_template("painel_monitoramento_sop.html", active_page="painel_monitoramento_sop")

    @app.route("/painel-monitoramento-contas-medicas")
    @login_required
    def painel_monitoramento_contas_medicas():
        return render_template(
            "painel_monitoramento_contas_medicas.html",
            active_page="painel_monitoramento_contas_medicas"
        )

    @app.route("/profissionais")
    @login_required
    def profissionais():
        return render_template("profissionais.html", active_page="profissionais")

    @app.route("/procedimentos")
    @login_required
    def procedimentos():
        return render_template("procedimentos.html", active_page="procedimentos")

    # -----------------------------------------------------------
    # API - PRONTUARIOS / FLUXO
    # -----------------------------------------------------------
    @app.route("/api/prontuarios", methods=["GET"])
    @login_required
    def api_listar_prontuarios():
        args = request.args
        status = v.escolha(args.get("status"), "status", FLUXO_ORDEM)
        busca = v.termo_busca(args.get("q"))
        numero = v.termo_busca(args.get("numero"))
        nome = v.termo_busca(args.get("nome"))
        data_inicio = v.data_iso(args.get("data_inicio"), "data inicial")
        data_fim = v.data_iso(args.get("data_fim"), "data final")
        # Devolvidos ao SOP aguardando confirmacao: "1" so eles, "0" sem eles.
        aguardando_sop = args.get("aguardando_sop")

        sql = """
            SELECT p.*,
                (SELECT COUNT(*) FROM pendencias pe
                    WHERE pe.prontuario_id = p.id AND pe.status != 'confirmada') AS pendencias_abertas,
                (SELECT MAX(m.data_movimentacao) FROM movimentacoes m
                    WHERE m.prontuario_id = p.id AND m.destino = 'sop') AS entrou_sop_em,
                (SELECT MAX(m.data_movimentacao) FROM movimentacoes m
                    WHERE m.prontuario_id = p.id AND m.destino = 'unidade') AS enviado_unidade_em,
                (SELECT nome FROM usuarios WHERE id = p.recebido_contas_medicas_usuario_id)
                    AS recebido_contas_medicas_usuario_nome,
                (SELECT u.nome FROM movimentacoes m JOIN usuarios u ON u.id = m.usuario_id
                    WHERE m.prontuario_id = p.id AND m.destino = 'pronto_faturamento'
                    ORDER BY m.data_movimentacao DESC LIMIT 1) AS faturamento_usuario_nome,
                (SELECT nome FROM usuarios WHERE id = p.auditoria_analisado_usuario_id)
                    AS auditoria_analisado_usuario_nome,
                (SELECT u.nome FROM movimentacoes m JOIN usuarios u ON u.id = m.usuario_id
                    WHERE m.prontuario_id = p.id AND m.destino = 'finalizado'
                    ORDER BY m.data_movimentacao DESC LIMIT 1) AS finalizado_usuario_nome
            FROM prontuarios p
            WHERE 1=1
        """
        params = []
        if status:
            sql += " AND p.status_atual = %s"
            params.append(status)
        if aguardando_sop in ("0", "1"):
            sql += " AND p.aguardando_recebimento_sop = %s"
            params.append(aguardando_sop == "1")
        if busca:
            sql += " AND (p.numero_prontuario ILIKE %s OR p.paciente_nome ILIKE %s)"
            params += [f"%{busca}%", f"%{busca}%"]
        if numero:
            sql += " AND p.numero_prontuario ILIKE %s"
            params.append(f"%{numero}%")
        if nome:
            sql += " AND p.paciente_nome ILIKE %s"
            params.append(f"%{nome}%")
        if data_inicio:
            sql += " AND p.data_internacao >= %s"
            params.append(data_inicio)
        if data_fim:
            sql += " AND p.data_internacao <= %s"
            params.append(data_fim)
        if session.get("perfil") != "admin" and session.get("unidade_ids"):
            sql += " AND p.unidade_id = ANY(%s)"
            params.append(session.get("unidade_ids"))
        sql += " ORDER BY p.atualizado_em DESC LIMIT 300"

        rows = db.query(sql, params)
        anexar_unidade_nome(rows)
        anexar_internacao_total(rows)

        agora = agora_local()
        for row in rows:
            if row["status_atual"] == "sop" and row["entrou_sop_em"]:
                row["horas_uteis_no_sop"] = round(horas_uteis_decorridas(row["entrou_sop_em"], agora), 2)
            else:
                row["horas_uteis_no_sop"] = None

            if row["status_atual"] == "unidade" and row["recebido_unidade_em"]:
                row["horas_uteis_na_unidade"] = round(horas_uteis_decorridas(row["recebido_unidade_em"], agora), 2)
            else:
                row["horas_uteis_na_unidade"] = None

            # Tempo na unidade contado desde o envio (inclui a espera pela
            # confirmacao de recebimento) - usado na lista do SOP.
            if row["status_atual"] == "unidade" and row["enviado_unidade_em"]:
                row["horas_uteis_desde_envio_unidade"] = round(
                    horas_uteis_decorridas(row["enviado_unidade_em"], agora), 2)
            else:
                row["horas_uteis_desde_envio_unidade"] = None

            row["dias_desde_alta"] = (agora.date() - row["data_alta"]).days if row["data_alta"] else None

        return jsonify(rows)

    @app.route("/api/prontuarios/<int:prontuario_id>", methods=["GET"])
    @login_required
    def api_obter_prontuario(prontuario_id):
        row = db.query(
            """SELECT p.*,
                (SELECT COUNT(*) FROM pendencias pe
                    WHERE pe.prontuario_id = p.id AND pe.status != 'confirmada') AS pendencias_abertas
               FROM prontuarios p
               WHERE p.id = %s""",
            (prontuario_id,), fetchone=True
        )
        if not row:
            return jsonify({"erro": "prontuario nao encontrado"}), 404
        if not prontuario_da_unidade_do_usuario(row):
            return jsonify({"erro": "sem permissao para ver este prontuario"}), 403
        anexar_unidade_nome(row)
        return jsonify(row)

    @app.route("/api/prontuarios/<int:prontuario_id>/mover", methods=["POST"])
    @login_required
    def api_mover_prontuario(prontuario_id):
        data = v.corpo_json()
        destino = data.get("destino")
        observacao = v.texto(data.get("observacao"), "observacao", 2000, padrao="", multilinha=True)

        if destino not in FLUXO_ORDEM:
            return jsonify({"erro": "status de destino invalido"}), 400

        atual, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        if session.get("perfil") == "operador" and destino != "sop":
            return jsonify({"erro": "perfil operador so pode enviar o prontuario para o SOP"}), 403
        if destino not in destinos_permitidos_usuario():
            return jsonify({"erro": "seu perfil nao pode enviar o prontuario para este destino"}), 403
        if atual["status_atual"] == "sop" and atual.get("aguardando_recebimento_sop"):
            return jsonify({"erro": "confirme o recebimento do prontuario devolvido antes de movimenta-lo"}), 409

        # Regra de negocio: so pode ir para "contas_medicas" ou alem quando nao
        # houver pendencia cadastrada, ou todas estiverem confirmadas pelo SOP
        # (uma pendencia "resolvida" pela unidade ainda aguarda confirmacao).
        if destino in ("contas_medicas", "pronto_faturamento", "auditoria", "finalizado"):
            abertas = db.query(
                "SELECT COUNT(*) AS total FROM pendencias WHERE prontuario_id = %s AND status != 'confirmada'",
                (prontuario_id,), fetchone=True
            )
            if abertas["total"] > 0:
                return jsonify({
                    "erro": "prontuario possui pendencias nao confirmadas e nao pode avancar",
                    "pendencias_abertas": abertas["total"]
                }), 409

        unidade_envio = None
        if destino == "unidade":
            # O SOP escolhe para qual unidade o prontuario volta: uma das
            # unidades do historico de internacao/atual ou uma unidade local.
            unidade_envio = v.inteiro(data.get("unidade_id"), "unidade de destino", obrigatorio=True)
            _, historico = historico_internacao(atual.get("integra_isn_internacao_leito"))
            opcoes = {u["id"]: u["nome"] for u in unidades_do_prontuario(atual, historico)}
            if unidade_envio not in opcoes:
                return jsonify({"erro": "unidade de destino nao pertence a este prontuario"}), 400
            observacao = (f"Enviado para a unidade {opcoes[unidade_envio]}"
                          + (f" - {observacao}" if observacao else ""))[:2000]

        if destino == "contas_medicas":
            # Toda nova chegada em contas_medicas exige nova confirmacao de entrega.
            db.execute(
                "UPDATE prontuarios SET status_atual = %s, recebido_contas_medicas_em = NULL WHERE id = %s",
                (destino, prontuario_id)
            )
        elif destino == "unidade":
            # Toda nova chegada na unidade (vinda do SOP) exige nova confirmacao de entrega.
            db.execute(
                "UPDATE prontuarios SET status_atual = %s, unidade_id = %s, recebido_unidade_em = NULL WHERE id = %s",
                (destino, unidade_envio, prontuario_id)
            )
        elif destino == "sop" and atual["status_atual"] in ("unidade", "contas_medicas"):
            # Devolvido ao SOP pela Unidade ou por Contas Medicas: fica em
            # "Prontuarios Devolvidos" ate o SOP confirmar o recebimento.
            db.execute(
                """UPDATE prontuarios SET status_atual = %s, aguardando_recebimento_sop = TRUE,
                       devolvido_sop_por = %s, recebido_sop_em = NULL, recebido_sop_usuario_id = NULL
                   WHERE id = %s""",
                (destino, atual["status_atual"], prontuario_id)
            )
        else:
            db.execute(
                "UPDATE prontuarios SET status_atual = %s WHERE id = %s",
                (destino, prontuario_id)
            )
        db.execute(
            """INSERT INTO movimentacoes (prontuario_id, origem, destino, usuario_id, observacao)
               VALUES (%s,%s,%s,%s,%s)""",
            (prontuario_id, atual["status_atual"], destino, session["usuario_id"], observacao)
        )
        encerrar_analises_abertas(prontuario_id)
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/unidades-envio", methods=["GET"])
    @login_required
    def api_unidades_envio_prontuario(prontuario_id):
        """Opcoes de unidade para "Enviar p/ Unidade" (ver unidades_do_prontuario)."""
        atual, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        _, historico = historico_internacao(atual.get("integra_isn_internacao_leito"))
        return jsonify({"atual": atual.get("unidade_id"),
                        "unidades": unidades_do_prontuario(atual, historico)})

    @app.route("/api/prontuarios/<int:prontuario_id>/confirmar-recebimento", methods=["POST"])
    @login_required
    def api_confirmar_recebimento_prontuario(prontuario_id):
        atual, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        if atual["status_atual"] != "contas_medicas":
            return jsonify({"erro": "prontuario nao esta aguardando recebimento em contas medicas"}), 400
        if atual["recebido_contas_medicas_em"]:
            return jsonify({"erro": "entrega deste prontuario ja foi confirmada"}), 409

        db.execute(
            "UPDATE prontuarios SET recebido_contas_medicas_em = NOW(), recebido_contas_medicas_usuario_id = %s WHERE id = %s",
            (session["usuario_id"], prontuario_id)
        )
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/valores-faturamento", methods=["PUT"])
    @login_required
    def api_editar_valores_faturamento(prontuario_id):
        data = v.corpo_json()
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro

        atualizado = db.execute(
            """UPDATE prontuarios
               SET dias_enfermaria=%s, dias_uti=%s, diaria_acompanhante=%s
               WHERE id=%s RETURNING *""",
            (v.inteiro(data.get("dias_enfermaria"), "dias de enfermaria", minimo=0, maximo=3650),
             v.inteiro(data.get("dias_uti"), "dias de UTI", minimo=0, maximo=3650),
             v.inteiro(data.get("diaria_acompanhante"), "diarias de acompanhante", minimo=0, maximo=3650),
             prontuario_id)
        )
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/registrar-analise-auditoria", methods=["POST"])
    @login_required
    def api_registrar_analise_auditoria(prontuario_id):
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        db.execute(
            "UPDATE prontuarios SET auditoria_analisado_em = NOW(), auditoria_analisado_usuario_id = %s WHERE id = %s",
            (session["usuario_id"], prontuario_id)
        )
        return jsonify({"ok": True})

    @app.route("/api/prontuarios/<int:prontuario_id>/confirmar-recebimento-unidade", methods=["POST"])
    @login_required
    def api_confirmar_recebimento_unidade(prontuario_id):
        atual, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        if atual["status_atual"] != "unidade":
            return jsonify({"erro": "prontuario nao esta aguardando recebimento na unidade"}), 400
        if atual["recebido_unidade_em"]:
            return jsonify({"erro": "entrega deste prontuario ja foi confirmada"}), 409

        db.execute(
            "UPDATE prontuarios SET recebido_unidade_em = NOW() WHERE id = %s",
            (prontuario_id,)
        )
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/confirmar-recebimento-sop", methods=["POST"])
    @login_required
    def api_confirmar_recebimento_sop(prontuario_id):
        """SOP confirma que recebeu um prontuario devolvido pela Unidade ou por
        Contas Medicas; a partir dai ele volta a lista "Prontuarios no SOP"."""
        atual, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        if atual["status_atual"] != "sop" or not atual.get("aguardando_recebimento_sop"):
            return jsonify({"erro": "prontuario nao esta aguardando recebimento no SOP"}), 409
        db.execute(
            """UPDATE prontuarios SET aguardando_recebimento_sop = FALSE, recebido_sop_em = NOW(),
                   recebido_sop_usuario_id = %s
               WHERE id = %s""",
            (session["usuario_id"], prontuario_id)
        )
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/historico", methods=["GET"])
    @login_required
    def api_historico_prontuario(prontuario_id):
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro

        rows = db.query(
            """SELECT m.*, u.nome AS usuario_nome
               FROM movimentacoes m
               LEFT JOIN usuarios u ON u.id = m.usuario_id
               WHERE m.prontuario_id = %s
               ORDER BY m.data_movimentacao DESC""",
            (prontuario_id,)
        )
        return jsonify(rows)

    # -----------------------------------------------------------
    # API - ALTAS (integracao com o sistema hospitalar ISIVITA)
    # -----------------------------------------------------------
    @app.route("/api/altas", methods=["GET"])
    @login_required
    def api_listar_altas():
        POR_PAGINA = 10
        try:
            pagina = max(1, int(request.args.get("pagina", 1)))
        except ValueError:
            pagina = 1
        prazo = v.escolha(request.args.get("prazo"), "prazo", ("30", "60", "80", "90", "90+"))

        pendentes = listar_altas_pendentes()
        if prazo:
            pendentes = [a for a in pendentes if dentro_do_filtro_prazo(a["dias_desde_alta"], prazo)]
        total = len(pendentes)

        # Para exportar o relatorio (PDF/Excel), devolve todos os itens
        # filtrados de uma vez, sem paginar.
        if request.args.get("exportar"):
            return jsonify({"itens": pendentes, "total": total})

        total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
        pagina = min(pagina, total_paginas)
        inicio = (pagina - 1) * POR_PAGINA
        itens = pendentes[inicio:inicio + POR_PAGINA]

        return jsonify({
            "itens": itens,
            "total": total,
            "pagina": pagina,
            "total_paginas": total_paginas,
        })

    @app.route("/api/altas/<int:isn_internacao_leito>/registrar", methods=["POST"])
    @login_required
    def api_registrar_alta(isn_internacao_leito):
        ja_existe = db.query(
            "SELECT id FROM prontuarios WHERE integra_isn_internacao_leito = %s",
            (isn_internacao_leito,), fetchone=True
        )
        if ja_existe:
            return jsonify({"erro": "esta alta ja foi registrada no fluxo"}), 409

        alta = db.query_integra(
            """SELECT il.isn_internacao_leito, il.isn_clinica, il.dat_internacao,
                      il.dat_alta, d.dsc_destino, ma.dsc_motivo_alta,
                      c.dsc_clinica AS unidade_nome,
                      p.num_prontuario, p.dsc_nome AS paciente_nome
               FROM t_internacao_leito il
               JOIN t_internacao i ON i.isn_internacao = il.isn_internacao
               JOIN t_paciente p ON p.isn_paciente = i.isn_paciente
               LEFT JOIN t_clinica c ON c.isn_clinica = il.isn_clinica
               LEFT JOIN t_destino d ON d.isn_destino = il.isn_destino
               LEFT JOIN (
                   SELECT DISTINCT ON (isn_internacao) isn_internacao, cod_tipo_alta
                   FROM t_internacao_alta
                   ORDER BY isn_internacao, dat_cadastro DESC
               ) ia ON ia.isn_internacao = i.isn_internacao
               LEFT JOIN t_motivo_alta ma ON ma.isn_motivo_alta = ia.cod_tipo_alta
               WHERE il.isn_internacao_leito = %s AND i.isn_tipo_atendimento = 1""",
            (isn_internacao_leito,), fetchone=True
        )
        if not alta:
            return jsonify({"erro": "alta nao encontrada no sistema hospitalar"}), 404
        if alta["isn_clinica"] is None or int(alta["isn_clinica"]) not in UNIDADES_PERMITIDAS:
            return jsonify({"erro": "altas desta clinica nao podem ser registradas pelo SOP"}), 403

        numero_prontuario = (alta["num_prontuario"] or "").strip()
        if not numero_prontuario:
            return jsonify({"erro": "esta alta nao possui numero de prontuario no sistema hospitalar"}), 400
        if not prontuario_da_unidade_do_usuario({"unidade_id": int(alta["isn_clinica"])}):
            return jsonify({"erro": "sem permissao para registrar altas desta unidade"}), 403

        data = v.corpo_json()
        prioridade = v.escolha(data.get("prioridade"), "prioridade", PRIORIDADES, padrao="normal")
        localizacao = v.texto(data.get("localizacao_fisica"), "localizacao fisica", 120)

        try:
            novo = db.execute(
                """INSERT INTO prontuarios
                    (numero_prontuario, paciente_nome, unidade_id, data_internacao,
                     data_alta, prioridade, localizacao_fisica, status_atual,
                     integra_isn_internacao_leito)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'sop',%s)
                   RETURNING *""",
                (
                    numero_prontuario, alta["paciente_nome"],
                    int(alta["isn_clinica"]) if alta["isn_clinica"] is not None else None,
                    alta["dat_internacao"], alta["dat_alta"],
                    prioridade, localizacao,
                    isn_internacao_leito,
                )
            )
            db.execute(
                """INSERT INTO movimentacoes (prontuario_id, origem, destino, usuario_id, observacao)
                   VALUES (%s, 'cadastro', 'sop', %s, %s)""",
                (novo["id"], session["usuario_id"],
                 f"Alta hospitalar importada do IntegraSH ({alta['dsc_destino'] or 'destino nao informado'})")
            )
            return jsonify(novo), 201
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "numero de prontuario ja cadastrado"}), 409

    @app.route("/api/internacoes/buscar", methods=["GET"])
    @login_required
    def api_buscar_internacoes_prontuario():
        numero = v.texto(request.args.get("numero"), "numero do prontuario", 30)
        if not numero:
            return jsonify({"erro": "informe o numero do prontuario"}), 400

        internacoes = db.query_integra(
            """SELECT i.isn_internacao, p.num_prontuario, p.dsc_nome AS paciente_nome,
                      MIN(il.dat_internacao) AS dat_internacao, MAX(il.dat_alta) AS dat_alta,
                      (ARRAY_AGG(il.isn_internacao_leito ORDER BY il.isn_internacao_leito DESC))[1]
                          AS isn_internacao_leito,
                      (ARRAY_AGG(d.dsc_destino ORDER BY il.isn_internacao_leito DESC))[1]
                          AS dsc_destino,
                      ma.dsc_motivo_alta
               FROM t_internacao i
               JOIN t_paciente p ON p.isn_paciente = i.isn_paciente
               JOIN t_internacao_leito il ON il.isn_internacao = i.isn_internacao
               LEFT JOIN t_destino d ON d.isn_destino = il.isn_destino
               LEFT JOIN (
                   SELECT DISTINCT ON (isn_internacao) isn_internacao, cod_tipo_alta
                   FROM t_internacao_alta
                   ORDER BY isn_internacao, dat_cadastro DESC
               ) ia ON ia.isn_internacao = i.isn_internacao
               LEFT JOIN t_motivo_alta ma ON ma.isn_motivo_alta = ia.cod_tipo_alta
               WHERE p.num_prontuario = %s AND i.isn_tipo_atendimento = 1
               GROUP BY i.isn_internacao, p.num_prontuario, p.dsc_nome, ma.dsc_motivo_alta
               ORDER BY dat_internacao DESC""",
            (numero,)
        )
        if not internacoes:
            return jsonify([])

        isn_leitos = [int(i["isn_internacao_leito"]) for i in internacoes]
        registrados = db.query(
            "SELECT integra_isn_internacao_leito, status_atual FROM prontuarios WHERE integra_isn_internacao_leito = ANY(%s)",
            (isn_leitos,)
        )
        mapa_registrados = {r["integra_isn_internacao_leito"]: r["status_atual"] for r in registrados}

        for i in internacoes:
            leito = int(i["isn_internacao_leito"])
            i["status_atual"] = mapa_registrados.get(leito)

        return jsonify(internacoes)

    @app.route("/api/internacoes/<int:isn_internacao_leito>/registrar", methods=["POST"])
    @login_required
    def api_registrar_internacao(isn_internacao_leito):
        ja_existe = db.query(
            "SELECT id FROM prontuarios WHERE integra_isn_internacao_leito = %s",
            (isn_internacao_leito,), fetchone=True
        )
        if ja_existe:
            return jsonify({"erro": "esta internacao ja foi registrada no fluxo"}), 409

        internacao = db.query_integra(
            """SELECT il.isn_internacao_leito, il.isn_clinica, il.dat_internacao, il.dat_alta,
                      p.num_prontuario, p.dsc_nome AS paciente_nome
               FROM t_internacao_leito il
               JOIN t_internacao i ON i.isn_internacao = il.isn_internacao
               JOIN t_paciente p ON p.isn_paciente = i.isn_paciente
               WHERE il.isn_internacao_leito = %s AND i.isn_tipo_atendimento = 1""",
            (isn_internacao_leito,), fetchone=True
        )
        if not internacao:
            return jsonify({"erro": "internacao nao encontrada no sistema hospitalar"}), 404

        numero_prontuario = (internacao["num_prontuario"] or "").strip()
        if not numero_prontuario:
            return jsonify({"erro": "esta internacao nao possui numero de prontuario no sistema hospitalar"}), 400
        unidade_internacao = int(internacao["isn_clinica"]) if internacao["isn_clinica"] is not None else None
        if not prontuario_da_unidade_do_usuario({"unidade_id": unidade_internacao}):
            return jsonify({"erro": "sem permissao para registrar internacoes desta unidade"}), 403

        data = v.corpo_json()
        prioridade = v.escolha(data.get("prioridade"), "prioridade", PRIORIDADES, padrao="normal")
        localizacao = v.texto(data.get("localizacao_fisica"), "localizacao fisica", 120)

        try:
            novo = db.execute(
                """INSERT INTO prontuarios
                    (numero_prontuario, paciente_nome, unidade_id, data_internacao,
                     data_alta, prioridade, localizacao_fisica, status_atual,
                     integra_isn_internacao_leito)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'sop',%s)
                   RETURNING *""",
                (
                    numero_prontuario, internacao["paciente_nome"],
                    unidade_internacao,
                    internacao["dat_internacao"], internacao["dat_alta"],
                    prioridade, localizacao,
                    isn_internacao_leito,
                )
            )
            db.execute(
                """INSERT INTO movimentacoes (prontuario_id, origem, destino, usuario_id, observacao)
                   VALUES (%s, 'cadastro', 'sop', %s, 'Registrado manualmente via busca por numero de prontuario')""",
                (novo["id"], session["usuario_id"])
            )
            return jsonify(novo), 201
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "numero de prontuario ja cadastrado"}), 409

    # -----------------------------------------------------------
    # API - PENDENCIAS
    # -----------------------------------------------------------
    @app.route("/api/pendencias", methods=["GET"])
    @login_required
    def api_listar_pendencias():
        status = v.escolha(request.args.get("status"), "status", STATUS_PENDENCIA)
        prontuario_id = v.inteiro(request.args.get("prontuario_id"), "prontuario_id", minimo=1)
        minha_unidade = request.args.get("minha_unidade")
        sql = """
            SELECT pe.*, p.numero_prontuario, p.paciente_nome,
                   tp.descricao AS tipo_descricao, tp.criticidade,
                   ur.nome AS usuario_resolucao_nome
            FROM pendencias pe
            JOIN prontuarios p ON p.id = pe.prontuario_id
            LEFT JOIN tipos_pendencia tp ON tp.id = pe.tipo_pendencia_id
            LEFT JOIN usuarios ur ON ur.id = pe.usuario_resolucao_id
            WHERE 1=1
        """
        params = []
        if status:
            sql += " AND pe.status = %s"
            params.append(status)
        if prontuario_id:
            sql += " AND pe.prontuario_id = %s"
            params.append(prontuario_id)
        if minha_unidade:
            # Pendencias cuja "Unidade da Ocorrencia" e uma das unidades do usuario
            # logado, independente de onde o prontuario esteja agora no fluxo.
            sql += " AND pe.unidade_id = ANY(%s)"
            params.append(session.get("unidade_ids") or [])
        elif session.get("perfil") != "admin" and session.get("unidade_ids"):
            sql += " AND p.unidade_id = ANY(%s)"
            params.append(session.get("unidade_ids"))
        sql += " ORDER BY pe.data_abertura DESC LIMIT 300"
        rows = db.query(sql, params)
        anexar_unidade_nome(rows)

        agora = agora_local()
        for row in rows:
            if row["status"] == "confirmada":
                row["horas_uteis_desde_abertura"] = None
            else:
                row["horas_uteis_desde_abertura"] = round(horas_uteis_decorridas(row["data_abertura"], agora), 2)

        return jsonify(rows)

    @app.route("/api/pendencias", methods=["POST"])
    @login_required
    def api_criar_pendencia():
        data = v.corpo_json()
        prontuario_id = v.inteiro(data.get("prontuario_id"), "prontuario_id", minimo=1)
        descricao = v.texto(data.get("descricao"), "descricao", 2000, multilinha=True)
        tipo_pendencia_id = v.inteiro(data.get("tipo_pendencia_id"), "tipo de pendencia", minimo=1)
        profissional = v.texto(data.get("profissional"), "profissional", 150)
        data_ocorrencia = v.data_iso(data.get("data_ocorrencia"), "data da ocorrencia")
        unidade_id = v.inteiro(data.get("unidade_id"), "unidade") or None

        if not prontuario_id or not descricao:
            return jsonify({"erro": "prontuario_id e descricao sao obrigatorios"}), 400
        if not unidade_id or not data_ocorrencia:
            return jsonify({"erro": "unidade_id e data_ocorrencia sao obrigatorios"}), 400
        if tipo_pendencia_id and not db.query(
            "SELECT 1 FROM tipos_pendencia WHERE id = %s AND ativo = TRUE", (tipo_pendencia_id,), fetchone=True
        ):
            return jsonify({"erro": "tipo de pendencia invalido"}), 400
        # Profissional e opcional; se informado, tem que existir no sistema hospitalar.
        if profissional and not db.query_integra(
            "SELECT 1 FROM t_profissional WHERE TRIM(dsc_usuario) = %s LIMIT 1", (profissional,), fetchone=True
        ):
            return jsonify({"erro": "profissional nao encontrado no sistema hospitalar"}), 400

        prontuario_row, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro

        erro_historico = validar_pendencia_contra_historico(
            prontuario_row, unidade_id, data_ocorrencia.isoformat())
        if erro_historico:
            return jsonify({"erro": erro_historico}), 400

        nova = db.execute(
            """INSERT INTO pendencias
                (prontuario_id, tipo_pendencia_id, descricao, profissional, data_ocorrencia, unidade_id, usuario_abertura_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (prontuario_id, tipo_pendencia_id, descricao, profissional, data_ocorrencia, unidade_id, session["usuario_id"])
        )
        return jsonify(nova), 201

    @app.route("/api/pendencias/<int:pendencia_id>/resolver", methods=["POST"])
    @login_required
    def api_resolver_pendencia(pendencia_id):
        pendencia = db.query("SELECT * FROM pendencias WHERE id = %s", (pendencia_id,), fetchone=True)
        if not pendencia:
            return jsonify({"erro": "pendencia nao encontrada"}), 404
        unidade_ids = session.get("unidade_ids") or []
        if session.get("perfil") != "admin" and unidade_ids and pendencia["unidade_id"] not in unidade_ids:
            return jsonify({"erro": "sem permissao para resolver esta pendencia"}), 403

        db.execute(
            """UPDATE pendencias
               SET status = 'resolvida', usuario_resolucao_id = %s, data_resolucao = NOW()
               WHERE id = %s""",
            (session["usuario_id"], pendencia_id)
        )
        return jsonify({"ok": True})

    @app.route("/api/pendencias/<int:pendencia_id>/confirmar", methods=["POST"])
    @login_required
    def api_confirmar_pendencia(pendencia_id):
        if session.get("perfil") == "operador":
            return jsonify({"erro": "perfil operador nao pode confirmar pendencias"}), 403

        pendencia = db.query("SELECT * FROM pendencias WHERE id = %s", (pendencia_id,), fetchone=True)
        if not pendencia:
            return jsonify({"erro": "pendencia nao encontrada"}), 404
        _, erro = obter_prontuario_autorizado(pendencia["prontuario_id"])
        if erro:
            return erro
        if pendencia["status"] != "resolvida":
            return jsonify({"erro": "pendencia precisa estar resolvida pela unidade antes de ser confirmada"}), 400

        db.execute("UPDATE pendencias SET status = 'confirmada' WHERE id = %s", (pendencia_id,))
        return jsonify({"ok": True})

    @app.route("/api/pendencias/<int:pendencia_id>/devolver", methods=["POST"])
    @login_required
    def api_devolver_pendencia(pendencia_id):
        if session.get("perfil") == "operador":
            return jsonify({"erro": "perfil operador nao pode devolver pendencias"}), 403

        pendencia = db.query("SELECT * FROM pendencias WHERE id = %s", (pendencia_id,), fetchone=True)
        if not pendencia:
            return jsonify({"erro": "pendencia nao encontrada"}), 404
        _, erro = obter_prontuario_autorizado(pendencia["prontuario_id"])
        if erro:
            return erro
        if pendencia["status"] != "resolvida":
            return jsonify({"erro": "pendencia precisa estar resolvida pela unidade para ser devolvida"}), 400

        db.execute(
            """UPDATE pendencias
               SET status = 'aberta', usuario_resolucao_id = NULL, data_resolucao = NULL
               WHERE id = %s""",
            (pendencia_id,)
        )
        return jsonify({"ok": True})

    @app.route("/api/tipos-pendencia", methods=["GET"])
    @login_required
    def api_tipos_pendencia():
        return jsonify(db.query("SELECT * FROM tipos_pendencia ORDER BY descricao"))

    @app.route("/api/tipos-pendencia", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_tipo_pendencia():
        data = v.corpo_json()
        descricao = v.texto(data.get("descricao"), "descricao", 150, obrigatorio=True)

        novo = db.execute(
            """INSERT INTO tipos_pendencia (descricao, setor_responsavel, criticidade)
               VALUES (%s,%s,%s) RETURNING *""",
            (descricao, v.texto(data.get("setor_responsavel"), "setor responsavel", 60),
             v.escolha(data.get("criticidade"), "criticidade", CRITICIDADES, padrao="media"))
        )
        return jsonify(novo), 201

    @app.route("/api/tipos-pendencia/<int:tipo_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_tipo_pendencia(tipo_id):
        data = v.corpo_json()
        atualizado = db.execute(
            """UPDATE tipos_pendencia
               SET descricao=%s, setor_responsavel=%s, criticidade=%s, ativo=%s
               WHERE id=%s RETURNING *""",
            (v.texto(data.get("descricao"), "descricao", 150, obrigatorio=True),
             v.texto(data.get("setor_responsavel"), "setor responsavel", 60),
             v.escolha(data.get("criticidade"), "criticidade", CRITICIDADES, padrao="media"),
             v.booleano(data.get("ativo"), "ativo", True), tipo_id)
        )
        if not atualizado:
            return jsonify({"erro": "tipo de pendencia nao encontrado"}), 404
        return jsonify(atualizado)

    @app.route("/api/tipos-pendencia/<int:tipo_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_excluir_tipo_pendencia(tipo_id):
        db.execute("UPDATE tipos_pendencia SET ativo = FALSE WHERE id = %s", (tipo_id,))
        return jsonify({"ok": True})

    @app.route("/api/tipos-pendencia/<int:tipo_id>/ativar", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_ativar_tipo_pendencia(tipo_id):
        db.execute("UPDATE tipos_pendencia SET ativo = TRUE WHERE id = %s", (tipo_id,))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - UNIDADES (consulta ao vivo no sistema hospitalar)
    # -----------------------------------------------------------
    @app.route("/api/unidades", methods=["GET"])
    @login_required
    def api_listar_unidades():
        return jsonify(listar_unidades_integra())

    # -----------------------------------------------------------
    # API - UNIDADES LOCAIS (clinicas cadastradas neste sistema,
    # complementares as do sistema hospitalar - tabela 'unidades')
    # -----------------------------------------------------------
    @app.route("/api/unidades-locais", methods=["GET"])
    @login_required
    def api_listar_unidades_locais():
        return jsonify(db.query("SELECT * FROM unidades WHERE ativo = TRUE ORDER BY nome"))

    @app.route("/api/unidades-locais", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_unidade_local():
        data = v.corpo_json()
        nome = v.texto(data.get("nome"), "nome", 120, obrigatorio=True)
        tipo = v.texto(data.get("tipo"), "tipo", 60)

        ultimo = db.query(
            "SELECT MAX(codigo::integer) AS maximo FROM unidades WHERE codigo ~ '^[0-9]+$'",
            fetchone=True
        )
        proximo_codigo = str(max(ultimo["maximo"] or 2999, 2999) + 1)

        nova = db.execute(
            "INSERT INTO unidades (nome, codigo, tipo) VALUES (%s,%s,%s) RETURNING *",
            (nome, proximo_codigo, tipo)
        )
        return jsonify(nova), 201

    @app.route("/api/unidades-locais/<int:unidade_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_unidade_local(unidade_id):
        data = v.corpo_json()
        nome = v.texto(data.get("nome"), "nome", 120, obrigatorio=True)

        atualizada = db.execute(
            "UPDATE unidades SET nome=%s, tipo=%s WHERE id=%s RETURNING *",
            (nome, v.texto(data.get("tipo"), "tipo", 60), unidade_id)
        )
        if not atualizada:
            return jsonify({"erro": "unidade nao encontrada"}), 404
        return jsonify(atualizada)

    @app.route("/api/unidades-locais/<int:unidade_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_desativar_unidade_local(unidade_id):
        db.execute("UPDATE unidades SET ativo = FALSE WHERE id = %s", (unidade_id,))
        return jsonify({"ok": True})

    @app.route("/api/clinicas/<int:isn_clinica>/tipo", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_tipo_clinica(isn_clinica):
        data = v.corpo_json()
        tipo = v.texto(data.get("tipo"), "tipo", 60)
        if isn_clinica not in UNIDADES_PERMITIDAS:
            return jsonify({"erro": "clinica nao encontrada"}), 404

        atualizado = db.execute(
            """INSERT INTO clinicas_tipo (isn_clinica, tipo, atualizado_em)
               VALUES (%s, %s, NOW())
               ON CONFLICT (isn_clinica) DO UPDATE SET tipo = EXCLUDED.tipo, atualizado_em = NOW()
               RETURNING *""",
            (isn_clinica, tipo)
        )
        return jsonify(atualizado)

    # -----------------------------------------------------------
    # API - PROFISSIONAIS (somente leitura, do sistema hospitalar)
    # -----------------------------------------------------------
    @app.route("/api/profissionais", methods=["GET"])
    @login_required
    def api_listar_profissionais():
        return jsonify(listar_profissionais_integra())

    # -----------------------------------------------------------
    # API - PROCEDIMENTOS SIGTAP (catalogo, CRUD)
    # -----------------------------------------------------------
    @app.route("/api/procedimentos-sigtap", methods=["GET"])
    @login_required
    def api_listar_procedimentos_sigtap():
        busca = v.termo_busca(request.args.get("q"))
        sql = "SELECT * FROM procedimentos_sigtap"
        params = []
        if busca:
            sql += " WHERE codigo ILIKE %s OR descricao ILIKE %s"
            params += [f"%{busca}%", f"%{busca}%"]
        sql += " ORDER BY codigo"
        return jsonify(db.query(sql, params))

    @app.route("/api/procedimentos-sigtap", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_procedimento_sigtap():
        data = v.corpo_json()
        codigo = v.texto(data.get("codigo"), "codigo", 20, obrigatorio=True)
        descricao = v.texto(data.get("descricao"), "descricao", 255, obrigatorio=True)

        try:
            novo = db.execute(
                "INSERT INTO procedimentos_sigtap (codigo, descricao) VALUES (%s,%s) RETURNING *",
                (codigo, descricao)
            )
            return jsonify(novo), 201
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "codigo SIGTAP ja cadastrado"}), 409

    @app.route("/api/procedimentos-sigtap/<int:procedimento_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_procedimento_sigtap(procedimento_id):
        data = v.corpo_json()
        try:
            atualizado = db.execute(
                """UPDATE procedimentos_sigtap SET codigo=%s, descricao=%s, ativo=%s
                   WHERE id=%s RETURNING *""",
                (v.texto(data.get("codigo"), "codigo", 20, obrigatorio=True),
                 v.texto(data.get("descricao"), "descricao", 255, obrigatorio=True),
                 v.booleano(data.get("ativo"), "ativo", True), procedimento_id)
            )
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "codigo SIGTAP ja cadastrado"}), 409
        if not atualizado:
            return jsonify({"erro": "procedimento nao encontrado"}), 404
        return jsonify(atualizado)

    @app.route("/api/procedimentos-sigtap/<int:procedimento_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_excluir_procedimento_sigtap(procedimento_id):
        db.execute("UPDATE procedimentos_sigtap SET ativo = FALSE WHERE id = %s", (procedimento_id,))
        return jsonify({"ok": True})

    @app.route("/api/procedimentos-sigtap/<int:procedimento_id>/ativar", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_ativar_procedimento_sigtap(procedimento_id):
        db.execute("UPDATE procedimentos_sigtap SET ativo = TRUE WHERE id = %s", (procedimento_id,))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - PROCEDIMENTOS DE UM PRONTUARIO (incluir/excluir em Contas Medicas)
    # -----------------------------------------------------------
    @app.route("/api/prontuarios/<int:prontuario_id>/procedimentos", methods=["GET"])
    @login_required
    def api_listar_procedimentos_prontuario(prontuario_id):
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        rows = db.query(
            """SELECT pp.id, pp.quantidade, pp.criado_em,
                      ps.codigo, ps.descricao,
                      u.nome AS usuario_nome
               FROM prontuario_procedimentos pp
               JOIN procedimentos_sigtap ps ON ps.id = pp.procedimento_id
               LEFT JOIN usuarios u ON u.id = pp.usuario_id
               WHERE pp.prontuario_id = %s
               ORDER BY pp.criado_em DESC""",
            (prontuario_id,)
        )
        return jsonify(rows)

    @app.route("/api/prontuarios/<int:prontuario_id>/procedimentos", methods=["POST"])
    @login_required
    def api_incluir_procedimento_prontuario(prontuario_id):
        data = v.corpo_json()
        procedimento_id = v.inteiro(data.get("procedimento_id"), "procedimento_id", obrigatorio=True, minimo=1)
        quantidade = v.inteiro(data.get("quantidade"), "quantidade", minimo=1, maximo=999, padrao=1)
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        if not db.query("SELECT 1 FROM procedimentos_sigtap WHERE id = %s AND ativo = TRUE",
                        (procedimento_id,), fetchone=True):
            return jsonify({"erro": "procedimento nao encontrado"}), 404

        db.execute(
            """INSERT INTO prontuario_procedimentos (prontuario_id, procedimento_id, quantidade, usuario_id)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (prontuario_id, procedimento_id, quantidade, session["usuario_id"])
        )
        return jsonify({"ok": True}), 201

    @app.route("/api/prontuarios/<int:prontuario_id>/procedimentos/<int:item_id>", methods=["DELETE"])
    @login_required
    def api_excluir_procedimento_prontuario(prontuario_id, item_id):
        _, erro = obter_prontuario_autorizado(prontuario_id)
        if erro:
            return erro
        db.execute(
            "DELETE FROM prontuario_procedimentos WHERE id = %s AND prontuario_id = %s",
            (item_id, prontuario_id)
        )
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - USUARIOS (CRUD)
    # -----------------------------------------------------------
    @app.route("/api/usuarios", methods=["GET"])
    @login_required
    @perfil_required("admin")
    def api_listar_usuarios():
        rows = db.query(
            """SELECT u.id, u.nome, u.login, u.email, u.perfil, u.ativo, u.criado_em, u.ultimo_login,
                      u.tela_inicial,
                      COALESCE(array_agg(uu.unidade_id) FILTER (WHERE uu.unidade_id IS NOT NULL), '{}')
                          AS unidade_ids
               FROM usuarios u
               LEFT JOIN usuario_unidades uu ON uu.usuario_id = u.id
               GROUP BY u.id
               ORDER BY u.nome"""
        )
        todos_ids = [i for row in rows for i in row["unidade_ids"]]
        mapa_nomes = mapa_nomes_unidades(todos_ids)
        for row in rows:
            row["unidade_nome"] = ", ".join(
                mapa_nomes.get(i, str(i)) for i in row["unidade_ids"]
            ) or None
        return jsonify(decifrar_campos(rows, "email"))

    def campos_usuario(data):
        """Valida nome/e-mail/perfil/tela inicial/unidades de um usuario."""
        perfil = v.texto(data.get("perfil"), "perfil", 30, padrao="operador")
        if not db.query("SELECT 1 FROM perfis WHERE nome = %s AND ativo = TRUE", (perfil,), fetchone=True):
            raise v.EntradaInvalida("perfil invalido")
        tela_inicial = v.escolha(data.get("tela_inicial"), "tela inicial",
                                 {chave for chave, _ in PAGINAS_SELECIONAVEIS})
        return {
            "nome": v.texto(data.get("nome"), "nome", 150, obrigatorio=True),
            "email": cifrar_campo(v.email(data.get("email"))),
            "perfil": perfil,
            "tela_inicial": tela_inicial,
            "unidade_ids": v.lista_inteiros(data.get("unidade_ids"), "unidades"),
        }

    @app.route("/api/usuarios", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_usuario():
        data = v.corpo_json()
        campos = campos_usuario(data)
        login_novo = v.login(data.get("login"))
        senha_hash = generate_password_hash(v.senha(data.get("senha")))
        try:
            novo = db.execute(
                """INSERT INTO usuarios (nome, login, email, senha_hash, perfil, tela_inicial)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   RETURNING id, nome, login, email, perfil, ativo, tela_inicial""",
                (campos["nome"], login_novo, campos["email"], senha_hash,
                 campos["perfil"], campos["tela_inicial"])
            )
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "ja existe um usuario com esse login"}), 409
        salvar_unidades_usuario(novo["id"], campos["unidade_ids"])
        return jsonify(decifrar_campos(novo, "email")), 201

    @app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_usuario(usuario_id):
        data = v.corpo_json()
        campos = campos_usuario(data)
        ativo = v.booleano(data.get("ativo"), "ativo", True)
        nova_senha = v.senha(data.get("senha"), obrigatoria=False)

        atual = db.query("SELECT perfil, ativo FROM usuarios WHERE id = %s", (usuario_id,), fetchone=True)
        if not atual:
            return jsonify({"erro": "usuario nao encontrado"}), 404
        if usuario_id == session.get("usuario_id") and (not ativo or campos["perfil"] != "admin"):
            return jsonify({"erro": "voce nao pode inativar nem tirar o perfil admin do seu proprio usuario"}), 400

        if nova_senha:
            db.execute("UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                       (generate_password_hash(nova_senha), usuario_id))
        # Senha, perfil ou status mudaram: encerra as sessoes abertas desse usuario.
        encerrar_sessoes = bool(nova_senha) or campos["perfil"] != atual["perfil"] or ativo != atual["ativo"]
        atualizado = db.execute(
            """UPDATE usuarios SET nome=%s, email=%s, perfil=%s, ativo=%s, tela_inicial=%s,
                      sessao_versao = sessao_versao + %s
               WHERE id=%s
               RETURNING id, nome, login, email, perfil, ativo, tela_inicial""",
            (campos["nome"], campos["email"], campos["perfil"], ativo, campos["tela_inicial"],
             1 if encerrar_sessoes and usuario_id != session.get("usuario_id") else 0, usuario_id)
        )
        if usuario_id == session.get("usuario_id") and nova_senha:
            # Trocou a propria senha: as outras sessoes caem, esta continua.
            db.execute("UPDATE usuarios SET sessao_versao = sessao_versao + 1 WHERE id = %s", (usuario_id,))
            session["sessao_versao"] = session.get("sessao_versao", 0) + 1
        salvar_unidades_usuario(usuario_id, campos["unidade_ids"])
        return jsonify(decifrar_campos(atualizado, "email"))

    @app.route("/api/usuarios/<int:usuario_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_excluir_usuario(usuario_id):
        if usuario_id == session.get("usuario_id"):
            return jsonify({"erro": "voce nao pode inativar o seu proprio usuario"}), 400
        db.execute("UPDATE usuarios SET ativo = FALSE, sessao_versao = sessao_versao + 1 WHERE id = %s",
                   (usuario_id,))
        return jsonify({"ok": True})

    @app.route("/api/usuarios/<int:usuario_id>/ativar", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_ativar_usuario(usuario_id):
        db.execute("UPDATE usuarios SET ativo = TRUE WHERE id = %s", (usuario_id,))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - PERFIS (controle de acesso por pagina)
    # -----------------------------------------------------------
    def serializar_perfil(perfil_row):
        paginas = db.query(
            "SELECT pagina FROM perfil_paginas WHERE perfil_id = %s ORDER BY pagina", (perfil_row["id"],)
        )
        return {**perfil_row, "paginas": [p["pagina"] for p in paginas]}

    @app.route("/api/perfis", methods=["GET"])
    @login_required
    @perfil_required("admin")
    def api_listar_perfis():
        linhas = db.query("SELECT * FROM perfis ORDER BY nome")
        return jsonify([serializar_perfil(p) for p in linhas])

    @app.route("/api/perfis", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_perfil():
        data = v.corpo_json()
        nome = (v.texto(data.get("nome"), "nome", 30) or "").lower().replace(" ", "_")
        paginas = v.lista_textos(data.get("paginas"), "paginas", dict(PAGINAS_SELECIONAVEIS))

        if not nome:
            return jsonify({"erro": "nome e obrigatorio"}), 400
        if not re.fullmatch(r"[a-z0-9_]+", nome):
            return jsonify({"erro": "nome deve ter apenas letras sem acento, numeros e _"}), 400
        if nome == "admin":
            return jsonify({"erro": "nome reservado"}), 400

        try:
            novo = db.execute(
                "INSERT INTO perfis (nome) VALUES (%s) RETURNING *", (nome,)
            )
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "ja existe um perfil com esse nome"}), 409

        for pagina in paginas:
            db.execute(
                "INSERT INTO perfil_paginas (perfil_id, pagina) VALUES (%s, %s)", (novo["id"], pagina)
            )
        return jsonify(serializar_perfil(novo)), 201

    @app.route("/api/perfis/<int:perfil_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_perfil(perfil_id):
        atual = db.query("SELECT * FROM perfis WHERE id = %s", (perfil_id,), fetchone=True)
        if not atual:
            return jsonify({"erro": "perfil nao encontrado"}), 404
        if atual["protegido"]:
            return jsonify({"erro": "perfil protegido nao pode ser alterado"}), 400

        data = v.corpo_json()
        ativo = v.booleano(data.get("ativo"), "ativo", atual["ativo"])
        paginas = v.lista_textos(data.get("paginas"), "paginas", dict(PAGINAS_SELECIONAVEIS))

        db.execute("UPDATE perfis SET ativo = %s WHERE id = %s", (ativo, perfil_id))
        db.execute("DELETE FROM perfil_paginas WHERE perfil_id = %s", (perfil_id,))
        for pagina in paginas:
            db.execute(
                "INSERT INTO perfil_paginas (perfil_id, pagina) VALUES (%s, %s)", (perfil_id, pagina)
            )

        atualizado = db.query("SELECT * FROM perfis WHERE id = %s", (perfil_id,), fetchone=True)
        return jsonify(serializar_perfil(atualizado))

    @app.route("/api/perfis/<int:perfil_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_alternar_perfil(perfil_id):
        atual = db.query("SELECT * FROM perfis WHERE id = %s", (perfil_id,), fetchone=True)
        if not atual:
            return jsonify({"erro": "perfil nao encontrado"}), 404
        if atual["protegido"]:
            return jsonify({"erro": "perfil protegido nao pode ser inativado"}), 400

        db.execute("UPDATE perfis SET ativo = %s WHERE id = %s", (not atual["ativo"], perfil_id))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - PAINEL EM TEMPO REAL
    # -----------------------------------------------------------
    @app.route("/api/painel", methods=["GET"])
    @login_required
    def api_painel():
        resumo = db.query("""
            SELECT status_atual, COUNT(*) AS total
            FROM prontuarios
            WHERE status_atual != 'finalizado'
            GROUP BY status_atual
        """)
        resumo_mapa = {r["status_atual"]: r["total"] for r in resumo}

        altas_pendentes = listar_altas_pendentes()
        contadores = {
            "altas": len(altas_pendentes),
            "sop": resumo_mapa.get("sop", 0),
            "contas_medicas": resumo_mapa.get("contas_medicas", 0),
            "pronto_faturamento": resumo_mapa.get("pronto_faturamento", 0),
        }

        agora = agora_local()

        eventos = []

        movimentacoes = db.query("""
            SELECT m.destino, m.data_movimentacao,
                   p.numero_prontuario, p.paciente_nome, p.data_alta
            FROM movimentacoes m
            JOIN prontuarios p ON p.id = m.prontuario_id
            ORDER BY m.data_movimentacao DESC
            LIMIT 20
        """)
        for m in movimentacoes:
            eventos.append({
                "tipo": "movimentacao",
                "numero_prontuario": m["numero_prontuario"],
                "paciente_nome": m["paciente_nome"],
                "destino": m["destino"],
                "destino_label": STATUS_LABEL.get(m["destino"], m["destino"]),
                "data_alta": m["data_alta"],
                "horas_uteis": round(horas_uteis_decorridas(m["data_movimentacao"], agora), 2),
                "timestamp": m["data_movimentacao"],
            })

        for a in altas_pendentes:
            hor_alta = (a["hor_alta"] or "00:00").strip() or "00:00"
            try:
                hora = datetime.strptime(hor_alta, "%H:%M").time()
            except ValueError:
                hora = dtime.min
            alta_datetime = datetime.combine(a["dat_alta"], hora)
            eventos.append({
                "tipo": "alta",
                "numero_prontuario": a["num_prontuario"] or "-",
                "paciente_nome": a["paciente_nome"],
                "destino": None,
                "destino_label": f"Alta: {a['dsc_destino'] or '-'}",
                "dsc_motivo_alta": a["dsc_motivo_alta"],
                "data_alta": a["dat_alta"],
                "horas_uteis": a["horas_uteis_desde_alta"],
                "timestamp": alta_datetime,
            })

        eventos.sort(key=lambda e: e["timestamp"], reverse=True)
        ultimos = eventos[:20]
        for u in ultimos:
            u["data_hora"] = u.pop("timestamp")

        return jsonify({
            "atualizado_em": agora_local().isoformat(),
            "contadores": contadores,
            "ultimo": ultimos[0] if ultimos else None,
            "ultimos": ultimos,
        })

    # -----------------------------------------------------------
    # API - PAINEIS DE MONITORAMENTO (quantidade por status e analises por usuario)
    # -----------------------------------------------------------
    def montar_resumo_status_prontuarios():
        status_rows = db.query("SELECT status_atual, COUNT(*) AS total FROM prontuarios GROUP BY status_atual")
        status_mapa = {r["status_atual"]: r["total"] for r in status_rows}
        return [
            {"status": chave, "label": STATUS_LABEL.get(chave, chave), "total": status_mapa.get(chave, 0)}
            for chave in FLUXO_ORDEM
        ]

    def buscar_usuarios_analise(etapa):
        return db.query("""
            SELECT u.nome,
                   COUNT(*) FILTER (WHERE ap.data_fim IS NULL) AS em_analise,
                   COUNT(*) FILTER (WHERE ap.data_fim IS NOT NULL) AS analisados
            FROM analises_prontuario ap
            JOIN usuarios u ON u.id = ap.usuario_id
            WHERE ap.etapa = %s
            GROUP BY u.nome
            ORDER BY u.nome
        """, (etapa,))

    @app.route("/api/painel-monitoramento-sop", methods=["GET"])
    @login_required
    def api_painel_monitoramento_sop():
        return jsonify({
            "por_status": montar_resumo_status_prontuarios(),
            "usuarios": buscar_usuarios_analise("sop"),
        })

    @app.route("/api/painel-monitoramento-contas-medicas", methods=["GET"])
    @login_required
    def api_painel_monitoramento_contas_medicas():
        return jsonify({
            "por_status": montar_resumo_status_prontuarios(),
            "usuarios": buscar_usuarios_analise("contas_medicas"),
        })

    # -----------------------------------------------------------
    # Contexto global para os templates
    # -----------------------------------------------------------
    @app.context_processor
    def inject_globals():
        if session.get("perfil") == "admin":
            paginas_permitidas = [chave for chave, _ in PAGINAS_SELECIONAVEIS]
        else:
            paginas_permitidas = session.get("paginas_permitidas") or []
        return {
            "usuario_nome": session.get("nome"),
            "usuario_perfil": session.get("perfil"),
            "paginas_permitidas": paginas_permitidas,
            "status_label": STATUS_LABEL,
            "ambiente_homolog": os.environ.get("AMBIENTE", "").strip().lower() == "homolog",
            "url_homologacao": _url_homologacao(),
        }


app = create_app()

if __name__ == "__main__":
    # O modo debug do Flask abre um console Python no navegador quando ocorre
    # um erro: so liga com FLASK_DEBUG=1 e, nesse caso, apenas nesta maquina.
    modo_debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true")
    app.run(debug=modo_debug, host="127.0.0.1" if modo_debug else "0.0.0.0", port=5500)
