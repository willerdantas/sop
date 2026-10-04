-- =========================================================
-- Sistema de Fluxo e Controle de Movimentacao de Prontuarios
-- Hospital Municipal - Schema PostgreSQL
-- =========================================================
-- Execute este script no banco Postgres ja existente.
-- Ajuste o schema (CREATE SCHEMA) se desejar isolar as tabelas.
-- =========================================================

-- Extensao para gerar UUID (opcional, aqui usamos SERIAL/IDENTITY)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------
-- UNIDADES
-- ---------------------------------------------------------
-- NAO sao mais cadastradas/editadas aqui. A partir da integracao com o
-- sistema hospitalar (ISIVITA/SESA), as unidades sao consultadas ao vivo
-- em integrasesa.t_clinica (banco isivitaedb_hm, mesmo servidor Postgres,
-- acessado via INTEGRA_DATABASE_URL). Qualquer coluna "unidade_id" neste
-- schema guarda o isn_clinica desse sistema externo, sem FK local.
CREATE TABLE IF NOT EXISTS unidades (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(120) NOT NULL,
    codigo          VARCHAR(20) UNIQUE,
    tipo            VARCHAR(60),
    ativo           BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em       TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------
-- PERFIS (controle de acesso por pagina, gerenciavel via tela Perfis)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS perfis (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(60) UNIQUE NOT NULL,  -- valor armazenado em usuarios.perfil
    protegido   BOOLEAN NOT NULL DEFAULT FALSE, -- admin: nao pode ser editado/inativado
    ativo       BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS perfil_paginas (
    perfil_id   INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    pagina      VARCHAR(40) NOT NULL,
    PRIMARY KEY (perfil_id, pagina)
);

INSERT INTO perfis (nome, protegido, ativo) VALUES
    ('admin', TRUE, TRUE),
    ('operador', FALSE, TRUE),
    ('sop', FALSE, TRUE),
    ('contas_medicas', FALSE, TRUE)
ON CONFLICT (nome) DO NOTHING;

INSERT INTO perfil_paginas (perfil_id, pagina)
SELECT id, pagina FROM perfis,
    unnest(ARRAY['dashboard','unidade','sop','contas_medicas','pendencias','painel','clinicas','profissionais']) AS pagina
WHERE nome IN ('admin', 'sop', 'contas_medicas')
ON CONFLICT DO NOTHING;

INSERT INTO perfil_paginas (perfil_id, pagina)
SELECT id, 'unidade' FROM perfis WHERE nome = 'operador'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------
-- USUARIOS
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(150) NOT NULL,
    login           VARCHAR(60) UNIQUE NOT NULL,
    email           VARCHAR(150),
    senha_hash      VARCHAR(255) NOT NULL,
    perfil          VARCHAR(30) NOT NULL DEFAULT 'operador',  -- admin, sop, contas_medicas, operador
    unidade_id      INTEGER,                -- isn_clinica (integrasesa.t_clinica), sem FK local
    ativo           BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em       TIMESTAMP NOT NULL DEFAULT NOW(),
    ultimo_login    TIMESTAMP
);

ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_unidade_id_fkey;

-- ---------------------------------------------------------
-- TIPOS DE PENDENCIA (catalogo de inconsistencias possiveis)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tipos_pendencia (
    id              SERIAL PRIMARY KEY,
    descricao       VARCHAR(150) NOT NULL,
    setor_responsavel VARCHAR(60),          -- SOP, Contas Medicas, Unidade, Medico
    criticidade     VARCHAR(20) DEFAULT 'media', -- baixa, media, alta
    ativo           BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------
-- PRONTUARIOS FISICOS
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS prontuarios (
    id              SERIAL PRIMARY KEY,
    numero_prontuario  VARCHAR(30) UNIQUE NOT NULL,
    paciente_nome      VARCHAR(200) NOT NULL,
    paciente_matricula VARCHAR(30),
    unidade_id         INTEGER,              -- isn_clinica (integrasesa.t_clinica), sem FK local
    data_internacao    DATE,
    data_alta          DATE,
    status_atual       VARCHAR(30) NOT NULL DEFAULT 'unidade',
        -- unidade | sop | contas_medicas | pronto_faturamento | auditoria | finalizado
    prioridade         VARCHAR(10) NOT NULL DEFAULT 'normal', -- normal, urgente
    localizacao_fisica VARCHAR(120),          -- prateleira/armario/setor onde esta fisicamente
    integra_isn_internacao_leito BIGINT UNIQUE, -- isn_internacao_leito de origem (altas ISIVITA), evita reimportar
    recebido_contas_medicas_em TIMESTAMP, -- confirmacao de entrega ao chegar em contas_medicas (null = aguardando)
    criado_em          TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em       TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE prontuarios DROP CONSTRAINT IF EXISTS prontuarios_unidade_id_fkey;
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS integra_isn_internacao_leito BIGINT UNIQUE;
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS recebido_contas_medicas_em TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_prontuarios_status ON prontuarios(status_atual);
CREATE INDEX IF NOT EXISTS idx_prontuarios_unidade ON prontuarios(unidade_id);

-- ---------------------------------------------------------
-- MOVIMENTACOES (log de fluxo do prontuario entre setores)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS movimentacoes (
    id              SERIAL PRIMARY KEY,
    prontuario_id   INTEGER NOT NULL REFERENCES prontuarios(id) ON DELETE CASCADE,
    origem          VARCHAR(30) NOT NULL,
    destino         VARCHAR(30) NOT NULL,
    usuario_id      INTEGER REFERENCES usuarios(id),
    observacao      TEXT,
    data_movimentacao TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mov_prontuario ON movimentacoes(prontuario_id);

-- ---------------------------------------------------------
-- PENDENCIAS / INCONSISTENCIAS
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS pendencias (
    id                  SERIAL PRIMARY KEY,
    prontuario_id       INTEGER NOT NULL REFERENCES prontuarios(id) ON DELETE CASCADE,
    tipo_pendencia_id   INTEGER REFERENCES tipos_pendencia(id),
    descricao           TEXT NOT NULL,
    profissional        VARCHAR(150),        -- profissional responsavel/envolvido na inconsistencia
    data_ocorrencia     DATE,                -- data do fato que originou a pendencia
    unidade_id          INTEGER,             -- isn_clinica (integrasesa.t_clinica); paciente pode passar por varias
    status              VARCHAR(20) NOT NULL DEFAULT 'aberta',  -- aberta, em_analise, resolvida
    usuario_abertura_id INTEGER REFERENCES usuarios(id),
    usuario_resolucao_id INTEGER REFERENCES usuarios(id),
    data_abertura        TIMESTAMP NOT NULL DEFAULT NOW(),
    data_resolucao        TIMESTAMP
);

-- Migracao para bancos ja criados antes destes campos existirem
ALTER TABLE pendencias ADD COLUMN IF NOT EXISTS profissional VARCHAR(150);
ALTER TABLE pendencias ADD COLUMN IF NOT EXISTS data_ocorrencia DATE;
ALTER TABLE pendencias ADD COLUMN IF NOT EXISTS unidade_id INTEGER;
ALTER TABLE pendencias DROP CONSTRAINT IF EXISTS pendencias_unidade_id_fkey;

-- ---------------------------------------------------------
-- PROFISSIONAIS (medicos, enfermeiros, etc. envolvidos no atendimento)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS profissionais (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(150) NOT NULL,
    categoria       VARCHAR(60) NOT NULL,   -- Medico, Enfermeiro, Tecnico de Enfermagem, etc.
    conselho        VARCHAR(20),            -- CRM, COREN, CREFITO, CRF, CRN, CRP, CRESS...
    numero_conselho VARCHAR(30),
    uf_conselho     VARCHAR(2),
    telefone        VARCHAR(20),
    email           VARCHAR(150),
    ativo           BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pendencias_prontuario ON pendencias(prontuario_id);
CREATE INDEX IF NOT EXISTS idx_pendencias_status ON pendencias(status);

-- ---------------------------------------------------------
-- Trigger simples para atualizar atualizado_em em prontuarios
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_set_atualizado_em()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_atualizado_em ON prontuarios;
CREATE TRIGGER set_atualizado_em
    BEFORE UPDATE ON prontuarios
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_atualizado_em();

-- ---------------------------------------------------------
-- Dados iniciais (seed) - ajuste conforme a realidade do hospital
-- ---------------------------------------------------------
INSERT INTO tipos_pendencia (descricao, setor_responsavel, criticidade) VALUES
    ('Falta assinatura medica', 'Unidade', 'alta'),
    ('Prescricao incompleta', 'Unidade', 'media'),
    ('Falta laudo de exame', 'SOP', 'media'),
    ('Divergencia de procedimento faturado', 'Contas Medicas', 'alta'),
    ('Folha de evolucao faltante', 'SOP', 'media'),
    ('Guia de autorizacao ausente', 'Contas Medicas', 'alta')
ON CONFLICT DO NOTHING;

-- Usuario admin padrao (login: admin / senha definida via app.py seed_admin)
-- A senha eh gerada por hash no primeiro start da aplicacao (ver README).
