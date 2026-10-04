/**
 * perfis.js - CRUD de perfis de acesso (quais paginas cada perfil pode ver)
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-novo-perfil").addEventListener("click", () => {
    const form = document.getElementById("form-perfil");
    form.reset();
    form.querySelector('[name="id"]').value = "";
    form.querySelector('[name="nome"]').disabled = false;
    document.getElementById("aviso-nome-fixo").style.display = "none";
    document.getElementById("campo-ativo-perfil").style.display = "none";
    document.getElementById("titulo-modal-perfil").textContent = "Novo Perfil";
    abrirModal("modal-perfil");
  });

  document.getElementById("form-perfil").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const id = form.querySelector('[name="id"]').value;
    const paginas = Array.from(form.querySelectorAll('input[name="paginas"]:checked')).map((el) => el.value);

    try {
      if (id) {
        const ativo = form.querySelector('[name="ativo"]').checked;
        await apiFetch(`/api/perfis/${id}`, { method: "PUT", body: JSON.stringify({ paginas, ativo }) });
      } else {
        const nome = form.querySelector('[name="nome"]').value.trim();
        await apiFetch("/api/perfis", { method: "POST", body: JSON.stringify({ nome, paginas }) });
      }
      fecharModal("modal-perfil");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const tbody = document.getElementById("tbody-perfis");
  try {
    const lista = await apiFetch("/api/perfis");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Nenhum perfil cadastrado.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.nome}</strong>${p.protegido ? ' <span class="badge badge-unidade">Protegido</span>' : ""}</td>
        <td>${p.paginas.length ? p.paginas.join(", ") : '<span class="texto-suave">nenhuma</span>'}</td>
        <td>${p.ativo ? '<span class="badge badge-ok">Ativo</span>' : '<span class="badge badge-pendencia">Inativo</span>'}</td>
        <td class="acoes-linha">
          ${p.protegido ? "" : `
            <button class="btn btn-outline btn-sm" onclick='editarPerfil(${JSON.stringify(p)})'>Editar</button>
            <button class="btn btn-perigo btn-sm" onclick="alternarPerfil(${p.id})">${p.ativo ? "Desativar" : "Reativar"}</button>
          `}
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function editarPerfil(perfil) {
  const form = document.getElementById("form-perfil");
  form.reset();
  form.querySelector('[name="id"]').value = perfil.id;
  form.querySelector('[name="nome"]').value = perfil.nome;
  form.querySelector('[name="nome"]').disabled = true;
  document.getElementById("aviso-nome-fixo").style.display = "block";

  form.querySelectorAll('input[name="paginas"]').forEach((el) => {
    el.checked = perfil.paginas.includes(el.value);
  });

  document.getElementById("campo-ativo-perfil").style.display = "block";
  form.querySelector('[name="ativo"]').checked = perfil.ativo;

  document.getElementById("titulo-modal-perfil").textContent = "Editar Perfil";
  abrirModal("modal-perfil");
}

async function alternarPerfil(id) {
  if (!confirm("Confirmar alteração de status deste perfil?")) return;
  try {
    await apiFetch(`/api/perfis/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
