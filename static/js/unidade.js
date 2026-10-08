/**
 * unidade.js - Prontuários ainda na Unidade de origem
 * Lista prontuarios com status "unidade" e permite envia-los ao SOP.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregarUnidade();
  carregarPendenciasUnidade();

  let timerBusca;
  ["filtro-nome", "filtro-numero", "filtro-data-inicio", "filtro-data-fim"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(timerBusca);
      timerBusca = setTimeout(carregarUnidade, 350);
    });
  });
});

async function carregarUnidade() {
  const nome = document.getElementById("filtro-nome").value.trim();
  const numero = document.getElementById("filtro-numero").value.trim();
  const dataInicio = document.getElementById("filtro-data-inicio").value;
  const dataFim = document.getElementById("filtro-data-fim").value;

  const params = new URLSearchParams({ status: "unidade" });
  if (nome) params.set("nome", nome);
  if (numero) params.set("numero", numero);
  if (dataInicio) params.set("data_inicio", dataInicio);
  if (dataFim) params.set("data_fim", dataFim);

  const tbody = document.getElementById("tbody-unidade");
  const tbodyEnviados = document.getElementById("tbody-enviados-unidade");
  try {
    const lista = await apiFetch(`/api/prontuarios?${params.toString()}`);
    const enviados = lista.filter((p) => !p.recebido_unidade_em);
    const confirmados = lista.filter((p) => p.recebido_unidade_em);

    renderizarEnviados(enviados);
    renderizarTabela(confirmados);
    atualizarKpis(confirmados);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
    tbodyEnviados.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function renderizarEnviados(lista) {
  const tbody = document.getElementById("tbody-enviados-unidade");
  document.getElementById("contador-enviados-unidade").textContent = `${lista.length} pendente(s)`;

  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum prontuário aguardando confirmação.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((p) => `
    <tr>
      <td><strong>${p.numero_prontuario}</strong></td>
      <td>${p.paciente_nome}</td>
      <td>${p.unidade_nome || "-"}</td>
      <td>${p.pendencias_abertas > 0
          ? `<span class="badge badge-pendencia">${p.pendencias_abertas} aberta(s)</span>`
          : `<span class="badge badge-ok">Sem pendência</span>`}</td>
      <td>${formatarData(p.atualizado_em)}</td>
      <td class="acoes-linha">
        <button class="btn btn-primario btn-sm" onclick="confirmarRecebimentoUnidade(${p.id})">Recebido</button>
      </td>
    </tr>
  `).join("");
}

async function confirmarRecebimentoUnidade(id) {
  if (!confirm("Confirmar que este prontuário foi recebido fisicamente na unidade?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/confirmar-recebimento-unidade`, { method: "POST" });
    carregarUnidade();
  } catch (e) {
    alert(e.message);
  }
}

function atualizarKpis(lista) {
  document.getElementById("kpi-total-unidade").textContent = lista.length;
  document.getElementById("kpi-sem-pendencia").textContent = lista.filter(p => p.pendencias_abertas == 0).length;
  document.getElementById("kpi-com-pendencia").textContent = lista.filter(p => p.pendencias_abertas > 0).length;
  document.getElementById("kpi-urgentes").textContent = lista.filter(p => p.prioridade === "urgente").length;
}

function renderizarTabela(lista) {
  const tbody = document.getElementById("tbody-unidade");
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="vazio-estado">Nenhum prontuário na unidade no momento.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((p) => `
    <tr>
      <td><strong>${p.numero_prontuario}</strong></td>
      <td>${p.paciente_nome}</td>
      <td>${p.unidade_nome || "-"}</td>
      <td>${p.prioridade === "urgente" ? '<span class="badge badge-pendencia">Urgente</span>' : "Normal"}</td>
      <td>${p.localizacao_fisica || "-"}</td>
      <td>${p.pendencias_abertas > 0
          ? `<span class="badge badge-pendencia">${p.pendencias_abertas} aberta(s)</span>`
          : `<span class="badge badge-ok">Sem pendência</span>`}</td>
      <td>${formatarData(p.atualizado_em)}</td>
      <td class="acoes-linha">
        <button class="btn btn-outline btn-sm" onclick="location.href='/analise_unidade/${p.id}'">Analisar</button>
        <button class="btn btn-primario btn-sm" onclick="enviarParaSOP(${p.id})">Enviar p/ SOP</button>
      </td>
    </tr>
  `).join("");
}

async function enviarParaSOP(id) {
  if (!confirm("Confirmar envio deste prontuário para o SOP?")) return;

  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "sop", observacao: "Enviado pela Unidade de origem" }),
    });
    carregarUnidade();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarPendenciasUnidade() {
  const tbody = document.getElementById("tbody-pendencias-unidade");
  const contador = document.getElementById("contador-pendencias-unidade");
  try {
    const lista = await apiFetch("/api/pendencias?minha_unidade=1");
    const pendentes = lista.filter((p) => p.status !== "confirmada");
    contador.textContent = `${pendentes.length} pendente(s)`;

    if (!pendentes.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="vazio-estado">Nenhuma pendência pendente para esta unidade.</td></tr>`;
      return;
    }

    tbody.innerHTML = pendentes.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.tipo_descricao || "-"}</td>
        <td>${p.profissional || "-"}</td>
        <td>${formatarDataSimples(p.data_ocorrencia)}</td>
        <td>${badgeCriticidade(p.criticidade)}</td>
        <td style="max-width:260px;">${p.descricao}</td>
        <td>${badgeStatusPendencia(p.status)}</td>
        <td>${formatarTimerHorasUteis(p.horas_uteis_desde_abertura)}</td>
        <td class="acoes-linha">
          ${p.status === "resolvida"
            ? `<span class="texto-suave">Aguardando confirmação do SOP</span>`
            : `<button class="btn btn-primario btn-sm" onclick="resolverPendenciaUnidade(${p.id})">Resolver</button>`}
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function resolverPendenciaUnidade(id) {
  if (!confirm("Confirmar resolução desta pendência?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/resolver`, { method: "POST" });
    carregarPendenciasUnidade();
  } catch (e) {
    alert(e.message);
  }
}
