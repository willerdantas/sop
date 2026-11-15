/**
 * procedimentos.js - CRUD simples do catalogo de procedimentos SIGTAP
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("filtro-busca").addEventListener("input", () => {
    clearTimeout(window._timerBuscaProcedimento);
    window._timerBuscaProcedimento = setTimeout(carregar, 350);
  });

  document.getElementById("btn-novo-procedimento").addEventListener("click", () => {
    const form = document.getElementById("form-procedimento");
    form.reset();
    form.querySelector('[name="id"]').value = "";
    document.getElementById("titulo-modal-procedimento").textContent = "Novo Procedimento";
    abrirModal("modal-procedimento");
  });

  document.getElementById("form-procedimento").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;
    dados.ativo = true;

    try {
      if (id) {
        await apiFetch(`/api/procedimentos-sigtap/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/procedimentos-sigtap", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-procedimento");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const busca = document.getElementById("filtro-busca").value.trim();
  const params = busca ? `?q=${encodeURIComponent(busca)}` : "";
  const tbody = document.getElementById("tbody-procedimentos");
  try {
    const lista = await apiFetch(`/api/procedimentos-sigtap${params}`);
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Nenhum procedimento cadastrado.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${esc(p.codigo)}</strong></td>
        <td>${esc(p.descricao)}</td>
        <td>${p.ativo ? '<span class="badge badge-ok">Ativo</span>' : '<span class="badge badge-pendencia">Inativo</span>'}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarProcedimento(${argJs(p)})'>Editar</button>
          ${p.ativo
            ? `<button class="btn btn-perigo btn-sm" onclick="excluirProcedimento(${esc(p.id)})">Desativar</button>`
            : `<button class="btn btn-primario btn-sm" onclick="ativarProcedimento(${esc(p.id)})">Ativar</button>`}
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function editarProcedimento(procedimento) {
  const form = document.getElementById("form-procedimento");
  form.querySelector('[name="id"]').value = procedimento.id;
  form.querySelector('[name="codigo"]').value = procedimento.codigo || "";
  form.querySelector('[name="descricao"]').value = procedimento.descricao || "";
  document.getElementById("titulo-modal-procedimento").textContent = "Editar Procedimento";
  abrirModal("modal-procedimento");
}

async function excluirProcedimento(id) {
  if (!confirm("Desativar este procedimento?")) return;
  try {
    await apiFetch(`/api/procedimentos-sigtap/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}

async function ativarProcedimento(id) {
  if (!confirm("Ativar este procedimento?")) return;
  try {
    await apiFetch(`/api/procedimentos-sigtap/${id}/ativar`, { method: "POST" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
