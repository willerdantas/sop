/**
 * clinicas.js - CRUD simples de clinicas locais (tabela 'unidades')
 * Complementam as clinicas do sistema hospitalar (ISIVITA) nas telas
 * de cadastro de pendencias.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-nova-clinica-local").addEventListener("click", () => {
    document.getElementById("form-clinica-local").reset();
    abrirModal("modal-clinica-local");
  });

  document.getElementById("form-clinica-local").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());

    try {
      await apiFetch("/api/unidades-locais", { method: "POST", body: JSON.stringify(dados) });
      fecharModal("modal-clinica-local");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const tbody = document.getElementById("tbody-clinicas-locais");
  try {
    const lista = await apiFetch("/api/unidades-locais");
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Nenhuma clínica local cadastrada.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((u) => `
      <tr>
        <td><strong>${u.nome}</strong></td>
        <td>${u.codigo || "-"}</td>
        <td>${u.tipo || "-"}</td>
        <td class="acoes-linha">
          <button class="btn btn-perigo btn-sm" onclick="excluirClinicaLocal(${u.id})">Desativar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${e.message}</td></tr>`;
  }
}

async function excluirClinicaLocal(id) {
  if (!confirm("Desativar esta clínica local?")) return;
  try {
    await apiFetch(`/api/unidades-locais/${id}`, { method: "DELETE" });
    carregar();
  } catch (e) {
    alert(e.message);
  }
}
