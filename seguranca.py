"""
Protecoes HTTP da aplicacao (registradas por init_app, antes das rotas):

- CSRF: todo POST/PUT/PATCH/DELETE precisa do token da sessao, enviado no
  campo "csrf_token" (formularios) ou no cabecalho X-CSRFToken (apiFetch).
- Cookie de sessao HttpOnly + SameSite=Lax (+ Secure com HTTPS), com
  expiracao por inatividade (PERMANENT_SESSION_LIFETIME).
- Cabecalhos de seguranca (CSP, nosniff, anti-clickjacking, HSTS...) e
  Cache-Control: no-store nas respostas com dados.
- FORCAR_HTTPS: redireciona http -> https.
- Erros: respostas curtas, sem stack trace nem mensagem interna do banco.
- Limite de tentativas de login (por login e por IP) e campo "isca"
  (honeypot) contra robos.
"""
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import current_app, flash, jsonify, redirect, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import db
from validacao import EntradaInvalida

log = logging.getLogger(__name__)

CSRF_CAMPO = "csrf_token"
CSRF_CABECALHO = "X-CSRFToken"
_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}

# Campo escondido no formulario de login: pessoas nao o veem nem preenchem;
# robos que preenchem todos os campos se denunciam.
CAMPO_ISCA = "website"

# Limite de tentativas de login (janela deslizante).
JANELA_MINUTOS = 15
MAX_FALHAS_POR_LOGIN = 5
MAX_FALHAS_POR_IP = 20

