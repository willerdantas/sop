"""
Modo de configuracao inicial (banco de dados indisponivel)
----------------------------------------------------------
Se na inicializacao nao for possivel conectar aos bancos (sop e ISIVITA),
a app sobe mesmo assim, em "modo de configuracao": todas as paginas
redirecionam para /configuracao, onde:

1. Na primeira vez, um perfil administrador e aberto SEM senha e o
   usuario e obrigado a criar uma. Como nao ha banco, o hash da senha
   fica no .env (SETUP_ADMIN_SENHA_HASH).
2. Nas vezes seguintes, essa senha e pedida para entrar.
3. Na pagina de configuracao do banco, as conexoes sao testadas e, se
   funcionarem, gravadas CIFRADAS no .env (DATABASE_URL e
   INTEGRA_DATABASE_URL). A app passa a usar o banco na hora, sem reiniciar.

Com varios processos (ex: gunicorn -w 4), cada processo percebe a mudanca
no .env na proxima requisicao e reconecta sozinho.
"""
import os
from urllib.parse import quote, unquote, urlparse

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key
from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
from config import SCHEMA_VALIDO, ler_integra_schema, ler_urls_banco
from crypto_utils import cifrar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
SCHEMA_PATH = os.path.join(BASE_DIR, "sql", "schema.sql")
CHAVE_HASH_SENHA = "SETUP_ADMIN_SENHA_HASH"
CHAVES_MONITORADAS = (
    "DATABASE_URL", "INTEGRA_DATABASE_URL", "INTEGRA_SCHEMA", "ENCRYPTION_KEY",
    CHAVE_HASH_SENHA,
)
SENHA_TAMANHO_MINIMO = 8
CAMPOS_CONEXAO = ("host", "porta", "banco", "usuario", "senha")

bp = Blueprint("configuracao", __name__, url_prefix="/configuracao")

_estado = {
    "ativo": False,          # True = banco indisponivel, app em modo de configuracao
    "erro": None,            # mensagem do ultimo erro de conexao
    "urls_tentadas": None,   # URLs usadas na ultima tentativa de conexao
    "env_snapshot": {},      # valores das CHAVES_MONITORADAS no .env
    "ao_conectar": None,     # callback executado quando o banco fica disponivel
    "app": None,
}


# ---------------------------------------------------------------
# Inicializacao / estado
# ---------------------------------------------------------------
def init_app(app, ao_conectar=None):
    """Registra o modo de configuracao e tenta conectar aos bancos.
    Deve ser chamado ANTES de registrar as demais rotas/before_request."""
    _estado["app"] = app
    _estado["ao_conectar"] = ao_conectar
    _estado["env_snapshot"] = _ler_env_monitorado()
    app.register_blueprint(bp)
    app.before_request(_redirecionar_para_configuracao)
    _conectar_bancos()


def _conectar_bancos():
    """Tenta abrir os pools com as URLs atuais. Liga/desliga o modo de
    configuracao conforme o resultado. Devolve True se conectou."""
    urls = ler_urls_banco()
    schema = ler_integra_schema()
    _estado["urls_tentadas"] = (urls, schema)
    # Cria o banco principal e/ou as tabelas, se faltarem. Se falhar, o
    # substituir_pools abaixo reporta o erro de conexao.
    _, acoes = db.preparar_banco(urls[0], SCHEMA_PATH)
    if acoes:
        print(f"[info] banco principal: {', '.join(acoes)}")
    try:
        db.substituir_pools(*urls, schema)
    except db.BancoIndisponivel as exc:
        # So entra em modo de configuracao se nao houver conexao funcionando
        # (numa reconfiguracao pelo admin, os pools anteriores continuam valendo).
        _estado.update(ativo=not db.pools_ativos(), erro=str(exc))
        print(f"[aviso] banco indisponivel - app em modo de configuracao: {exc}")
        return False

    _estado.update(ativo=False, erro=None)
    app = _estado["app"]
    app.config["DATABASE_URL"], app.config["INTEGRA_DATABASE_URL"] = urls
    app.config["INTEGRA_SCHEMA"] = schema
    if _estado["ao_conectar"]:
        with app.app_context():
            _estado["ao_conectar"]()
    return True


def _ler_env_monitorado():
    if not os.path.isfile(ENV_PATH):
        return {}
    valores = dotenv_values(ENV_PATH)
    return {chave: valores.get(chave) for chave in CHAVES_MONITORADAS}


def _sincronizar_com_env():
    """Se o .env mudou (por outro processo ou editado a mao), aplica os
    novos valores e tenta conectar de novo caso as URLs tenham mudado."""
    atual = _ler_env_monitorado()
    if atual == _estado["env_snapshot"]:
        return
    _estado["env_snapshot"] = atual
    for chave, valor in atual.items():
        if valor is not None:
            os.environ[chave] = valor
    if (ler_urls_banco(), ler_integra_schema()) != _estado["urls_tentadas"]:
        _conectar_bancos()


