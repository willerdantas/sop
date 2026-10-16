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
  carregarFaturados();
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
      tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Nenhum prontuário confirmado em Contas Médicas.</td></tr>`;
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
        <td>${p.recebido_contas_medicas_usuario_nome || "-"}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="analisarEMigrarFaturamento(${p.id})">Analisar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function analisarEMigrarFaturamento(id) {
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "pronto_faturamento", observacao: "Movido para faturamento ao analisar" }),
    });
  } catch (e) {
    // Pendencias em aberto ou outro bloqueio: segue para a analise mesmo assim.
  }
  window.location.href = `/analise_c_medicas/${id}`;
}

async function carregarFaturamento() {
  const tbody = document.getElementById("tbody-faturamento");
  try {
    const lista = await apiFetch("/api/prontuarios?status=pronto_faturamento");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum prontuário pronto para faturamento.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td>${p.faturamento_usuario_nome || "-"}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="location.href='/analise_c_medicas/${p.id}'">Analisar</button>
          <button class="btn btn-verde-agua btn-sm" onclick="devolverParaSOP(${p.id})">Devolver p/ SOP</button>
          <button class="btn btn-primario btn-sm" onclick="enviarParaAuditoria(${p.id})">Enviar para Auditoria</button>
          <button class="btn btn-secundario btn-sm" onclick="prontuarioFaturado(${p.id})">Prontuário Faturado</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function prontuarioFaturado(id) {
  if (!confirm("Confirmar que este prontuário foi faturado? Isso finaliza o processo.")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "finalizado", observacao: "Prontuário faturado" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}

async function carregarFaturados() {
  const tbody = document.getElementById("tbody-faturados");
  try {
    const lista = await apiFetch("/api/prontuarios?status=finalizado");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhum prontuário faturado ainda.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td>${p.finalizado_usuario_nome || "-"}</td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
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
      tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Nenhum prontuário em auditoria.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.numero_prontuario}</strong></td>
        <td>${p.paciente_nome}</td>
        <td>${p.unidade_nome || "-"}</td>
        <td>${formatarData(p.atualizado_em)}</td>
        <td>${p.auditoria_analisado_em ? formatarData(p.auditoria_analisado_em) : "-"}</td>
        <td>${p.auditoria_analisado_usuario_nome || "-"}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick="analisarAuditoria(${p.id})">Analisar</button>
          <button class="btn btn-primario btn-sm" onclick="enviarParaFaturamento(${p.id})">Enviar para Faturamento</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function analisarAuditoria(id) {
  try {
    await apiFetch(`/api/prontuarios/${id}/registrar-analise-auditoria`, { method: "POST" });
  } catch (e) {
    // Nao bloqueia a navegacao se o registro falhar.
  }
  window.location.href = `/analise_c_medicas/${id}`;
}

async function enviarParaFaturamento(id) {
  if (!confirm("Confirmar envio deste prontuário de volta para o Faturamento?")) return;
  try {
    await apiFetch(`/api/prontuarios/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ destino: "pronto_faturamento", observacao: "Devolvido pela Auditoria para o Faturamento" }),
    });
    carregarTudo();
  } catch (e) {
    alert(e.message);
  }
}
