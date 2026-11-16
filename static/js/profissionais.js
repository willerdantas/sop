/**
 * profissionais.js - consulta dos profissionais do sistema hospitalar
 * (t_profissional), somente leitura, com busca local.
 */

const LIMITE_LINHAS = 500;
let PROFISSIONAIS = [];

document.addEventListener("DOMContentLoaded", () => {
  carregar();
  document.getElementById("busca-profissional").addEventListener("input", renderizar);
});

async function carregar() {
  const tbody = document.getElementById("tbody-profissionais");
  try {
    PROFISSIONAIS = await apiFetch("/api/profissionais");
    renderizar();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function normalizar(texto) {
  return String(texto || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function renderizar() {
  const tbody = document.getElementById("tbody-profissionais");
  const termo = normalizar(document.getElementById("busca-profissional").value.trim());
  const filtrados = termo
    ? PROFISSIONAIS.filter((p) => normalizar(`${p.nome} ${p.conselho || ""} ${p.numero_conselho || ""}`).includes(termo))
    : PROFISSIONAIS;
  document.getElementById("total-profissionais").textContent = filtrados.length;

  if (!filtrados.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Nenhum profissional encontrado.</td></tr>`;
    return;
  }
  const linhas = filtrados.slice(0, LIMITE_LINHAS).map((p) => `
    <tr>
      <td>${esc(p.isn_profissional ?? "-")}</td>
      <td><strong>${esc(p.nome)}</strong></td>
      <td>${esc(p.conselho || "-")}</td>
      <td>${esc(p.numero_conselho || "-")}</td>
    </tr>
  `).join("");
  const aviso = filtrados.length > LIMITE_LINHAS
    ? `<tr><td colspan="4" class="vazio-estado">Mostrando ${LIMITE_LINHAS} de ${filtrados.length}. Use a busca para refinar.</td></tr>`
    : "";
  tbody.innerHTML = linhas + aviso;
}