_CDN = "https://cdnjs.cloudflare.com"
CSP = "; ".join([
    "default-src 'self'",
    # 'unsafe-inline' ainda e necessario pelos onclick="..." gerados no JS;
    # sem 'unsafe-eval' e apenas este CDN como origem externa.
    f"script-src 'self' 'unsafe-inline' {_CDN}",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def init_app(app):
    if app.config.get("CONFIAR_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.jinja_env.globals["csrf_token"] = token_csrf
    app.jinja_env.globals["campo_isca"] = CAMPO_ISCA

    app.before_request(_forcar_https)
    app.before_request(_sessao_com_expiracao)
    app.before_request(_validar_csrf)
    app.after_request(_cabecalhos_seguranca)

    app.register_error_handler(EntradaInvalida, _erro_entrada)
    app.register_error_handler(HTTPException, _erro_http)
    app.register_error_handler(Exception, _erro_interno)


# ---------------------------------------------------------------
# HTTPS, sessao e CSRF
# ---------------------------------------------------------------
def _eh_api():
    return request.path.startswith("/api/")


def _forcar_https():
    if not current_app.config.get("FORCAR_HTTPS") or request.is_secure:
        return None
    return redirect(request.url.replace("http://", "https://", 1), code=308)


def _sessao_com_expiracao():
    # Sessao "permanente" = cookie com validade (PERMANENT_SESSION_LIFETIME),
    # renovada a cada requisicao; o Flask tambem recusa cookies mais velhos.
    if request.endpoint != "static" and not session.permanent:
        session.permanent = True


def token_csrf():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


def _validar_csrf():
    if request.method in _METODOS_SEGUROS:
        return None
    esperado = session.get("_csrf")
    recebido = request.headers.get(CSRF_CABECALHO) or request.form.get(CSRF_CAMPO)
    if esperado and recebido and hmac.compare_digest(esperado, recebido):
        return None
    log.warning("CSRF recusado: %s %s (ip %s)", request.method, request.path, request.remote_addr)
    if _eh_api():
        return jsonify({"erro": "sessao expirada ou requisicao invalida - recarregue a pagina"}), 403
    flash("Sua sessão expirou ou o formulário ficou desatualizado. Tente novamente.", "erro")
    return redirect(request.path)


def _cabecalhos_seguranca(resposta):
    h = resposta.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Content-Security-Policy", CSP)
    if current_app.config.get("FORCAR_HTTPS"):
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint != "static":
        # Paginas e API trazem dados de pacientes: nada de cache em disco/proxy.
        h["Cache-Control"] = "no-store"
        h["Pragma"] = "no-cache"
    return resposta


# ---------------------------------------------------------------
# Erros: nada de detalhes internos para o cliente
# ---------------------------------------------------------------
def _erro_entrada(exc):
    if _eh_api():
        return jsonify({"erro": str(exc)}), 400
    return str(exc), 400


def _erro_http(exc):
    if _eh_api():
        return jsonify({"erro": (exc.name or "erro").lower()}), exc.code
    return exc


def _erro_interno(exc):
    log.exception("Erro nao tratado em %s %s", request.method, request.path)
    try:
        db.descartar_transacao()
    except Exception:  # noqa: BLE001 - nao mascarar o erro original
        pass
    if _eh_api():
        return jsonify({"erro": "erro interno do servidor"}), 500
    return "Erro interno do servidor. Tente novamente ou contate o suporte.", 500


# ---------------------------------------------------------------
# Limite de tentativas de login
# ---------------------------------------------------------------
def ip_cliente():
    return (request.remote_addr or "?")[:64]


def segundos_bloqueio_login(login):
    """>0 se o login (ou o IP) excedeu as falhas na janela: segundos ate liberar."""
    linha = db.query(
        """SELECT
               COUNT(*) FILTER (WHERE login = %(login)s) AS falhas_login,
               COUNT(*) FILTER (WHERE ip = %(ip)s) AS falhas_ip,
               MIN(criado_em) FILTER (WHERE login = %(login)s) AS primeira_login,
               MIN(criado_em) FILTER (WHERE ip = %(ip)s) AS primeira_ip,
               NOW()::timestamp AS agora
           FROM tentativas_login
           WHERE criado_em > NOW() - make_interval(mins => %(janela)s)
             AND (login = %(login)s OR ip = %(ip)s)""",
        {"login": login[:60], "ip": ip_cliente(), "janela": JANELA_MINUTOS},
        fetchone=True,
    )
    primeiras = []
    if linha["falhas_login"] >= MAX_FALHAS_POR_LOGIN:
        primeiras.append(linha["primeira_login"])
    if linha["falhas_ip"] >= MAX_FALHAS_POR_IP:
        primeiras.append(linha["primeira_ip"])
    if not primeiras:
        return 0
    restante = (min(primeiras) - linha["agora"]).total_seconds() + JANELA_MINUTOS * 60
    return max(1, int(restante))


def registrar_falha_login(login):
    db.execute(
        "INSERT INTO tentativas_login (login, ip) VALUES (%s, %s)",
        (login[:60], ip_cliente()),
    )
    if secrets.randbelow(50) == 0:  # limpeza ocasional do historico antigo
        db.execute("DELETE FROM tentativas_login WHERE criado_em < NOW() - INTERVAL '1 day'")


def limpar_falhas_login(login):
    db.execute("DELETE FROM tentativas_login WHERE login = %s", (login[:60],))


class LimitadorMemoria:
    """Limite de tentativas em memoria (usado onde ainda nao ha banco, ex:
    senha da configuracao inicial). Vale por processo."""

    def __init__(self, maximo, janela_segundos):
        self.maximo = maximo
        self.janela = janela_segundos
        self._falhas = defaultdict(deque)
        self._lock = threading.Lock()

    def _limpar(self, chave, agora):
        fila = self._falhas[chave]
        while fila and fila[0] <= agora - self.janela:
            fila.popleft()
        return fila

    def segundos_bloqueio(self, chave):
        agora = time.monotonic()
        with self._lock:
            fila = self._limpar(chave, agora)
            if len(fila) < self.maximo:
                return 0
            return max(1, int(fila[0] + self.janela - agora))

    def registrar_falha(self, chave):
        agora = time.monotonic()
        with self._lock:
            self._limpar(chave, agora).append(agora)

    def limpar(self, chave):
        with self._lock:
            self._falhas.pop(chave, None)
