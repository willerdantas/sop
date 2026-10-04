/**
 * pendencias.js
 * Lista, cadastra e resolve pendencias/inconsistencias vinculadas
 * a um prontuario (por numero, resolvido para o id internamente).
 */

let prontuarioEncontradoId = null;

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("filtro-status").addEventListener("change", carregar);
  document.getElementById("btn-nova-pendencia").addEventListener("click", () => abrirModal("modal-nova-pendencia"));

  const inputNumero = document.getElementById("input-numero-prontuario");
  const statusBusca = document.getElementById("status-busca-prontuario");
  let timerBuscaProntuario;

  inputNumero.addEventListener("input", () => {
    prontuarioEncontradoId = null;
    statusBusca.textContent = "";
    clearTimeout(timerBuscaProntuario);
    const valor = inputNumero.value.trim();
    if (!valor) return;

    timerBuscaProntuario = setTimeout(async () => {
      try {
        const resultados = await apiFetch(`/api/prontuarios?q=${encodeURIComponent(valor)}`);
        const exato = resultados.find(p => p.numero_prontuario.toLowerCase() === valor.toLowerCase());
        if (exato) {
          prontuarioEncontradoId = exato.id;
          statusBusca.textContent = `✓ Encontrado: ${exato.paciente_nome} (${statusLabelLocal(exato.status_atual)})`;
          statusBusca.style.color = "var(--cor-teal-var)";
        } else {
          statusBusca.textContent = "Prontuário não encontrado. Verifique o número.";
          statusBusca.style.color = "var(--cor-laranja)";
        }
      } catch (e) {
        statusBusca.textContent = "Erro ao buscar prontuário.";
      }
    }, 400);
  });

  document.getElementById("form-nova-pendencia").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!prontuarioEncontradoId) {
      alert("Informe um número de prontuário válido (encontrado na busca) antes de salvar.");
      return;
    }
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    delete dados.numero_prontuario;
    dados.prontuario_id = prontuarioEncontradoId;

    try {
      await apiFetch("/api/pendencias", { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-nova-pendencia");
      form.reset();
      document.getElementById("status-busca-prontuario").textContent = "";
      prontuarioEncontradoId = null;
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

function statusLabelLocal(status) {
  return STATUS_LABEL_JS[status] || status;
}

async function carregar() {
  const status = document.getElementById("filtro-status").value;
  const params = status ? new URLSearchParams({ status }) : new URLSearchParams();
  const tbody = document.getElementById("tbody-pendencias");

  try {
    const lista = await apiFetch(`/api/pendencias?${params.toString()}`);
    document.getElementById("kpi-total").textContent = lista.length;
    renderizar(lista);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="12" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
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
  return `<span class="texto-suave">${p.usuario_resolucao_nome || "-"} · ${formatarData(p.data_resolucao)}</span>`;
}

function renderizar(lista) {
  const tbody = document.getElementById("tbody-pendencias");
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="12" class="vazio-estado">Nenhuma pendência encontrada.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((p) => `
    <tr>
      <td><strong>${p.numero_prontuario}</strong></td>
      <td>${p.paciente_nome}</td>
      <td>${p.tipo_descricao || "-"}</td>
      <td>${p.unidade_nome || "-"}</td>
      <td>${p.profissional || "-"}</td>
      <td>${formatarDataSimples(p.data_ocorrencia)}</td>
      <td>${badgeCriticidade(p.criticidade)}</td>
      <td style="max-width:260px;">${p.descricao}</td>
      <td>${badgeStatusPendencia(p.status)}</td>
      <td>${formatarData(p.data_abertura)}</td>
      <td>${formatarTimerHorasUteis(p.horas_uteis_desde_abertura)}</td>
      <td class="acoes-linha">${acoesPendencia(p)}</td>
    </tr>
  `).join("");
}

async function resolverPendencia(id) {
  if (!confirm("Confirmar resolução desta pendência?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/resolver`, { method: "POST" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}

async function confirmarPendencia(id) {
  if (!confirm("Confirmar e finalizar esta pendência?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/confirmar`, { method: "POST" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}

async function devolverPendencia(id) {
  if (!confirm("Devolver esta pendência para a Unidade resolver novamente?")) return;
  try {
    await apiFetch(`/api/pendencias/${id}/devolver`, { method: "POST" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
