-- =========================================================
-- Usuarios de banco com o MENOR PRIVILEGIO para a aplicacao
-- =========================================================
-- NAO e executado pela aplicacao. Rode manualmente, com psql, como
-- superusuario (postgres), no servidor do banco:
--
--     psql -U postgres -h <servidor> -f sql/permissoes.sql
--
-- Antes: suba a app UMA vez com o usuario atual (dono das tabelas), para
-- que o schema.sql e o sql/seguranca.sql sejam aplicados. O usuario
-- restrito nao tem permissao de criar/alterar tabelas.
--
-- Depois: na tela "Configuracao do Banco" (admin), troque o usuario/senha
-- das conexoes para sop_app (banco principal) e sop_leitura (ISIVITA).
-- Com sop_app a row-level security de sql/seguranca.sql passa a valer.
--
-- TROQUE as senhas abaixo antes de rodar (e nao as grave no git).
-- Ajuste os nomes dos bancos/schema se forem diferentes.
-- =========================================================

-- ---------------------------------------------------------
-- 1) Banco principal "sop": le e grava dados, nao altera estrutura.
-- ---------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sop_app') THEN
        CREATE ROLE sop_app LOGIN PASSWORD 'TROQUE-ESTA-SENHA-sop_app'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END $$;

\connect sop

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE sop TO sop_app;
GRANT USAGE ON SCHEMA public TO sop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sop_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sop_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sop_app;
-- Historico de movimentacoes: somente inclusao e leitura.
REVOKE UPDATE, DELETE ON movimentacoes FROM sop_app;
-- Tabelas criadas no futuro pelo dono tambem ficam acessiveis.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sop_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sop_app;

-- ---------------------------------------------------------
-- 2) Banco do sistema hospitalar (ISIVITA): SOMENTE LEITURA, apenas nas
--    tabelas que a aplicacao consulta.
-- ---------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sop_leitura') THEN
        CREATE ROLE sop_leitura LOGIN PASSWORD 'TROQUE-ESTA-SENHA-sop_leitura'
            NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;
ALTER ROLE sop_leitura SET default_transaction_read_only = on;

\connect isivitaedb_hm

GRANT CONNECT ON DATABASE isivitaedb_hm TO sop_leitura;
GRANT USAGE ON SCHEMA integra_local TO sop_leitura;
GRANT SELECT ON
    integra_local.t_clinica, integra_local.t_enfermaria, integra_local.t_leito,
    integra_local.t_internacao, integra_local.t_internacao_leito, integra_local.t_paciente,
    integra_local.t_destino, integra_local.t_exame, integra_local.t_exame_solic,
    integra_local.t_admissao, integra_local.t_cid10, integra_local.t_internacao_alta,
    integra_local.t_motivo_alta, integra_local.t_profissional, integra_local.t_conselho
TO sop_leitura;
