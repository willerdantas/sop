/**
 * clinicas.js - CRUD simples de clinicas locais (tabela 'unidades')
 * Complementam as clinicas do sistema hospitalar (ISIVITA) nas telas
 * de cadastro de pendencias.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("btn-nova-clinica-local").addEventListener("click", () => {
    const form = document.getElementById("form-clinica-local");
    form.reset();
    form.querySelector('[name="id"]').value = "";
    document.getElementById("titulo-modal-clinica-local").textContent = "Nova Clínica Local";
    abrirModal("modal-clinica-local");
  });

  document.getElementById("form-clinica-local").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;

    try {
      if (id) {
        await apiFetch(`/api/unidades-locais/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/unidades-locais", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-clinica-local");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("form-tipo-clinica").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const isn = form.querySelector('[name="isn_clinica"]').value;
    const tipo = form.querySelector('[name="tipo"]').value;

    try {
      await apiFetch(`/api/clinicas/${isn}/tipo`, { method: "PUT", body: JSON.stringify({ tipo }) });
      fecharModal("modal-tipo-clinica");
      window.location.reload();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("btn-novo-tipo-diaria").addEventListener("click", () => {
    const form = document.getElementById("form-tipo-diaria");
    form.reset();
    form.querySelector('[name="id"]').value = "";
    document.getElementById("titulo-modal-tipo-diaria").textContent = "Novo Tipo de Diária";
    abrirModal("modal-tipo-diaria");
  });

  document.getElementById("form-tipo-diaria").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const dados = Object.fromEntries(new FormData(form).entries());
    const id = dados.id;
    delete dados.id;
    dados.acompanhante = form.querySelector('[name="acompanhante"]').checked;

    try {
      if (id) {
        await apiFetch(`/api/tipos-diaria-clinica/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      } else {
        await apiFetch("/api/tipos-diaria-clinica", { method: "POST", body: JSON.stringify(dados) });
      }
      fecharModal("modal-tipo-diaria");
      window.location.reload();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("form-tipo-diaria-clinica").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const isn = form.querySelector('[name="isn_clinica"]').value;
    const tipoDiariaId = form.querySelector('[name="tipo_diaria_id"]').value;

    try {
      await apiFetch(`/api/clinicas/${isn}/tipo-diaria`, {
        method: "PUT",
        body: JSON.stringify({ tipo_diaria_id: tipoDiariaId }),
      });
      fecharModal("modal-tipo-diaria-clinica");
      window.location.reload();
    } catch (e) {
      alert(e.message);
    }
  });
});

function editarTipoClinica(isnClinica, nome, tipoAtual) {
  const form = document.getElementById("form-tipo-clinica");
  form.querySelector('[name="isn_clinica"]').value = isnClinica;
  form.querySelector('[name="tipo"]').value = tipoAtual || "";
  document.getElementById("tipo-clinica-nome").value = nome;
  abrirModal("modal-tipo-clinica");
}

function editarTipoDiaria(tipo) {
  const form = document.getElementById("form-tipo-diaria");
  form.reset();
  form.querySelector('[name="id"]').value = tipo.id;
  form.querySelector('[name="nome"]').value = tipo.nome || "";
  form.querySelector('[name="acompanhante"]').checked = !!tipo.acompanhante;
  document.getElementById("titulo-modal-tipo-diaria").textContent = "Editar Tipo de Diária";
  abrirModal("modal-tipo-diaria");
}

async function excluirTipoDiaria(id) {
  if (!confirm("Excluir este tipo de diária? Clínicas vinculadas deixarão de contar automaticamente.")) return;
  try {
    await apiFetch(`/api/tipos-diaria-clinica/${id}`, { method: "DELETE" });
    window.location.reload();
  } catch (e) {
    alert(e.message);
  }
}

function editarTipoDiariaClinica(isnClinica, nome, tipoDiariaIdAtual) {
  const form = document.getElementById("form-tipo-diaria-clinica");
  form.querySelector('[name="isn_clinica"]').value = isnClinica;
  form.querySelector('[name="tipo_diaria_id"]').value = tipoDiariaIdAtual || "";
  document.getElementById("tipo-diaria-clinica-nome").value = nome;
  abrirModal("modal-tipo-diaria-clinica");
}

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
        <td><strong>${esc(u.nome)}</strong></td>
        <td>${esc(u.codigo || "-")}</td>
        <td>${esc(u.tipo || "-")}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarClinicaLocal(${argJs(u)})'>Editar</button>
          <button class="btn btn-perigo btn-sm" onclick="excluirClinicaLocal(${esc(u.id)})">Desativar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function editarClinicaLocal(clinica) {
  const form = document.getElementById("form-clinica-local");
  form.querySelector('[name="id"]').value = clinica.id;
  form.querySelector('[name="nome"]').value = clinica.nome || "";
  form.querySelector('[name="tipo"]').value = clinica.tipo || "";
  document.getElementById("titulo-modal-clinica-local").textContent = "Editar Clínica Local";
  abrirModal("modal-clinica-local");
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
