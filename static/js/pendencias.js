/**
 * pendencias.js - CRUD simples de tipos de pendencia (catalogo)
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-novo-tipo-pendencia").addEventListener("click", () => {
    document.getElementById("form-tipo-pendencia").reset();
    document.getElementById("form-tipo-pendencia").querySelector('[name="id"]').value = "";
    document.getElementById("titulo-modal-tipo-pendencia").textContent = "Novo Tipo de Pendência";
    abrirModal("modal-tipo-pendencia");
  });

  document.getElementById("form-tipo-pendencia").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;
    dados.ativo = true;

    try {
      if (id) {
        await apiFetch(`/api/tipos-pendencia/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/tipos-pendencia", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-tipo-pendencia");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const tbody = document.getElementById("tbody-tipos-pendencia");
  try {
    const lista = await apiFetch("/api/tipos-pendencia");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhum tipo de pendência cadastrado.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((t) => `
      <tr>
        <td><strong>${esc(t.descricao)}</strong></td>
        <td>${esc(t.setor_responsavel || "-")}</td>
        <td>${badgeCriticidade(t.criticidade)}</td>
        <td>${t.ativo ? '<span class="badge badge-ok">Ativo</span>' : '<span class="badge badge-pendencia">Inativo</span>'}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarTipoPendencia(${argJs(t)})'>Editar</button>
          ${t.ativo
            ? `<button class="btn btn-perigo btn-sm" onclick="excluirTipoPendencia(${esc(t.id)})">Desativar</button>`
            : `<button class="btn btn-primario btn-sm" onclick="ativarTipoPendencia(${esc(t.id)})">Ativar</button>`}
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function editarTipoPendencia(tipo) {
  const form = document.getElementById("form-tipo-pendencia");
  form.querySelector('[name="id"]').value = tipo.id;
  form.querySelector('[name="descricao"]').value = tipo.descricao || "";
  form.querySelector('[name="setor_responsavel"]').value = tipo.setor_responsavel || "";
  form.querySelector('[name="criticidade"]').value = tipo.criticidade || "media";
  document.getElementById("titulo-modal-tipo-pendencia").textContent = "Editar Tipo de Pendência";
  abrirModal("modal-tipo-pendencia");
}

async function excluirTipoPendencia(id) {
  if (!confirm("Desativar este tipo de pendência?")) return;
  try {
    await apiFetch(`/api/tipos-pendencia/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}

async function ativarTipoPendencia(id) {
  if (!confirm("Ativar este tipo de pendência?")) return;
  try {
    await apiFetch(`/api/tipos-pendencia/${id}/ativar`, { method: "POST" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
