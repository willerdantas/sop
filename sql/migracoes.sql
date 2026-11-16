-- =========================================================
-- Migracoes de estrutura do banco "sop" (idempotente)
-- =========================================================
-- Aplicado automaticamente a cada inicio (db.preparar_banco), depois do
-- schema.sql e antes do seguranca.sql. O schema.sql so roda em banco novo;
-- colunas/tabelas criadas depois devem entrar AQUI para chegar tambem aos
-- bancos que ja existem. Use sempre "IF NOT EXISTS" (pode rodar de novo).
-- =========================================================

-- ---------------------------------------------------------
-- Prontuarios devolvidos ao SOP (pela Unidade ou por Contas Medicas)
-- aguardam a confirmacao de recebimento no SOP.
-- DEFAULT FALSE: prontuarios que ja estao no SOP nao ficam pendentes.
-- ---------------------------------------------------------
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS aguardando_recebimento_sop BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS devolvido_sop_por VARCHAR(30);  -- unidade | contas_medicas
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS recebido_sop_em TIMESTAMP;
ALTER TABLE prontuarios ADD COLUMN IF NOT EXISTS recebido_sop_usuario_id INTEGER REFERENCES usuarios(id);
