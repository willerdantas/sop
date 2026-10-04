/**
 * sop.js - Serviço de Organização de Prontuários
 * Lista prontuarios com status "sop", permite cadastrar novos
 * e move-los para "contas_medicas" quando conferidos.
 */

let altasCache = {};
let altasPaginaAtual = 1;

document.addEventListener("DOMContentLoaded", () => {
  carregarSOP();
  carregarAltas(1);
  carregarEnviadosContas();

  document.getElementById("btn-altas-anterior").addEventListener("click", () => carregarAltas(altasPaginaAtual - 1));
  document.getElementById("btn-altas-proxima").addEventListener("click", () => carregarAltas(altasPaginaAtual + 1));

  document.getElementById("btn-novo-prontuario").addEventListener("click", () => abrirModal("modal-novo-prontuario"));

  document.getElementById("form-registrar-alta").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const isn = dados.isn_internacao_leito;
    delete dados.isn_internacao_leito;

    try {
      await apiFetch(`/api/altas/${isn}/registrar`, { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-registrar-alta");
      form.reset();
      carregarAltas(altasPaginaAtual);
      carregarSOP();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("form-novo-prontuario").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    try {
      await apiFetch("/api/prontuarios", { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-novo-prontuario");
      form.reset();
      carregarSOP();
    } catch (e) {
      alert(e.message);
    }
  });

  let timerBusca;
  ["filtro-nome", "filtro-numero", "filtro-data-inicio", "filtro-data-fim"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(timerBusca);
      timerBusca = setTimeout(carregarSOP, 350);
    });
  });
});

async function carregarSOP() {
  const nome = document.getElementById("filtro-nome").value.trim();
  const numero = document.getElementById("filtro-numero").value.trim();
  const dataInicio = document.getElementById("filtro-data-inicio").value;
  const dataFim = document.getElementById("filtro-data-fim").value;

  const params = new URLSearchParams({ status: "sop" });
  if (nome) params.set("nome", nome);
  if (numero) params.set("numero", numero);
  if (dataInicio) params.set("data_inicio", dataInicio);
  if (dataFim) params.set("data_fim", dataFim);

  const tbody = document.getElementById("tbody-sop");
  try {
    const lista = await apiFetch(`/api/prontuarios?${params.toString()}`);
    renderizarTabela(lista);
    atualizarKpis(lista);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function atualizarKpis(lista) {
  document.getElementById("kpi-total-sop").textContent = lista.length;
  document.getElementById("kpi-sem-pendencia").textContent = lista.filter(p => p.pendencias_abertas == 0).length;
  document.getElementById("kpi-com-pendencia").textContent = lista.filter(p => p.pendencias_abertas > 0).length;
  document.getElementById("kpi-urgentes").textContent = lista.filter(p => p.prioridade === "urgente").length;
}

function renderizarTabela(lista) {
  const tbody = document.getElementById("tbody-sop");
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="vazio-estado">Nenhum prontuário no SOP no momento.</td></tr>`;
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
      <td>${formatarTimerSOP(p.horas_uteis_no_sop)}</td>
      <td class="acoes-linha">
        <button class="btn btn-outline btn-sm" onclick="location.href='/analise/${p.id}'">Analisar</button>
        <button class="btn btn-primario btn-sm" onclick="enviarParaContasMedicas(${p.id}, ${p.pendencias_abertas})">
          Enviar p/ Contas Médicas
        </button>
      </td>
    </tr>
  `).join("");
}

async function enviarParaContasMedicas(id, pendenciasAbertas) {
  if (pendenciasAbertas > 0) {
    alert("Este prontuário possui pendências abertas. Resolva-as na página de Análise antes de enviar.");
    return;
  }
  if (!confirm("Confirmar envio deste prontuário para Contas Médicas?")) return;

  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "contas_medicas", observacao: "Conferido pelo SOP" }),
    });
    carregarSOP();
  } catch (e) {
    alert(e.message);
  }
}

const DESTINO_BADGE_CLASSE = {
  "Residência": "badge-ok",
  "Outro hospital": "badge-media",
  "Óbito": "badge-pendencia",
};

async function carregarAltas(pagina) {
  const tbody = document.getElementById("tbody-altas");
  const contador = document.getElementById("contador-altas");
  const paginacao = document.getElementById("paginacao-altas");
  try {
    const resp = await apiFetch(`/api/altas?pagina=${pagina}`);
    const lista = resp.itens;
    altasPaginaAtual = resp.pagina;
    altasCache = Object.fromEntries(lista.map((a) => [a.isn_internacao_leito, a]));
    contador.textContent = `${resp.total} pendente(s)`;

    paginacao.style.display = resp.total_paginas > 1 ? "flex" : "none";
    document.getElementById("altas-pagina-info").textContent = `Página ${resp.pagina} de ${resp.total_paginas}`;
    document.getElementById("btn-altas-anterior").disabled = resp.pagina <= 1;
    document.getElementById("btn-altas-proxima").disabled = resp.pagina >= resp.total_paginas;

    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="vazio-estado">Nenhuma alta pendente de registro.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((a) => `
      <tr>
        <td>${a.isn_internacao}</td>
        <td>${a.num_prontuario || '<span class="texto-suave">não informado</span>'}</td>
        <td>${a.paciente_nome}</td>
        <td>${a.unidade_nome || "-"}</td>
        <td>${formatarDataSimples(a.dat_internacao)}</td>
        <td>${formatarDataSimples(a.dat_alta)}${a.hor_alta ? " " + a.hor_alta : ""}</td>
        <td><span class="badge ${DESTINO_BADGE_CLASSE[a.dsc_destino] || "badge-unidade"}">${a.dsc_destino || "-"}</span></td>
        <td>${formatarTimerHorasUteis(a.horas_uteis_desde_alta)}</td>
        <td class="acoes-linha">
          ${a.num_prontuario
            ? `<button class="btn btn-laranja btn-sm" onclick="abrirModalRegistrarAlta(${a.isn_internacao_leito})">Registrar no Fluxo</button>`
            : `<button class="btn btn-ghost btn-sm" disabled title="Sem número de prontuário no sistema hospitalar">Registrar no Fluxo</button>`}
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function abrirModalRegistrarAlta(isn) {
  const a = altasCache[isn];
  if (!a) return;

  if (!a.num_prontuario) {
    alert("Esta alta não possui número de prontuário informado no sistema hospitalar e não pode ser registrada no fluxo.");
    return;
  }

  document.getElementById("alta-paciente-nome").textContent = a.paciente_nome || "-";
  document.getElementById("alta-unidade-nome").textContent = a.unidade_nome || "-";
  document.getElementById("alta-data-internacao").textContent = formatarDataSimples(a.dat_internacao);
  document.getElementById("alta-data-alta").textContent = `${formatarDataSimples(a.dat_alta)}${a.hor_alta ? " " + a.hor_alta : ""}`;
  document.getElementById("alta-numero-prontuario").textContent = a.num_prontuario;
  document.getElementById("alta-destino").textContent = a.dsc_destino || "-";

  const form = document.getElementById("form-registrar-alta");
  form.reset();
  form.querySelector('[name="isn_internacao_leito"]').value = a.isn_internacao_leito;

  abrirModal("modal-registrar-alta");
}

async function carregarEnviadosContas() {
  const tbody = document.getElementById("tbody-enviados-contas");
  try {
    const lista = await apiFetch(`/api/prontuarios?status=contas_medicas`);
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhum prontuário enviado para Contas Médicas ainda.</td></tr>`;
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
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}
