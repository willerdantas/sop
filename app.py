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
from datetime import datetime, date, time as dtime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import psycopg2
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash

import db
from config import Config

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
ALTAS_DATA_INICIO = "2026-10-01"


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

# Unidades (isn_clinica em integra_local.t_clinica) exibidas na pagina de Unidades.
UNIDADES_PERMITIDAS = (
    15, 17, 18, 20, 21, 22, 23, 24, 34, 35,
    36, 37, 38, 42, 44, 46, 50, 52, 53, 54,
)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_pool(app)
    db.init_pool_integra(app)
    db.register_teardown(app)

    with app.app_context():
        _seed_admin()

    register_routes(app)
    return app


def _seed_admin():
    """Cria um usuario admin padrao se a tabela usuarios estiver vazia."""
    try:
        existentes = db.query("SELECT COUNT(*) AS total FROM usuarios", fetchone=True)
        if existentes and existentes["total"] == 0:
            senha_hash = generate_password_hash(Config.ADMIN_DEFAULT_SENHA)
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
    """Unidades (clinicas) ativas, consultadas ao vivo em integra_local.t_clinica."""
    rows = db.query_integra(
        """SELECT isn_clinica, dsc_clinica
           FROM integra_local.t_clinica
           WHERE flg_ativo = 'S'
           ORDER BY dsc_clinica"""
    )
    return [{"id": int(r["isn_clinica"]), "nome": r["dsc_clinica"]} for r in rows]


def listar_unidades_locais_opcoes():
    """Unidades cadastradas localmente (tabela 'unidades'), com id negativo
    para nao colidir com isn_clinica do sistema hospitalar."""
    rows = db.query("SELECT id, nome FROM unidades WHERE ativo = TRUE ORDER BY nome")
    return [{"id": -r["id"], "nome": r["nome"]} for r in rows]


