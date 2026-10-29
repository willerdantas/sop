/**
 * analise_c_medicas.js
 * Pagina de analise de um prontuario a partir de Contas Medicas: registra
 * pendencias, confirma/devolve pendencias resolvidas pela Unidade e permite
 * devolver o prontuario para o SOP.
 */

let pendenciasAbertasCount = 0;

let procedimentoSelecionadoId = null;

document.addEventListener("DOMContentLoaded", () => {
  carregarPendencias();
  carregarHistorico();
  carregarProcedimentos();
  configurarBuscaProfissional();

  document.getElementById("btn-nova-pendencia").addEventListener("click", () => {
    limparBuscaProfissional();
    abrirModal("modal-nova-pendencia");
  });

  document.getElementById("form-nova-pendencia").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!document.getElementById("input-profissional-selecionado").value) {
      alert("Selecione um profissional cadastrado na lista de resultados.");
      return;
    }
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    dados.prontuario_id = PRONTUARIO_ID;

    try {
      await apiFetch("/api/pendencias", { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-nova-pendencia");
      form.reset();
      limparBuscaProfissional();
      carregarPendencias();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("btn-enviar-sop").addEventListener("click", async () => {
    if (!confirm("Confirmar envio deste prontuário para o SOP?")) return;

    try {
      await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
        method: "POST",
        body: JSON.stringify({ destino: "sop", observacao: "Devolvido pela equipe de Contas Médicas" }),
      });
      window.location.href = "/contas-medicas";
    } catch (e) {
      alert(e.message);
    }
  });

  const btnEnviarAuditoria = document.getElementById("btn-enviar-auditoria");
  if (btnEnviarAuditoria) {
    btnEnviarAuditoria.addEventListener("click", async () => {
      if (!confirm("Confirmar envio deste prontuário para Auditoria?")) return;

      try {
        await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
          method: "POST",
          body: JSON.stringify({ destino: "auditoria", observacao: "Enviado para auditoria" }),
        });
        window.location.href = "/contas-medicas";
      } catch (e) {
        alert(e.message);
      }
    });
  }

  const btnProntuarioFaturado = document.getElementById("btn-prontuario-faturado");
  if (btnProntuarioFaturado) {
    btnProntuarioFaturado.addEventListener("click", async () => {
      if (!confirm("Confirmar que este prontuário foi faturado? Isso finaliza o processo.")) return;

      try {
        await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
          method: "POST",
          body: JSON.stringify({ destino: "finalizado", observacao: "Prontuário faturado" }),
        });
        window.location.href = "/contas-medicas";
      } catch (e) {
        alert(e.message);
      }
    });
  }

  const btnEnviarFaturamento = document.getElementById("btn-enviar-faturamento");
  if (btnEnviarFaturamento) {
    btnEnviarFaturamento.addEventListener("click", async () => {
      if (!confirm("Confirmar envio deste prontuário de volta para o Faturamento?")) return;

      try {
        await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/mover`, {
          method: "POST",
          body: JSON.stringify({ destino: "pronto_faturamento", observacao: "Devolvido pela Auditoria para o Faturamento" }),
        });
        window.location.href = "/contas-medicas";
      } catch (e) {
        alert(e.message);
      }
    });
  }

  document.getElementById("btn-salvar-valores-faturamento").addEventListener("click", async () => {
    const dados = {
      dias_enfermaria: document.getElementById("input-dias-enfermaria").value,
      dias_uti: document.getElementById("input-dias-uti").value,
      diaria_acompanhante: document.getElementById("input-diaria-acompanhante").value,
    };

    try {
      await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/valores-faturamento`, {
        method: "PUT",
        body: JSON.stringify(dados),
      });
      alert("Valores salvos.");
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("btn-incluir-procedimento").addEventListener("click", () => {
    document.getElementById("form-incluir-procedimento").reset();
    document.getElementById("input-procedimento-id").value = "";
    document.getElementById("resultados-procedimento").innerHTML = "";
    procedimentoSelecionadoId = null;
    abrirModal("modal-incluir-procedimento");
  });

  let timerBuscaProcedimento;
  document.getElementById("input-busca-procedimento").addEventListener("input", () => {
    procedimentoSelecionadoId = null;
    document.getElementById("input-procedimento-id").value = "";
    clearTimeout(timerBuscaProcedimento);
    const valor = document.getElementById("input-busca-procedimento").value.trim();
    const resultados = document.getElementById("resultados-procedimento");
    if (!valor) {
      resultados.innerHTML = "";
      return;
    }
    timerBuscaProcedimento = setTimeout(async () => {
      try {
        const lista = await apiFetch(`/api/procedimentos-sigtap?q=${encodeURIComponent(valor)}`);
        const ativos = lista.filter((p) => p.ativo);
        if (!ativos.length) {
          resultados.innerHTML = `<div>Nenhum procedimento encontrado.</div>`;
          return;
        }
        resultados.innerHTML = ativos.map((p) => `
          <div style="padding:6px 0; cursor:pointer; border-bottom:1px solid var(--cor-borda);"
               onclick="selecionarProcedimento(${p.id}, ${JSON.stringify(p.codigo)}, ${JSON.stringify(p.descricao)})">
            <strong>${p.codigo}</strong> · ${p.descricao}
          </div>
        `).join("");
      } catch (e) {
        resultados.innerHTML = `<div>Erro ao buscar: ${e.message}</div>`;
      }
    }, 300);
  });

  document.getElementById("form-incluir-procedimento").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!procedimentoSelecionadoId) {
      alert("Selecione um procedimento na lista de resultados.");
      return;
    }
    try {
      await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/procedimentos`, {
        method: "POST",
        body: JSON.stringify({
          procedimento_id: procedimentoSelecionadoId,
          quantidade: document.getElementById("input-quantidade-procedimento").value || 1,
        }),
      });
      fecharModal("modal-incluir-procedimento");
      carregarProcedimentos();
    } catch (e) {
      alert(e.message);
    }
  });
});

function selecionarProcedimento(id, codigo, descricao) {
  procedimentoSelecionadoId = id;
  document.getElementById("input-procedimento-id").value = id;
  document.getElementById("input-busca-procedimento").value = `${codigo} - ${descricao}`;
  document.getElementById("resultados-procedimento").innerHTML = "";
}

async function carregarProcedimentos() {
  const tbody = document.getElementById("tbody-procedimentos-analise");
  try {
    const lista = await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/procedimentos`);
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum procedimento incluído.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.codigo}</strong></td>
        <td>${p.descricao}</td>
        <td>${p.quantidade}</td>
        <td>${formatarData(p.criado_em)}</td>
        <td>${p.usuario_nome || "-"}</td>
        <td class="acoes-linha">
          <button class="btn btn-perigo btn-sm" onclick="excluirProcedimentoProntuario(${p.id})">Excluir</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function excluirProcedimentoProntuario(itemId) {
  if (!confirm("Excluir este procedimento do prontuário?")) return;
  try {
    await apiFetch(`/api/prontuarios/${PRONTUARIO_ID}/procedimentos/${itemId}`, { method: "DELETE" });
    carregarProcedimentos();
  } catch (e) {
    alert(e.message);
  }
}

function acoesPendencia(p) {
  if (p.status === "aberta" || p.status === "em_analise") {
    return `<button class="btn btn-primario btn-sm" onclick="resolverPendencia(${p.id})">Resolver</button>`;
  }
  if (p.status === "resolvida") {
    const info = `<div class="texto-suave" style="margin-bottom:6px;">
      ${p.usuario_resolucao_nome || "-"} · ${formatarData(p.data_resolucao)}
    </div>`;
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