def _gravar_env(valores, entre_aspas=()):
    """Grava chaves no .env (criando o arquivo se preciso) e no ambiente."""
    if not os.path.isfile(ENV_PATH):
        open(ENV_PATH, "a", encoding="utf-8").close()
    for chave, valor in valores.items():
        # Aspas simples impedem que "$" do hash seja interpretado como
        # variavel pelo docker compose (env_file).
        modo = "always" if chave in entre_aspas else "never"
        set_key(ENV_PATH, chave, valor, quote_mode=modo)
        os.environ[chave] = valor
    _estado["env_snapshot"] = _ler_env_monitorado()


def _hash_senha_admin():
    return os.environ.get(CHAVE_HASH_SENHA) or None


# ---------------------------------------------------------------
# Bloqueio das demais paginas enquanto o banco nao estiver configurado
# ---------------------------------------------------------------
def _redirecionar_para_configuracao():
    if not _estado["ativo"]:
        return None
    _sincronizar_com_env()
    if not _estado["ativo"]:
        return None  # outro processo configurou o banco: segue normal

    endpoint = request.endpoint or ""
    if endpoint == "static" or endpoint.startswith(f"{bp.name}."):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"erro": "banco de dados nao configurado"}), 503
    return redirect(url_for("configuracao.inicio"))


def _sessao_admin_configuracao():
    return session.get("setup_admin") is True


# ---------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------
@bp.route("/")
def inicio():
    if not _estado["ativo"]:
        return redirect(url_for("index"))
    if _hash_senha_admin() is None:
        return redirect(url_for("configuracao.criar_senha"))
    if _sessao_admin_configuracao():
        return redirect(url_for("configuracao.banco"))
    return redirect(url_for("configuracao.entrar"))


@bp.route("/criar-senha", methods=["GET", "POST"])
def criar_senha():
    """Perfil admin aberto sem senha: obriga a criacao de uma."""
    if not _estado["ativo"] or _hash_senha_admin() is not None:
        return redirect(url_for("configuracao.inicio"))

    if request.method == "POST":
        senha = request.form.get("senha", "")
        confirmacao = request.form.get("confirmacao", "")
        if len(senha) < SENHA_TAMANHO_MINIMO:
            flash(f"A senha deve ter pelo menos {SENHA_TAMANHO_MINIMO} caracteres.", "erro")
        elif senha != confirmacao:
            flash("As senhas não conferem.", "erro")
        else:
            _gravar_env(
                {CHAVE_HASH_SENHA: generate_password_hash(senha)},
                entre_aspas=(CHAVE_HASH_SENHA,),
            )
            session.clear()
            session["setup_admin"] = True
            flash("Senha do administrador criada. Agora configure o banco de dados.", "sucesso")
            return redirect(url_for("configuracao.banco"))

    return render_template("configuracao.html", etapa="criar_senha",
                           senha_minima=SENHA_TAMANHO_MINIMO)


@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if not _estado["ativo"] or _hash_senha_admin() is None:
        return redirect(url_for("configuracao.inicio"))

    if request.method == "POST":
        if check_password_hash(_hash_senha_admin(), request.form.get("senha", "")):
            session.clear()
            session["setup_admin"] = True
            return redirect(url_for("configuracao.banco"))
        flash("Senha inválida.", "erro")

    return render_template("configuracao.html", etapa="entrar")


@bp.route("/sair")
def sair():
    session.pop("setup_admin", None)
    return redirect(url_for("configuracao.inicio"))


