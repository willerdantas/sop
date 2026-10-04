import os


class Config:
    """
    Configuracoes da aplicacao. Todos os valores sensiveis devem vir
    de variaveis de ambiente (nunca deixe senha de banco hardcoded).

    Defina no seu servidor (ou em um arquivo .env carregado por voce):

        SECRET_KEY=alguma-chave-secreta-bem-grande
        DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco
        ADMIN_DEFAULT_LOGIN=admin
        ADMIN_DEFAULT_SENHA=troque-esta-senha
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-trocar-em-producao")

    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/sop",
    )

    # Banco do sistema hospitalar (ISIVITA/SESA) - somente leitura.
    # Usado para consultar unidades (t_clinica) e altas (t_internacao_leito).
    INTEGRA_DATABASE_URL = os.environ.get(
        "INTEGRA_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/isivitaedb_hm",
    )

    # Usuario administrador criado automaticamente no primeiro start,
    # caso a tabela usuarios esteja vazia.
    ADMIN_DEFAULT_LOGIN = os.environ.get("ADMIN_DEFAULT_LOGIN", "admin")
    ADMIN_DEFAULT_SENHA = os.environ.get("ADMIN_DEFAULT_SENHA", "admin123")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Intervalo (ms) de atualizacao do painel em tempo real no front-end
    PAINEL_POLL_INTERVAL_MS = int(os.environ.get("PAINEL_POLL_INTERVAL_MS", "5000"))
