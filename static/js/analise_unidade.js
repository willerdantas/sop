/**
 * analise_unidade.js
 * Pagina de analise de um prontuario a partir da Unidade: resolve
 * pendencias e devolve o prontuario para o SOP quando todas estiverem
 * resolvidas (nenhuma mais "aberta"/"em_analise").
 */

document.addEventListener("DOMContentLoaded", () => {
  carregarPendencias();
  carregarHistorico();

  document.getElementById("btn-devolver-sop").addEventListener("click", async () => {
    if (!confirm("Confirmar devolução deste prontuário para o SOP?")) return;
    try {
      await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
        method: "POST",
        body: JSON.stringify({ destino: "sop", observacao: "Devolvido pela Unidade apos resolucao das pendencias" }),
      });
      window.location.href = "/unidade";
    } catch (e) {
      alert(e.message);
    }
  });
});

function acoesPendencia(p) {
  if (p.status === "aberta" || p.status === "em_analise") {
    return `<button class="btn btn-primario btn-sm" onclick="resolverPendencia(${p.id})">Resolver</button>`;
  }
  return `<span class="texto-suave">${p.usuario_resolucao_nome || "-"} · ${formatarData(p.data_resolucao)}</span>`;
}

async function carregarPendencias() {
  const tbody = document.getElementById("tbody-pendencias-analise");
  const btnDevolver = document.getElementById("btn-devolver-sop");
  try {
    const lista = await apiFetch(`/api/pendencias?prontuario_id=${PRONTUARIO_ID}`);
    const naoResolvidas = lista.filter(p => p.status === "aberta" || p.status === "em_analise").length;
    btnDevolver.disabled = naoResolvidas > 0;
    btnDevolver.title = naoResolvidas > 0 ? "Resolva todas as pendências antes de devolver para o SOP" : "";

    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="vazio-estado">Nenhuma pendência registrada para este prontuário.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td>${p.tipo_descricao || "-"}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${p.profissional || "-"}</td>
        <td>${formatarDataSimples(p.data_ocorrencia)}</td>
        <td>${badgeCriticidade(p.criticidade)}</td>
        <td style="max-width:320px;">${p.descricao}</td>
        <td>${badgeStatusPendencia(p.status)}</td>
        <td>${formatarData(p.data_abertura)}</td>
        <td>${formatarTimerHorasUteis(p.horas_uteis_desde_abertura)}</td>
        <td class="acoes-linha">${acoesPendencia(p)}</td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function resolverPendencia(id) {
  if (!confirm("Confirmar resolução desta pendência?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/resolver`, { method: "POST" });
    carregarPendencias();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarHistorico() {
  const container = document.getElementById("conteudo-historico");
  try {
    const historico = await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/historico`);
    if (!historico.length) {
      container.innerHTML = '<p class="vazio-estado">Sem movimentações registradas.</p>';
      return;
    }
    container.innerHTML = historico.map(h => `
      <div style="padding:10px 0; border-bottom:1px solid var(--cor-borda);">
        <strong>${badgeStatus(h.origem)} → ${badgeStatus(h.destino)}</strong>
        <div class="texto-suave" style="margin-top:4px;">${formatarData(h.data_movimentacao)} · ${h.usuario_nome || "Sistema"}</div>
        ${h.observacao ? `<div style="margin-top:4px;">${h.observacao}</div>` : ""}
      </div>
    `).join("");
  } catch (e) {
    container.innerHTML = `<p class="vazio-estado">Erro: ${e.message}</p>`;
  }
}