@bp.route("/banco", methods=["GET", "POST"])
def banco():
    """Configuracao do banco. Acessivel:
    - em modo de configuracao (banco indisponivel): pelo admin de configuracao;
    - com o sistema funcionando: pelo usuario logado com perfil "admin"
      (item "Configuração do Banco" no menu lateral)."""
    modo_setup = _estado["ativo"]
    if modo_setup:
        if not _sessao_admin_configuracao():
            return redirect(url_for("configuracao.inicio"))
    elif not session.get("usuario_id"):
        return redirect(url_for("login", next=request.path))
    elif session.get("perfil") != "admin":
        flash("Voce nao tem permissao para acessar esta pagina.", "erro")
        return redirect(url_for("dashboard"))

    url_atual, url_integra_atual = ler_urls_banco()
    erros = {}
    if request.method == "POST":
        campos = {"principal": _campos_do_form("principal"),
                  "integra": _campos_do_form("integra")}
        campos["integra"]["schema"] = request.form.get("integra_schema", "").strip()
        mesmo_servidor = bool(request.form.get("integra_mesmo_servidor"))
        # Senha em branco = manter a atual (se servidor/porta/usuario nao mudaram).
        _completar_senha(campos["principal"], url_atual)
        if mesmo_servidor:
            for chave in ("host", "porta", "usuario", "senha"):
                campos["integra"][chave] = campos["principal"][chave]
        else:
            _completar_senha(campos["integra"], url_integra_atual)

        urls = {}
        acoes = []
        for nome, dados in campos.items():
            erro = _validar_campos(dados)
            if erro is None:
                urls[nome] = _montar_url(dados)
                if nome == "principal":
                    # Cria o banco e as tabelas se nao existirem.
                    erro, acoes = db.preparar_banco(urls[nome], SCHEMA_PATH)
                else:
                    # Conecta e confere o schema dos dados de pacientes.
                    erro = db.verificar_schema_integra(urls[nome], dados["schema"])
            if erro:
                erros[nome] = erro

        if not erros:
            if not os.environ.get("ENCRYPTION_KEY"):
                _gravar_env({"ENCRYPTION_KEY": Fernet.generate_key().decode()})
            _gravar_env({
                "DATABASE_URL": cifrar(urls["principal"]),
                "INTEGRA_DATABASE_URL": cifrar(urls["integra"]),
                "INTEGRA_SCHEMA": campos["integra"]["schema"],
            })
            if _conectar_bancos():
                feito = f" ({', '.join(acoes)})" if acoes else ""
                if modo_setup or not _mesmo_banco(urls["principal"], url_atual):
                    # Banco principal novo: os usuarios podem ser outros.
                    session.clear()
                    flash(f"Banco de dados configurado{feito}. Entre com seu usuário do sistema.", "sucesso")
                    return redirect(url_for("login"))
                flash(f"Configuração do banco salva{feito}.", "sucesso")
                return redirect(url_for("configuracao.banco"))
            erros["principal"] = _estado["erro"]
    else:
        campos = {"principal": _campos_da_url(url_atual),
                  "integra": _campos_da_url(url_integra_atual)}
        campos["integra"]["schema"] = ler_integra_schema()
        mesmo_servidor = all(
            campos["principal"][c] == campos["integra"][c] for c in ("host", "porta", "usuario")
        )

    # As senhas nunca voltam para a pagina.
    for dados in campos.values():
        dados["senha"] = ""
    contexto = dict(campos=campos, mesmo_servidor=mesmo_servidor, erros=erros,
                    modo_setup=modo_setup)
    if modo_setup:
        return render_template("configuracao.html", etapa="banco",
                               erro_inicial=_estado["erro"], **contexto)
    return render_template("configuracao_banco.html", active_page="configuracao_banco",
                           **contexto)


def _mesmo_banco(url_a, url_b):
    a, b = _campos_da_url(url_a), _campos_da_url(url_b)
    return all(a[c] == b[c] for c in ("host", "porta", "banco"))


def _completar_senha(dados, url_atual):
    """Se a senha veio em branco e servidor, porta e usuario sao os mesmos da
    conexao atual, reaproveita a senha atual."""
    if dados["senha"]:
        return
    atual = _campos_da_url(url_atual)
    if all(dados[c] == atual[c] for c in ("host", "porta", "usuario")):
        try:
            dados["senha"] = unquote(urlparse(url_atual).password or "")
        except ValueError:
            pass


def _validar_campos(dados):
    rotulos = {"host": "servidor", "porta": "porta", "banco": "banco", "usuario": "usuário"}
    faltando = [rotulo for chave, rotulo in rotulos.items() if not dados[chave]]
    if faltando:
        return "Preencha: " + ", ".join(faltando) + "."
    if not dados["porta"].isdigit():
        return "A porta deve ser um número."
    if "schema" in dados:
        if not dados["schema"]:
            return "Preencha: schema dos dados de pacientes."
        if not SCHEMA_VALIDO.match(dados["schema"]):
            return "Schema inválido: use apenas letras, números e _ (sem começar por número)."
    return None


def _campos_da_url(url):
    vazio = {"host": "", "porta": "5432", "banco": "", "usuario": "", "senha": ""}
    try:
        partes = urlparse(url)
        porta = str(partes.port or 5432)
    except ValueError:
        return vazio
    if partes.scheme not in ("postgres", "postgresql"):
        return vazio
    return {
        "host": partes.hostname or "",
        "porta": porta,
        "banco": unquote(partes.path.lstrip("/")),
        "usuario": unquote(partes.username or ""),
        "senha": "",
    }


def _campos_do_form(prefixo):
    dados = {chave: request.form.get(f"{prefixo}_{chave}", "").strip()
             for chave in CAMPOS_CONEXAO}
    dados["senha"] = request.form.get(f"{prefixo}_senha", "")  # senha sem strip
    return dados


def _montar_url(dados):
    credenciais = quote(dados["usuario"], safe="")
    if dados["senha"]:
        credenciais += ":" + quote(dados["senha"], safe="")
    host = dados["host"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    return (f"postgresql://{credenciais}@{host}:{dados['porta']}/"
            f"{quote(dados['banco'], safe='')}")
