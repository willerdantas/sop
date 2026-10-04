"""
Camada de acesso ao banco de dados PostgreSQL.

Usa um pool de conexoes simples via psycopg2. Todas as funcoes de
rota do app.py devem passar por aqui em vez de abrir conexoes soltas.

Alem do banco principal (sop), ha um segundo pool somente-leitura
para o banco do sistema hospitalar (ISIVITA/SESA - isivitaedb_hm),
usado para consultar unidades e altas. Esse banco e o sistema de
registro oficial do hospital e NUNCA deve ser alterado por aqui.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import g

_pool = None
_pool_integra = None


def init_pool(app):
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=app.config["DATABASE_URL"],
    )


def init_pool_integra(app):
    global _pool_integra
    _pool_integra = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=5,
        dsn=app.config["INTEGRA_DATABASE_URL"],
    )


def get_conn():
    if "db_conn" not in g:
        g.db_conn = _pool.getconn()
    return g.db_conn


def get_conn_integra():
    if "db_conn_integra" not in g:
        conn = _pool_integra.getconn()
        conn.set_session(readonly=True, autocommit=True)
        g.db_conn_integra = conn
    return g.db_conn_integra


def close_conn(e=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        _pool.putconn(conn)

    conn_integra = g.pop("db_conn_integra", None)
    if conn_integra is not None:
        _pool_integra.putconn(conn_integra)


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
