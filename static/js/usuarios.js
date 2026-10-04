/**
 * usuarios.js - Criacao e gestao de usuarios do sistema
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-novo-usuario").addEventListener("click", () => {
    const form = document.getElementById("form-usuario");
    form.reset();
    form.querySelector('[name="id"]').value = "";
    document.getElementById("input-senha-usuario").required = true;
    document.getElementById("input-senha-usuario").placeholder = "Mínimo 6 caracteres";
    document.getElementById("rotulo-senha-obrig").textContent = "*";
    document.getElementById("input-login-usuario").disabled = false;
    document.getElementById("titulo-modal-usuario").textContent = "Novo Usuário";
    abrirModal("modal-usuario");
  });

  document.getElementById("form-usuario").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;
    dados.ativo = true;
    if (!dados.unidade_id) dados.unidade_id = null;
    if (id && !dados.senha) delete dados.senha;

    try {
      if (id) {
        await apiFetch(`/api/usuarios/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/usuarios", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-usuario");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const tbody = document.getElementById("tbody-usuarios");
  try {
    const lista = await apiFetch("/api/usuarios");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Nenhum usuário cadastrado.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((u) => `
      <tr>
        <td><strong>${u.nome}</strong></td>
        <td>${u.login}</td>
        <td>${u.email || "-"}</td>
        <td>${rotuloPerfil(u.perfil)}</td>
        <td>${u.ativo ? '<span class="badge badge-ok">Ativo</span>' : '<span class="badge badge-pendencia">Inativo</span>'}</td>
        <td>${u.ultimo_login ? formatarData(u.ultimo_login) : "Nunca acessou"}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarUsuario(${JSON.stringify(u)})'>Editar</button>
          <button class="btn btn-perigo btn-sm" onclick="excluirUsuario(${u.id})">Desativar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

function rotuloPerfil(perfil) {
  const mapa = {
    admin: "Administrador", sop: "SOP",
    contas_medicas: "Contas Médicas", operador: "Operador",
  };
  return mapa[perfil] || perfil;
}

function editarUsuario(usuario) {
  const form = document.getElementById("form-usuario");
  form.querySelector('[name="id"]').value = usuario.id;
  form.querySelector('[name="nome"]').value = usuario.nome || "";
  form.querySelector('[name="login"]').value = usuario.login || "";
  form.querySelector('[name="email"]').value = usuario.email || "";
  form.querySelector('[name="perfil"]').value = usuario.perfil || "operador";
  form.querySelector('[name="unidade_id"]').value = usuario.unidade_id || "";

  document.getElementById("input-senha-usuario").value = "";
  document.getElementById("input-senha-usuario").required = false;
  document.getElementById("input-senha-usuario").placeholder = "Deixe em branco para manter a atual";
  document.getElementById("rotulo-senha-obrig").textContent = "";
  document.getElementById("input-login-usuario").disabled = true;

  document.getElementById("titulo-modal-usuario").textContent = "Editar Usuário";
  abrirModal("modal-usuario");
}

async function excluirUsuario(id) {
  if (!confirm("Desativar este usuário?")) return;
  try {
    await apiFetch(`/api/usuarios/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
