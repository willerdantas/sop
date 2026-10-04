/**
 * analise.js
 * Pagina de analise de um prontuario especifico: registra pendencias,
 * mostra historico de movimentacao e permite avancar para contas medicas.
 */

let pendenciasAbertasCount = 0;

document.addEventListener("DOMContentLoaded", () => {
  carregarPendencias();
  carregarHistorico();

  document.getElementById("btn-nova-pendencia").addEventListener("click", () => abrirModal("modal-nova-pendencia"));

  document.getElementById("form-nova-pendencia").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    dados.prontuario_id = PRONTUARIO_ID;

    try {
      await apiFetch("/api/pendencias", { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-nova-pendencia");
      form.reset();
      carregarPendencias();
    } catch (e) {
      alert(e.message);
    }
  });

  const btnEnviarContas = document.getElementById("btn-enviar-contas");
  if (btnEnviarContas) {
    btnEnviarContas.addEventListener("click", async () => {
      if (pendenciasAbertasCount > 0) {
        alert("Este prontuário possui pendências abertas. Resolva-as antes de enviar para Contas Médicas.");
        return;
      }
      if (!confirm("Confirmar envio deste prontuário para Contas Médicas?")) return;

      try {
        await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
          method: "POST",
          body: JSON.stringify({ destino: "contas_medicas", observacao: "Conferido pelo SOP" }),
        });
        window.location.href = "/sop";
      } catch (e) {
        alert(e.message);
      }
    });
  }

  const btnEnviarSop = document.getElementById("btn-enviar-sop");
  if (btnEnviarSop) {
    btnEnviarSop.addEventListener("click", async () => {
      if (!confirm("Confirmar envio deste prontuário para o SOP?")) return;

      try {
        await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
          method: "POST",
          body: JSON.stringify({ destino: "sop", observacao: "Enviado pela Unidade de origem" }),
        });
        window.location.href = "/unidade";
      } catch (e) {
        alert(e.message);
      }
    });
  }
});

function acoesPendencia(p) {
  if (p.status === "aberta" || p.status === "em_analise") {
    return `<button class="btn btn-primario btn-sm" onclick="resolverPendencia(${p.id})">Resolver</button>`;
  }
  if (p.status === "resolvida") {
    const info = `<div class="texto-suave" style="margin-bottom:6px;">
      ${p.usuario_resolucao_nome || "-"} · ${formatarData(p.data_resolucao)}
    </div>`;
    if (USUARIO_PERFIL === "operador") return info;
    return `${info}
      <button class="btn btn-primario btn-sm" onclick="confirmarPendencia(${p.id})">Confirmar</button>
      <button class="btn btn-perigo btn-sm" onclick="devolverPendencia(${p.id})">Devolver</button>`;
  }
  // confirmada
  return `<span class="texto-suave">${p.usuario_resolucao_nome || "-"} · ${formatarData(p.data_resolucao)}</span>`;
}

async function carregarPendencias() {
  const tbody = document.getElementById("tbody-pendencias-analise");
  try {
    const lista = await apiFetch(`/api/pendencias?prontuario_id=${PRONTUARIO_ID}`);
    pendenciasAbertasCount = lista.filter(p => p.status !== "confirmada").length;
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

async function confirmarPendencia(id) {
  if (!confirm("Confirmar e finalizar esta pendência?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/confirmar`, { method: "POST" });
    carregarPendencias();
  } catch (e) {
    alert(e.message);
  }
}

async function devolverPendencia(id) {
  if (!confirm("Devolver esta pendência para a Unidade resolver novamente?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/devolver`, { method: "POST" });
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
