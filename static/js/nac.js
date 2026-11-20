/**
 * nac.js - Prontuários arquivados (NAC)
 * Lista prontuarios com status "nac" e permite confirmar o recebimento
 * fisico. Mesma mecanica de custodia da tela Unidade, sem a secao de
 * pendencias (o NAC e um estagio de arquivamento, nao de conferencia).
 */

document.addEventListener("DOMContentLoaded", () => {
  carregarNac();

  let timerBusca;
  ["filtro-nome", "filtro-numero", "filtro-data-inicio", "filtro-data-fim"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(timerBusca);
      timerBusca = setTimeout(carregarNac, 350);
    });
  });
});

async function carregarNac() {
  const nome = document.getElementById("filtro-nome").value.trim();
  const numero = document.getElementById("filtro-numero").value.trim();
  const dataInicio = document.getElementById("filtro-data-inicio").value;
  const dataFim = document.getElementById("filtro-data-fim").value;

  const params = new URLSearchParams({ status: "nac" });
  if (nome) params.set("nome", nome);
  if (numero) params.set("numero", numero);
  if (dataInicio) params.set("data_inicio", dataInicio);
  if (dataFim) params.set("data_fim", dataFim);

  const tbody = document.getElementById("tbody-nac");
  const tbodyEnviados = document.getElementById("tbody-enviados-nac");
  try {
    const lista = await apiFetch(`/api/prontuarios?${params.toString()}`);
    const enviados = lista.filter((p) => !p.recebido_nac_em);
    const confirmados = lista.filter((p) => p.recebido_nac_em);

    renderizarEnviadosNac(enviados);
    renderizarTabelaNac(confirmados);
    document.getElementById("kpi-total-nac").textContent = confirmados.length;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
    tbodyEnviados.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function renderizarEnviadosNac(lista) {
  const tbody = document.getElementById("tbody-enviados-nac");
  document.getElementById("contador-enviados-nac").textContent = `${lista.length} pendente(s)`;

  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum prontuário aguardando confirmação.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((p) => `
    <tr>
      <td><strong>${esc(p.numero_prontuario)}</strong>${etiqueta24h(p.internacao_total_dias)}</td>
      <td>${esc(p.paciente_nome)}</td>
      <td>${esc(p.unidade_nome || "-")}</td>
      <td>${esc(formatarData(p.atualizado_em))}</td>
      <td>${badgeDiasAlta(p.dias_desde_alta)}</td>
      <td class="acoes-linha">
        <button class="btn btn-primario btn-sm" onclick="confirmarRecebimentoNac(${esc(p.id)})">Recebido</button>
      </td>
    </tr>
  `).join("");
}

async function confirmarRecebimentoNac(id) {
  if (!confirm("Confirmar que este prontuário foi recebido fisicamente no NAC?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/confirmar-recebimento-nac`, { method: "POST" });
    carregarNac();
  } catch (e) {
    alert(e.message);
  }
}

function renderizarTabelaNac(lista) {
  const tbody = document.getElementById("tbody-nac");
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Nenhum prontuário no NAC no momento.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((p) => `
    <tr>
      <td><strong>${esc(p.numero_prontuario)}</strong>${etiqueta24h(p.internacao_total_dias)}</td>
      <td>${esc(p.paciente_nome)}</td>
      <td>${esc(p.unidade_nome || "-")}</td>
      <td>${esc(p.localizacao_fisica || "-")}</td>
      <td>${esc(formatarData(p.atualizado_em))}</td>
      <td>${badgeDiasAlta(p.dias_desde_alta)}</td>
      <td class="acoes-linha">
        <button class="btn btn-outline btn-sm" onclick="location.href='/analise_c_medicas/${esc(p.id)}'">Analisar</button>
      </td>
    </tr>
  `).join("");
}