def mapa_nomes_unidades(ids):
    """Recebe uma lista de unidade_id e devolve {id: nome}. IDs positivos sao
    isn_clinica do sistema hospitalar (integra_local.t_clinica); IDs negativos
    sao unidades cadastradas localmente (tabela 'unidades', id = -unidade_id)."""
    ids_validos = {int(i) for i in ids if i is not None}
    if not ids_validos:
        return {}

    ids_integra = [i for i in ids_validos if i > 0]
    ids_locais = [-i for i in ids_validos if i < 0]

    mapa = {}
    if ids_integra:
        rows = db.query_integra(
            "SELECT isn_clinica, dsc_clinica FROM integra_local.t_clinica WHERE isn_clinica = ANY(%s)",
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


def historico_internacao(integra_isn_internacao_leito):
    """Dado o isn_internacao_leito gravado no prontuario (origem: Altas), devolve
    (isn_internacao, historico de clinicas/enfermarias/leitos daquela internacao)."""
    if not integra_isn_internacao_leito:
        return None, []

    referencia = db.query_integra(
        "SELECT isn_internacao FROM integra_local.t_internacao_leito WHERE isn_internacao_leito = %s",
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
           FROM integra_local.t_internacao_leito il
           LEFT JOIN integra_local.t_clinica c ON c.isn_clinica = il.isn_clinica
           LEFT JOIN integra_local.t_enfermaria e ON e.isn_enfermaria = il.isn_enfermaria
           LEFT JOIN integra_local.t_leito l ON l.isn_leito = il.isn_leito
           WHERE il.isn_internacao = %s
           ORDER BY il.dat_alta ASC, il.isn_internacao_leito ASC""",
        (isn_internacao,)
    )
    return isn_internacao, registros


def listar_exames_internacao(isn_internacao):
    """Exames solicitados durante a internacao: t_internacao join t_exame_solic
    (por isn_internacao) join t_exame (por isn_exame) para o nome do exame."""
    if not isn_internacao:
        return []
    return db.query_integra(
        """SELECT ex.dsc_exame,
                  es.dat_solicitacao, es.dat_agendamento,
                  es.dat_realizacao, es.dat_cancelamento
           FROM integra_local.t_internacao i
           JOIN integra_local.t_exame_solic es ON es.isn_internacao = i.isn_internacao
           LEFT JOIN integra_local.t_exame ex ON ex.isn_exame = es.isn_exame
           WHERE i.isn_internacao = %s
           ORDER BY es.dat_solicitacao DESC""",
        (isn_internacao,)
    )


def resumir_exames_por_nome(exames):
    """Agrupa a lista de exames por nome, contando quantos houve de cada um."""
    contagem = {}
    for ex in exames:
        nome = ex["dsc_exame"] or "Sem nome"
        contagem[nome] = contagem.get(nome, 0) + 1
    return sorted(
        [{"nome": nome, "quantidade": qtd} for nome, qtd in contagem.items()],
        key=lambda r: r["nome"]
    )


def listar_altas_pendentes():
    """Altas (destino 1/3/4, internacao real) ainda nao registradas no fluxo,
    com as horas uteis decorridas desde a alta."""
    altas = db.query_integra(
        """SELECT * FROM (
               SELECT DISTINCT ON (il.isn_internacao)
                      il.isn_internacao_leito, il.isn_internacao, il.isn_clinica,
                      il.dat_internacao, il.dat_alta, il.hor_alta,
                      il.isn_destino, d.dsc_destino,
                      c.dsc_clinica AS unidade_nome,
                      p.num_prontuario, p.dsc_nome AS paciente_nome
               FROM integra_local.t_internacao_leito il
               JOIN integra_local.t_internacao i ON i.isn_internacao = il.isn_internacao
               JOIN integra_local.t_paciente p ON p.isn_paciente = i.isn_paciente
               LEFT JOIN integra_local.t_clinica c ON c.isn_clinica = il.isn_clinica
               LEFT JOIN integra_local.t_destino d ON d.isn_destino = il.isn_destino
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
            "dat_alta": a["dat_alta"],
            "hor_alta": a["hor_alta"],
            "isn_destino": int(a["isn_destino"]) if a["isn_destino"] is not None else None,
            "dsc_destino": a["dsc_destino"],
            "num_prontuario": (a["num_prontuario"] or "").strip(),
            "paciente_nome": a["paciente_nome"],
            "horas_uteis_desde_alta": round(horas_uteis, 2),
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
    "analise_prontuario": ("sop",),
    "analise_unidade_prontuario": ("unidade",),
    "analise_c_medicas_prontuario": ("contas_medicas",),
    "api_listar_prontuarios": ("sop", "unidade", "contas_medicas"),
    "api_obter_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_criar_prontuario": ("sop",),
    "api_mover_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_confirmar_recebimento_prontuario": ("contas_medicas",),
    "api_historico_prontuario": ("sop", "unidade", "contas_medicas"),
    "api_listar_altas": ("sop",),
    "api_registrar_alta": ("sop",),
    "api_listar_pendencias": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_criar_pendencia": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_resolver_pendencia": ("sop", "unidade", "pendencias", "contas_medicas"),
    "api_confirmar_pendencia": ("sop", "pendencias", "contas_medicas"),
    "api_devolver_pendencia": ("sop", "pendencias", "contas_medicas"),
    "api_painel": ("painel",),
    "api_listar_profissionais": ("profissionais",),
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


def primeira_pagina_permitida():
    """Primeira pagina (na ordem de PAGINAS_SELECIONAVEIS) que o usuario logado
    pode acessar, usada como destino seguro apos login ou em bloqueios."""
    paginas_do_usuario = session.get("paginas_permitidas") or []
    for chave, _ in PAGINAS_SELECIONAVEIS:
        if chave in paginas_do_usuario:
            return chave
    return None


def prontuario_da_unidade_do_usuario(prontuario_row):
    """True se o perfil nao for operador, ou se o prontuario pertencer a
    unidade a qual o operador esta atrelado."""
    if session.get("perfil") != "operador":
        return True
    return bool(prontuario_row) and prontuario_row.get("unidade_id") == session.get("unidade_id")


def register_routes(app):

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

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            login_usuario = request.form.get("login", "").strip()
            senha = request.form.get("senha", "")

            usuario = db.query(
                "SELECT * FROM usuarios WHERE login = %s AND ativo = TRUE",
                (login_usuario,), fetchone=True
            )

            if usuario and check_password_hash(usuario["senha_hash"], senha):
                session.clear()
                session["usuario_id"] = usuario["id"]
                session["nome"] = usuario["nome"]
                session["perfil"] = usuario["perfil"]
                session["unidade_id"] = usuario["unidade_id"]
                session["paginas_permitidas"] = (
                    [] if usuario["perfil"] == "admin" else paginas_do_perfil(usuario["perfil"])
                )
                db.execute(
                    "UPDATE usuarios SET ultimo_login = NOW() WHERE id = %s",
                    (usuario["id"],)
                )
                if usuario["perfil"] == "admin":
                    destino_padrao = url_for("dashboard")
                else:
                    destino_padrao = url_for(primeira_pagina_permitida() or "dashboard")
                destino = request.args.get("next") or destino_padrao
                return redirect(destino)

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
        unidades = listar_unidades_integra()
        return render_template("sop.html", unidades=unidades, active_page="sop")

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
            "SELECT COUNT(*) AS total FROM integra_local.t_clinica WHERE isn_clinica = ANY(%s)",
            (list(UNIDADES_PERMITIDAS),), fetchone=True
        )["total"]
        total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
        pagina = min(pagina, total_paginas)

        unidades = db.query_integra(
            """SELECT isn_clinica, dsc_clinica
               FROM integra_local.t_clinica
               WHERE isn_clinica = ANY(%s)
               ORDER BY isn_clinica ASC
               LIMIT %s OFFSET %s""",
            (list(UNIDADES_PERMITIDAS), POR_PAGINA, (pagina - 1) * POR_PAGINA)
        )
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
        unidades = listar_unidades_integra()
        perfis = db.query("SELECT nome FROM perfis WHERE ativo = TRUE ORDER BY nome")
        return render_template("usuarios.html", unidades=unidades, perfis=perfis, active_page="usuarios")

    @app.route("/perfis")
    @login_required
    @perfil_required("admin")
    def perfis():
        return render_template("perfis.html", paginas_disponiveis=PAGINAS_SELECIONAVEIS, active_page="perfis")

    @app.route("/pendencias")
    @login_required
    def pendencias():
        tipos = db.query("SELECT id, descricao, criticidade FROM tipos_pendencia WHERE ativo = TRUE ORDER BY descricao")
        unidades = listar_unidades_integra() + listar_unidades_locais_opcoes()
        profissionais = db.query("SELECT nome FROM profissionais WHERE ativo = TRUE ORDER BY nome")
        return render_template(
            "pendencias.html", tipos=tipos, unidades=unidades, profissionais=profissionais,
            active_page="pendencias"
        )

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
        resumo_exames = resumir_exames_por_nome(exames)

        if historico_leitos:
            unidades_pendencia = []
            vistas = set()
            for h in historico_leitos:
                if h["isn_clinica"] is not None and h["isn_clinica"] not in vistas:
                    vistas.add(h["isn_clinica"])
                    unidades_pendencia.append({"id": int(h["isn_clinica"]), "nome": h["dsc_clinica"]})
        else:
            unidades_pendencia = listar_unidades_integra()
        unidades_pendencia += listar_unidades_locais_opcoes()

        min_data_ocorrencia = None
        max_data_ocorrencia = None
        if historico_leitos:
            min_data_ocorrencia = min(h["dat_internacao"] for h in historico_leitos if h["dat_internacao"])
            max_data_ocorrencia = max((h["dat_alta"] or date.today()) for h in historico_leitos)

        tipos = db.query("SELECT id, descricao, criticidade FROM tipos_pendencia WHERE ativo = TRUE ORDER BY descricao")
        profissionais = db.query("SELECT nome FROM profissionais WHERE ativo = TRUE ORDER BY nome")
        return dict(
            prontuario=prontuario, tipos=tipos, profissionais=profissionais,
            isn_internacao=isn_internacao, historico_leitos=historico_leitos,
            exames=exames, resumo_exames=resumo_exames,
            unidades_pendencia=unidades_pendencia,
            min_data_ocorrencia=min_data_ocorrencia, max_data_ocorrencia=max_data_ocorrencia,
        )

    @app.route("/analise/<int:prontuario_id>")
    @login_required
    def analise_prontuario(prontuario_id):
        contexto = montar_contexto_analise(prontuario_id, "sop")
        if contexto is None:
            return redirect(url_for("sop"))
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
        return render_template("analise_c_medicas.html", active_page="contas_medicas", **contexto)

    @app.route("/painel")
    @login_required
    def painel():
        return render_template("painel.html", active_page="painel")

    @app.route("/profissionais")
    @login_required
    def profissionais():
        return render_template("profissionais.html", active_page="profissionais")

    # -----------------------------------------------------------
    # API - PRONTUARIOS / FLUXO
    # -----------------------------------------------------------
    @app.route("/api/prontuarios", methods=["GET"])
    @login_required
    def api_listar_prontuarios():
        status = request.args.get("status")
        busca = request.args.get("q")
        numero = request.args.get("numero")
        nome = request.args.get("nome")
        data_inicio = request.args.get("data_inicio")
        data_fim = request.args.get("data_fim")

        sql = """
            SELECT p.*,
                (SELECT COUNT(*) FROM pendencias pe
                    WHERE pe.prontuario_id = p.id AND pe.status != 'confirmada') AS pendencias_abertas,
                (SELECT MAX(m.data_movimentacao) FROM movimentacoes m
                    WHERE m.prontuario_id = p.id AND m.destino = 'sop') AS entrou_sop_em
            FROM prontuarios p
            WHERE 1=1
        """
        params = []
        if status:
            sql += " AND p.status_atual = %s"
            params.append(status)
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
        if session.get("perfil") == "operador":
            sql += " AND p.unidade_id = %s"
            params.append(session.get("unidade_id"))
        sql += " ORDER BY p.atualizado_em DESC LIMIT 300"

        rows = db.query(sql, params)
        anexar_unidade_nome(rows)

        agora = agora_local()
        for row in rows:
            if row["status_atual"] == "sop" and row["entrou_sop_em"]:
                row["horas_uteis_no_sop"] = round(horas_uteis_decorridas(row["entrou_sop_em"], agora), 2)
            else:
                row["horas_uteis_no_sop"] = None

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

    @app.route("/api/prontuarios", methods=["POST"])
    @login_required
    def api_criar_prontuario():
        data = request.get_json(force=True)
        numero = data.get("numero_prontuario", "").strip()
        paciente = data.get("paciente_nome", "").strip()
        unidade_id = data.get("unidade_id")

        if not numero or not paciente or not unidade_id:
            return jsonify({"erro": "numero_prontuario, paciente_nome e unidade_id sao obrigatorios"}), 400

        try:
            novo = db.execute(
                """INSERT INTO prontuarios
                    (numero_prontuario, paciente_nome, paciente_matricula,
                     unidade_id, data_internacao, data_alta, prioridade,
                     localizacao_fisica, status_atual)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'unidade')
                   RETURNING *""",
                (
                    numero, paciente, data.get("paciente_matricula"),
                    unidade_id, data.get("data_internacao"), data.get("data_alta"),
                    data.get("prioridade", "normal"), data.get("localizacao_fisica"),
                )
            )
            db.execute(
                """INSERT INTO movimentacoes (prontuario_id, origem, destino, usuario_id, observacao)
                   VALUES (%s, 'cadastro', 'unidade', %s, 'Cadastro inicial do prontuario')""",
                (novo["id"], session["usuario_id"])
            )
            return jsonify(novo), 201
        except psycopg2.errors.UniqueViolation:
            db.get_conn().rollback()
            return jsonify({"erro": "numero de prontuario ja cadastrado"}), 409

    @app.route("/api/prontuarios/<int:prontuario_id>/mover", methods=["POST"])
    @login_required
    def api_mover_prontuario(prontuario_id):
        data = request.get_json(force=True)
        destino = data.get("destino")
        observacao = data.get("observacao", "")

        if destino not in FLUXO_ORDEM:
            return jsonify({"erro": "status de destino invalido"}), 400

        atual = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        if not atual:
            return jsonify({"erro": "prontuario nao encontrado"}), 404
        if not prontuario_da_unidade_do_usuario(atual):
            return jsonify({"erro": "sem permissao para mover este prontuario"}), 403
        if session.get("perfil") == "operador" and destino != "sop":
            return jsonify({"erro": "perfil operador so pode enviar o prontuario para o SOP"}), 403

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

        if destino == "contas_medicas":
            # Toda nova chegada em contas_medicas exige nova confirmacao de entrega.
            db.execute(
                "UPDATE prontuarios SET status_atual = %s, recebido_contas_medicas_em = NULL WHERE id = %s",
                (destino, prontuario_id)
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
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/confirmar-recebimento", methods=["POST"])
    @login_required
    def api_confirmar_recebimento_prontuario(prontuario_id):
        atual = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        if not atual:
            return jsonify({"erro": "prontuario nao encontrado"}), 404
        if atual["status_atual"] != "contas_medicas":
            return jsonify({"erro": "prontuario nao esta aguardando recebimento em contas medicas"}), 400
        if atual["recebido_contas_medicas_em"]:
            return jsonify({"erro": "entrega deste prontuario ja foi confirmada"}), 409

        db.execute(
            "UPDATE prontuarios SET recebido_contas_medicas_em = NOW() WHERE id = %s",
            (prontuario_id,)
        )
        atualizado = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        return jsonify(atualizado)

    @app.route("/api/prontuarios/<int:prontuario_id>/historico", methods=["GET"])
    @login_required
    def api_historico_prontuario(prontuario_id):
        prontuario_row = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        if not prontuario_da_unidade_do_usuario(prontuario_row):
            return jsonify({"erro": "sem permissao para ver este prontuario"}), 403

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

        pendentes = listar_altas_pendentes()
        total = len(pendentes)
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
                      il.dat_alta, d.dsc_destino,
                      c.dsc_clinica AS unidade_nome,
                      p.num_prontuario, p.dsc_nome AS paciente_nome
               FROM integra_local.t_internacao_leito il
               JOIN integra_local.t_internacao i ON i.isn_internacao = il.isn_internacao
               JOIN integra_local.t_paciente p ON p.isn_paciente = i.isn_paciente
               LEFT JOIN integra_local.t_clinica c ON c.isn_clinica = il.isn_clinica
               LEFT JOIN integra_local.t_destino d ON d.isn_destino = il.isn_destino
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

        data = request.get_json(force=True)

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
                    data.get("prioridade", "normal"), data.get("localizacao_fisica"),
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

    # -----------------------------------------------------------
    # API - PENDENCIAS
    # -----------------------------------------------------------
    @app.route("/api/pendencias", methods=["GET"])
    @login_required
    def api_listar_pendencias():
        status = request.args.get("status")
        prontuario_id = request.args.get("prontuario_id")
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
            # Pendencias cuja "Unidade da Ocorrencia" e a unidade do usuario logado,
            # independente de onde o prontuario esteja agora no fluxo.
            sql += " AND pe.unidade_id = %s"
            params.append(session.get("unidade_id"))
        elif session.get("perfil") == "operador":
            sql += " AND p.unidade_id = %s"
            params.append(session.get("unidade_id"))
        sql += " ORDER BY pe.data_abertura DESC LIMIT 300"
        rows = db.query(sql, params)
        anexar_unidade_nome(rows)

        agora = agora_local()
        for row in rows:
            row["horas_uteis_desde_abertura"] = round(horas_uteis_decorridas(row["data_abertura"], agora), 2)

        return jsonify(rows)

    @app.route("/api/pendencias", methods=["POST"])
    @login_required
    def api_criar_pendencia():
        data = request.get_json(force=True)
        prontuario_id = data.get("prontuario_id")
        descricao = data.get("descricao", "").strip()
        tipo_pendencia_id = data.get("tipo_pendencia_id")
        profissional = (data.get("profissional") or "").strip() or None
        data_ocorrencia = data.get("data_ocorrencia") or None
        unidade_id = data.get("unidade_id") or None

        if not prontuario_id or not descricao:
            return jsonify({"erro": "prontuario_id e descricao sao obrigatorios"}), 400
        if not profissional or not unidade_id or not data_ocorrencia:
            return jsonify({"erro": "profissional, unidade_id e data_ocorrencia sao obrigatorios"}), 400

        prontuario_row = db.query("SELECT * FROM prontuarios WHERE id = %s", (prontuario_id,), fetchone=True)
        if not prontuario_row:
            return jsonify({"erro": "prontuario nao encontrado"}), 404
        if not prontuario_da_unidade_do_usuario(prontuario_row):
            return jsonify({"erro": "sem permissao para registrar pendencia neste prontuario"}), 403

        erro_historico = validar_pendencia_contra_historico(prontuario_row, unidade_id, data_ocorrencia)
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
        if session.get("perfil") == "operador" and pendencia["unidade_id"] != session.get("unidade_id"):
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
        return jsonify(db.query("SELECT * FROM tipos_pendencia WHERE ativo = TRUE ORDER BY descricao"))

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
        data = request.get_json(force=True)
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"erro": "nome e obrigatorio"}), 400

        ultimo = db.query(
            "SELECT MAX(codigo::integer) AS maximo FROM unidades WHERE codigo ~ '^[0-9]+$'",
            fetchone=True
        )
        proximo_codigo = str(max(ultimo["maximo"] or 2999, 2999) + 1)

        nova = db.execute(
            "INSERT INTO unidades (nome, codigo, tipo) VALUES (%s,%s,%s) RETURNING *",
            (nome, proximo_codigo, data.get("tipo"))
        )
        return jsonify(nova), 201

    @app.route("/api/unidades-locais/<int:unidade_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_desativar_unidade_local(unidade_id):
        db.execute("UPDATE unidades SET ativo = FALSE WHERE id = %s", (unidade_id,))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - PROFISSIONAIS (CRUD)
    # -----------------------------------------------------------
    @app.route("/api/profissionais", methods=["GET"])
    @login_required
    def api_listar_profissionais():
        return jsonify(db.query("SELECT * FROM profissionais ORDER BY nome"))

    @app.route("/api/profissionais", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_profissional():
        data = request.get_json(force=True)
        nome = data.get("nome", "").strip()
        categoria = data.get("categoria", "").strip()

        if not nome or not categoria:
            return jsonify({"erro": "nome e categoria sao obrigatorios"}), 400

        novo = db.execute(
            """INSERT INTO profissionais
                (nome, categoria, conselho, numero_conselho, uf_conselho, telefone, email)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (nome, categoria, data.get("conselho"), data.get("numero_conselho"),
             data.get("uf_conselho"), data.get("telefone"), data.get("email"))
        )
        return jsonify(novo), 201

    @app.route("/api/profissionais/<int:profissional_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_profissional(profissional_id):
        data = request.get_json(force=True)
        atualizado = db.execute(
            """UPDATE profissionais
               SET nome=%s, categoria=%s, conselho=%s, numero_conselho=%s,
                   uf_conselho=%s, telefone=%s, email=%s, ativo=%s
               WHERE id=%s RETURNING *""",
            (data.get("nome"), data.get("categoria"), data.get("conselho"),
             data.get("numero_conselho"), data.get("uf_conselho"), data.get("telefone"),
             data.get("email"), data.get("ativo", True), profissional_id)
        )
        return jsonify(atualizado)

    @app.route("/api/profissionais/<int:profissional_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_excluir_profissional(profissional_id):
        db.execute("UPDATE profissionais SET ativo = FALSE WHERE id = %s", (profissional_id,))
        return jsonify({"ok": True})

    # -----------------------------------------------------------
    # API - USUARIOS (CRUD)
    # -----------------------------------------------------------
    @app.route("/api/usuarios", methods=["GET"])
    @login_required
    @perfil_required("admin")
    def api_listar_usuarios():
        rows = db.query(
            """SELECT id, nome, login, email, perfil, unidade_id, ativo, criado_em, ultimo_login
               FROM usuarios ORDER BY nome"""
        )
        return jsonify(rows)

    @app.route("/api/usuarios", methods=["POST"])
    @login_required
    @perfil_required("admin")
    def api_criar_usuario():
        data = request.get_json(force=True)
        nome = data.get("nome", "").strip()
        login_novo = data.get("login", "").strip()
        senha = data.get("senha", "")
        perfil = data.get("perfil", "operador")

        if not nome or not login_novo or not senha:
            return jsonify({"erro": "nome, login e senha sao obrigatorios"}), 400

        senha_hash = generate_password_hash(senha)
        novo = db.execute(
            """INSERT INTO usuarios (nome, login, email, senha_hash, perfil, unidade_id)
               VALUES (%s,%s,%s,%s,%s,%s)
               RETURNING id, nome, login, email, perfil, unidade_id, ativo""",
            (nome, login_novo, data.get("email"), senha_hash, perfil, data.get("unidade_id"))
        )
        return jsonify(novo), 201

    @app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
    @login_required
    @perfil_required("admin")
    def api_editar_usuario(usuario_id):
        data = request.get_json(force=True)
        if data.get("senha"):
            senha_hash = generate_password_hash(data["senha"])
            db.execute("UPDATE usuarios SET senha_hash = %s WHERE id = %s", (senha_hash, usuario_id))

        atualizado = db.execute(
            """UPDATE usuarios SET nome=%s, email=%s, perfil=%s, unidade_id=%s, ativo=%s
               WHERE id=%s
               RETURNING id, nome, login, email, perfil, unidade_id, ativo""",
            (data.get("nome"), data.get("email"), data.get("perfil"),
             data.get("unidade_id"), data.get("ativo", True), usuario_id)
        )
        return jsonify(atualizado)

    @app.route("/api/usuarios/<int:usuario_id>", methods=["DELETE"])
    @login_required
    @perfil_required("admin")
    def api_excluir_usuario(usuario_id):
        db.execute("UPDATE usuarios SET ativo = FALSE WHERE id = %s", (usuario_id,))
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
        data = request.get_json(force=True)
        nome = (data.get("nome") or "").strip().lower().replace(" ", "_")
        paginas = [p for p in (data.get("paginas") or []) if p in dict(PAGINAS_SELECIONAVEIS)]

        if not nome:
            return jsonify({"erro": "nome e obrigatorio"}), 400
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

        data = request.get_json(force=True)
        ativo = data.get("ativo", atual["ativo"])
        paginas = [p for p in (data.get("paginas") or []) if p in dict(PAGINAS_SELECIONAVEIS)]

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
        }


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5500)
