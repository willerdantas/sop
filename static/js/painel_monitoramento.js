/**
 * painel_monitoramento.js
 * Quantidade de prontuarios por status e analises (em andamento/concluidas)
 * por usuario. Compartilhado pelas paginas de monitoramento do SOP e de
 * Contas Medicas - cada uma define PAINEL_MONITORAMENTO_URL com seu endpoint.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregarPainelMonitoramento();
});

async function carregarPainelMonitoramento() {
  try {
    const dados = await apiFetch(PAINEL_MONITORAMENTO_URL);
    renderizarStatus(dados.por_status);
    renderizarUsuarios(dados.usuarios);
  } catch (e) {
    document.getElementById("linha-kpis-status").innerHTML =
      `<div class="kpi-card"><div class="kpi-desc">Erro ao carregar: ${esc(e.message)}</div></div>`;
  }
}

function renderizarStatus(lista) {
  const container = document.getElementById("linha-kpis-status");
  container.innerHTML = lista.map((s) => `
    <div class="kpi-card">
      <div class="kpi-num">${esc(s.total)}</div>
      <div class="kpi-desc">${esc(s.label)}</div>
    </div>
  `).join("");
}

function renderizarUsuarios(lista) {
  const tbody = document.getElementById("tbody-usuarios-monitoramento");
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="vazio-estado">Nenhuma análise registrada ainda.</td></tr>`;
    return;
  }
  tbody.innerHTML = lista.map((u) => `
    <tr>
      <td><strong>${esc(u.nome)}</strong></td>
      <td>${esc(u.em_analise)}</td>
      <td>${esc(u.analisados)}</td>
    </tr>
  `).join("");
}
