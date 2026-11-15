-- =========================================================
-- Ajustes de seguranca do banco "sop" (idempotente)
-- =========================================================
-- Aplicado automaticamente pela aplicacao a cada inicio
-- (db.preparar_banco), depois do schema.sql. Pode ser rodado de novo
-- sem efeito colateral. Os blocos DO tratam o proprio erro, para que um
-- ajuste que falhe (ex: dado antigo fora do padrao) nao impeca os demais.
-- =========================================================

-- ---------------------------------------------------------
-- Limite de tentativas de login (seguranca.py)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tentativas_login (
    id          BIGSERIAL PRIMARY KEY,
    login       VARCHAR(60) NOT NULL,
    ip          VARCHAR(64) NOT NULL,
    criado_em   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tentativas_login_login ON tentativas_login(login, criado_em);
CREATE INDEX IF NOT EXISTS idx_tentativas_login_ip ON tentativas_login(ip, criado_em);

-- ---------------------------------------------------------
-- Versao da sessao: incrementada ao trocar senha/perfil ou inativar o
-- usuario, derrubando as sessoes ja abertas dele.
-- ---------------------------------------------------------
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS sessao_versao INTEGER NOT NULL DEFAULT 0;

-- ---------------------------------------------------------
-- Dados pessoais gravados cifrados (crypto_utils.cifrar_campo): o texto
-- cifrado e bem maior que o original, entao as colunas viram TEXT (o
-- limite de tamanho do valor digitado continua validado na app).
-- ---------------------------------------------------------
DO $$
DECLARE
    alvo RECORD;
BEGIN
    FOR alvo IN
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND data_type <> 'text'
          AND (table_name, column_name) IN (('usuarios','email'), ('profissionais','email'),
                                            ('profissionais','telefone'))
    LOOP
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE TEXT', alvo.table_name, alvo.column_name);
    END LOOP;
END $$;

-- ---------------------------------------------------------
-- Valores aceitos nos campos de fluxo (bloqueia adulteracao mesmo por
-- fora da API). NOT VALID: vale para gravacoes novas, sem travar a
-- migracao por causa de algum registro antigo.
-- ---------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_prontuarios_status') THEN
        ALTER TABLE prontuarios ADD CONSTRAINT ck_prontuarios_status CHECK (status_atual IN
            ('unidade','sop','contas_medicas','pronto_faturamento','auditoria','finalizado')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_prontuarios_prioridade') THEN
        ALTER TABLE prontuarios ADD CONSTRAINT ck_prontuarios_prioridade
            CHECK (prioridade IN ('normal','urgente')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_prontuarios_dias') THEN
        ALTER TABLE prontuarios ADD CONSTRAINT ck_prontuarios_dias CHECK (
            COALESCE(dias_enfermaria, 0) >= 0 AND COALESCE(dias_uti, 0) >= 0
            AND COALESCE(diaria_acompanhante, 0) >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_pendencias_status') THEN
        ALTER TABLE pendencias ADD CONSTRAINT ck_pendencias_status
            CHECK (status IN ('aberta','em_analise','resolvida','confirmada')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_prontuario_procedimentos_qtd') THEN
        ALTER TABLE prontuario_procedimentos ADD CONSTRAINT ck_prontuario_procedimentos_qtd
            CHECK (quantidade > 0) NOT VALID;
    END IF;
EXCEPTION WHEN others THEN
    RAISE WARNING 'restricoes de valores nao aplicadas: %', SQLERRM;
END $$;

-- ---------------------------------------------------------
-- Historico de movimentacoes e somente-inclusao: ninguem altera ou apaga
-- o registro de quem moveu o prontuario (nem a app, nem acesso direto).
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_bloquear_alteracao_historico()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'o historico de movimentacoes nao pode ser alterado ou apagado';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS bloquear_alteracao_movimentacoes ON movimentacoes;
CREATE TRIGGER bloquear_alteracao_movimentacoes
    BEFORE UPDATE OR DELETE ON movimentacoes
    FOR EACH ROW EXECUTE FUNCTION trg_bloquear_alteracao_historico();

-- ---------------------------------------------------------
-- Row-level security: usuario vinculado a unidades so enxerga
-- prontuarios dessas unidades (ou com pendencia registrada nelas).
--
-- A app informa as unidades do usuario em cada requisicao
-- (db.aplicar_contexto_rls -> app.unidade_ids). Vazio = sem restricao
-- (admin / usuario sem unidade), igual a regra da propria aplicacao.
--
-- IMPORTANTE: o Postgres NAO aplica RLS ao dono da tabela nem a
-- superusuarios. A politica so passa a valer quando a app conectar com o
-- usuario restrito criado por sql/permissoes.sql.
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION app_unidades_usuario()
RETURNS INTEGER[] AS $$
    SELECT CASE
        WHEN COALESCE(current_setting('app.unidade_ids', true), '') = '' THEN NULL
        ELSE string_to_array(current_setting('app.unidade_ids', true), ',')::INTEGER[]
    END
$$ LANGUAGE sql STABLE;

ALTER TABLE prontuarios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS prontuarios_por_unidade ON prontuarios;
CREATE POLICY prontuarios_por_unidade ON prontuarios
    USING (
        app_unidades_usuario() IS NULL
        OR unidade_id = ANY (app_unidades_usuario())
        OR EXISTS (SELECT 1 FROM pendencias pe
                   WHERE pe.prontuario_id = prontuarios.id
                     AND pe.unidade_id = ANY (app_unidades_usuario()))
    );
