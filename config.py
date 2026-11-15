import os
import re
import secrets
import time
from datetime import timedelta

from crypto_utils import decifrar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Chaves de exemplo/antigas que nunca devem assinar sessoes de verdade.
_SECRET_KEYS_INSEGURAS = {"", "dev-secret-key-trocar-em-producao", "alguma-chave-secreta-bem-grande"}


def _ler_ou_criar_secret_key():
    """SECRET_KEY assina o cookie de sessao: quem a conhece pode se passar por
    qualquer usuario. Usa a do ambiente; se faltar (ou for um valor de
    exemplo), gera uma aleatoria e guarda em instance/secret_key (fora do
    git), compartilhada por todos os processos do gunicorn."""
    chave = os.environ.get("SECRET_KEY", "").strip()
    if chave not in _SECRET_KEYS_INSEGURAS:
        return chave
    caminho = os.path.join(BASE_DIR, "instance", "secret_key")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    try:
        # O_EXCL: so um processo cria o arquivo; os demais leem o mesmo valor.
        fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as arquivo:
            arquivo.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    for _ in range(100):
        with open(caminho, encoding="utf-8") as arquivo:
            valor = arquivo.read().strip()
        if valor:
            return valor
        time.sleep(0.05)  # outro processo ainda esta gravando
    raise RuntimeError(f"Nao foi possivel ler a SECRET_KEY de {caminho}")


def _flag(nome, padrao=False):
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")

DATABASE_URL_PADRAO = "postgresql://postgres:postgres@localhost:5432/sop"
INTEGRA_DATABASE_URL_PADRAO = "postgresql://postgres:postgres@localhost:5432/isivitaedb_hm"


INTEGRA_SCHEMA_PADRAO = "integra_local"

# Nome de schema aceito: letras, numeros e "_", sem comecar por numero.
SCHEMA_VALIDO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def ler_integra_schema():
    """Schema do banco do sistema hospitalar (ISIVITA) onde ficam as tabelas
    com as informacoes dos pacientes (t_paciente, t_internacao, ...)."""
    return os.environ.get("INTEGRA_SCHEMA", "").strip() or INTEGRA_SCHEMA_PADRAO


def ler_urls_banco():
    """(DATABASE_URL, INTEGRA_DATABASE_URL) ja decifradas, lidas do ambiente
    no momento da chamada (o modo de configuracao pode altera-las em execucao)."""
    return (
        decifrar(os.environ.get("DATABASE_URL", DATABASE_URL_PADRAO)),
        decifrar(os.environ.get("INTEGRA_DATABASE_URL", INTEGRA_DATABASE_URL_PADRAO)),
    )


class Config:
    """
    Configuracoes da aplicacao. Todos os valores sensiveis devem vir
    de variaveis de ambiente (nunca deixe senha de banco hardcoded).

    DATABASE_URL, INTEGRA_DATABASE_URL, ADMIN_DEFAULT_LOGIN e
    ADMIN_DEFAULT_SENHA sao guardados CIFRADOS no .env (veja
    crypto_utils.py) e decifrados aqui na leitura.

    Defina no seu servidor (ou em um arquivo .env carregado por voce):

        SECRET_KEY=alguma-chave-secreta-bem-grande
        ENCRYPTION_KEY=<gerada com: python3 crypto_utils.py gerar-chave>
        DATABASE_URL=<cifrado com: python3 crypto_utils.py cifrar "postgresql://usuario:senha@host:5432/banco">
        ADMIN_DEFAULT_LOGIN=<cifrado>
        ADMIN_DEFAULT_SENHA=<cifrado>
    """

    SECRET_KEY = _ler_ou_criar_secret_key()

    # INTEGRA_DATABASE_URL: banco do sistema hospitalar (ISIVITA/SESA) -
    # somente leitura. Usado para consultar unidades (t_clinica) e altas
    # (t_internacao_leito). Valores lidos na inicializacao; os pools usam
    # ler_urls_banco(), que reflete alteracoes feitas pelo modo de configuracao.
    DATABASE_URL, INTEGRA_DATABASE_URL = ler_urls_banco()

    # Usuario administrador criado automaticamente no primeiro start,
    # caso a tabela usuarios esteja vazia. Sem ADMIN_DEFAULT_SENHA, a senha
    # e a do administrador da configuracao inicial (ou uma aleatoria,
    # exibida uma unica vez no log) - nunca uma senha fixa conhecida.
    ADMIN_DEFAULT_LOGIN = decifrar(os.environ.get("ADMIN_DEFAULT_LOGIN", "admin"))
    ADMIN_DEFAULT_SENHA = decifrar(os.environ.get("ADMIN_DEFAULT_SENHA", ""))

    # --- Seguranca (ver seguranca.py) ---
    # FORCAR_HTTPS=true: redireciona http->https, liga HSTS e o cookie "Secure".
    # So ligue com HTTPS funcionando (proxy reverso ou gunicorn --certfile).
    FORCAR_HTTPS = _flag("FORCAR_HTTPS")
    # CONFIAR_PROXY=true: atras de proxy reverso (nginx/IIS), le o IP real e o
    # protocolo dos cabecalhos X-Forwarded-*. Nao ligue sem proxy na frente.
    CONFIAR_PROXY = _flag("CONFIAR_PROXY")

    SESSION_COOKIE_NAME = "sop_sessao"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = FORCAR_HTTPS
    # Sessao expira apos este tempo sem uso (renovada a cada requisicao).
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSAO_HORAS", "8")))
    # A app nao recebe arquivos: limita o tamanho de qualquer requisicao.
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 64 * 1024

    # Cache dos arquivos estaticos (CSS/JS/imagens) no navegador. Sem isso,
    # o Flask manda "Cache-Control: no-cache", forcando o navegador a
    # revalidar com o servidor a cada carregamento de pagina - fica bem
    # perceptivel em imagens grandes como a logo.
    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get("STATIC_CACHE_SECONDS", "3600"))  # 1 hora

    # Faz o Flask checar o arquivo de cada template a cada requisicao e
    # recarregar se tiver mudado - sem isso, o Gunicorn (que nao reinicia
    # sozinho) mantem os .html compilados em memoria, entao editar um
    # template so tem efeito depois de reiniciar o container. Tem um custo
    # (stat no disco a cada request), entao fica desligado por padrao e so
    # e ligado em desenvolvimento via TEMPLATES_AUTO_RELOAD=true no ambiente.
    TEMPLATES_AUTO_RELOAD = os.environ.get("TEMPLATES_AUTO_RELOAD", "false").lower() == "true"

    # Intervalo (ms) de atualizacao do painel em tempo real no front-end
    PAINEL_POLL_INTERVAL_MS = int(os.environ.get("PAINEL_POLL_INTERVAL_MS", "5000"))
