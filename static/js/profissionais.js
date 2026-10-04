/**
 * profissionais.js - CRUD simples de profissionais
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-novo-profissional").addEventListener("click", () => {
    document.getElementById("form-profissional").reset();
    document.getElementById("form-profissional").querySelector('[name="id"]').value = "";
    document.getElementById("titulo-modal-profissional").textContent = "Novo Profissional";
    abrirModal("modal-profissional");
  });

  document.getElementById("form-profissional").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;
    dados.ativo = true;
    if (dados.uf_conselho) dados.uf_conselho = dados.uf_conselho.toUpperCase();

    try {
      if (id) {
        await apiFetch(`/api/profissionais/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/profissionais", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-profissional");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const tbody = document.getElementById("tbody-profissionais");
  try {
    const lista = await apiFetch("/api/profissionais");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Nenhum profissional cadastrado.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.nome}</strong></td>
        <td>${p.categoria}</td>
        <td>${p.conselho ? `${p.conselho} ${p.numero_conselho || ""}${p.uf_conselho ? "/" + p.uf_conselho : ""}` : "-"}</td>
        <td>${[p.telefone, p.email].filter(Boolean).join(" · ") || "-"}</td>
        <td>${p.ativo ? '<span class="badge badge-ok">Ativo</span>' : '<span class="badge badge-pendencia">Inativo</span>'}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarProfissional(${JSON.stringify(p)})'>Editar</button>
          <button class="btn btn-perigo btn-sm" onclick="excluirProfissional(${p.id})">Desativar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function editarProfissional(profissional) {
  const form = document.getElementById("form-profissional");
  form.querySelector('[name="id"]').value = profissional.id;
  form.querySelector('[name="nome"]').value = profissional.nome || "";
  form.querySelector('[name="categoria"]').value = profissional.categoria || "";
  form.querySelector('[name="conselho"]').value = profissional.conselho || "";
  form.querySelector('[name="numero_conselho"]').value = profissional.numero_conselho || "";
  form.querySelector('[name="uf_conselho"]').value = profissional.uf_conselho || "";
  form.querySelector('[name="telefone"]').value = profissional.telefone || "";
  form.querySelector('[name="email"]').value = profissional.email || "";
  document.getElementById("titulo-modal-profissional").textContent = "Editar Profissional";
  abrirModal("modal-profissional");
}

async function excluirProfissional(id) {
  if (!confirm("Desativar este profissional?")) return;
  try {
    await apiFetch(`/api/profissionais/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
