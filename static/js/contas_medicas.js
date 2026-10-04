/**
 * contas_medicas.js
 * Quatro secoes: aguardando confirmacao de entrega, em contas medicas
 * (ja confirmados), prontos para faturamento e em auditoria.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregarTudo();
});

function carregarTudo() {
  carregarAguardando();
  carregarContas();
  carregarFaturamento();
  carregarAuditoria();
}

async function carregarAguardando() {
  const tbody = document.getElementById("tbody-aguardando");
  const contador = document.getElementById("contador-aguardando");
  try {
    const lista = await apiFetch("/api/prontuarios?status=contas_medicas");
    const aguardando = lista.filter((p) => !p.recebido_contas_medicas_em);
    contador.textContent = `${aguardando.length} pendente(s)`;

    if (!aguardando.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum prontuário aguardando confirmação.</td></tr>`;
      return;
    }

    tbody.innerHTML = aguardando.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${p.pendencias_abertas > 0
            ? `<span class="badge badge-pendencia">${p.pendencias_abertas} aberta(s)</span>`
            : `<span class="badge badge-ok">Sem pendência</span>`}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td class="acoes-linha">
          <button class="btn btn-primario btn-sm" onclick="confirmarRecebimento(${p.id})">Confirmar Entrega</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function confirmarRecebimento(id) {
  if (!confirm("Confirmar que este prontuário foi entregue fisicamente?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/confirmar-recebimento`, { method: "POST" });
    carregarAguardando();
    carregarContas();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarContas() {
  const tbody = document.getElementById("tbody-contas");
  try {
    const lista = await apiFetch("/api/prontuarios?status=contas_medicas");
    const confirmados = lista.filter((p) => p.recebido_contas_medicas_em);

    if (!confirmados.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum prontuário confirmado em Contas Médicas.</td></tr>`;
      return;
    }

    tbody.innerHTML = confirmados.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${p.pendencias_abertas > 0
            ? `<span class="badge badge-pendencia">${p.pendencias_abertas} aberta(s)</span>`
            : `<span class="badge badge-ok">Sem pendência</span>`}</td>
        <td>${formatarData(p.recebido_contas_medicas_em)}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="location.href='/analise/${p.id}'">Analisar</button>
          <button class="btn btn-verde-agua btn-sm" onclick="devolverParaSOP(${p.id})">Devolver p/ SOP</button>
          <button class="btn btn-secundario btn-sm" ${p.pendencias_abertas > 0 ? "disabled title='Resolva as pendências primeiro'" : ""}
            onclick="marcarProntoFaturamento(${p.id}, ${p.pendencias_abertas})">
            Pronto p/ Faturamento
          </button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function devolverParaSOP(id) {
  if (!confirm("Confirmar devolução deste prontuário para o SOP?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "sop", observacao: "Devolvido pela equipe de Contas Médicas" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}

async function marcarProntoFaturamento(id, pendenciasAbertas) {
  if (pendenciasAbertas > 0) {
    alert("Prontuário com pendências não confirmadas não pode avançar.");
    return;
  }
  if (!confirm("Confirmar que este prontuário está pronto para faturamento?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "pronto_faturamento", observacao: "Marcado pronto p/ faturamento" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarFaturamento() {
  const tbody = document.getElementById("tbody-faturamento");
  try {
    const lista = await apiFetch("/api/prontuarios?status=pronto_faturamento");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhum prontuário pronto para faturamento.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="location.href='/analise/${p.id}'">Analisar</button>
          <button class="btn btn-primario btn-sm" onclick="enviarParaAuditoria(${p.id})">Enviar para Auditoria</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function enviarParaAuditoria(id) {
  if (!confirm("Confirmar envio deste prontuário para Auditoria?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "auditoria", observacao: "Enviado para auditoria" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarAuditoria() {
  const tbody = document.getElementById("tbody-auditoria");
  try {
    const lista = await apiFetch("/api/prontuarios?status=auditoria");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhum prontuário em auditoria.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="location.href='/analise/${p.id}'">Analisar</button>
          <button class="btn btn-primario btn-sm" onclick="finalizarProcesso(${p.id})">Finalizar Processo</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function finalizarProcesso(id) {
  if (!confirm("Confirmar finalização deste processo?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "finalizado", observacao: "Processo finalizado" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}
