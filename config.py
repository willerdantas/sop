import os
import re

from crypto_utils import decifrar

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

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-trocar-em-producao")

    # INTEGRA_DATABASE_URL: banco do sistema hospitalar (ISIVITA/SESA) -
    # somente leitura. Usado para consultar unidades (t_clinica) e altas
    # (t_internacao_leito). Valores lidos na inicializacao; os pools usam
    # ler_urls_banco(), que reflete alteracoes feitas pelo modo de configuracao.
    DATABASE_URL, INTEGRA_DATABASE_URL = ler_urls_banco()

    # Usuario administrador criado automaticamente no primeiro start,
    # caso a tabela usuarios esteja vazia.
    ADMIN_DEFAULT_LOGIN = decifrar(os.environ.get("ADMIN_DEFAULT_LOGIN", "admin"))
    ADMIN_DEFAULT_SENHA = decifrar(os.environ.get("ADMIN_DEFAULT_SENHA", "admin123"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

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
