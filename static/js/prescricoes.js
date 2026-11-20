/**
 * prescricoes.js - catalogo local de itens de prescricao (ver prescricoes.html),
 * sincronizado a partir de t_prescricao_pep_item.dsc_prescricao (sistema
 * hospitalar, sem indexacao propria) e com edicao de codigo/faturamento.
 */

document.addEventListener("DOMContentLoaded", () => {
  carregar();

  document.getElementById("filtro-busca").addEventListener("input", () => {
    clearTimeout(window._timerBuscaItemPrescricao);
    window._timerBuscaItemPrescricao = setTimeout(carregar, 350);
  });

  document.getElementById("btn-sincronizar-itens-prescricao").addEventListener("click", async (ev) => {
    const botao = ev.currentTarget;
    botao.disabled = true;
    const textoOriginal = botao.textContent;
    botao.textContent = "Sincronizando...";
    try {
      const resultado = await apiFetch("/api/itens-prescricao/sincronizar", { method: "POST" });
      let mensagem = `Sincronização concluída: ${resultado.novos} item(ns) novo(s) de ${resultado.lidos} lido(s).`;
      if (resultado.ignorados) mensagem += ` ${resultado.ignorados} item(ns) ignorado(s) por erro.`;
      alert(mensagem);
      carregar();
    } catch (e) {
      alert(e.message);
    } finally {
      botao.disabled = false;
      botao.textContent = textoOriginal;
    }
  });

  document.getElementById("form-item-prescricao").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const id = form.querySelector('[name="id"]').value;
    const dados = {
      codigo: form.querySelector('[name="codigo"]').value,
      faturamento: form.querySelector('[name="faturamento"]').checked,
    };

    try {
      await apiFetch(`/api/itens-prescricao/${id}`, { method: "PUT", body: JSON.stringify(dados) });
      fecharModal("modal-item-prescricao");
      carregar();
    } catch (e) {
      alert(e.message);
    }
  });
});

async function carregar() {
  const busca = document.getElementById("filtro-busca").value.trim();
  const params = busca ? `?q=${encodeURIComponent(busca)}` : "";
  const tbody = document.getElementById("tbody-itens-prescricao");
  try {
    const lista = await apiFetch(`/api/itens-prescricao${params}`);
    if (!lista.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Nenhum item cadastrado. Clique em "Sincronizar com Sistema Hospitalar".</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((item) => `
      <tr>
        <td>${esc(item.dsc_prescricao)}</td>
        <td>${esc(item.codigo || "-")}</td>
        <td>${item.faturamento ? '<span class="badge badge-ok">Sim</span>' : "Não"}</td>
        <td class="acoes-linha">
          <button class="btn btn-outline btn-sm" onclick='editarItemPrescricao(${argJs(item)})'>Editar</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="vazio-estado">Erro ao carregar: ${esc(e.message)}</td></tr>`;
  }
}

function editarItemPrescricao(item) {
  const form = document.getElementById("form-item-prescricao");
  form.querySelector('[name="id"]').value = item.id;
  form.querySelector('[name="codigo"]').value = item.codigo || "";
  form.querySelector('[name="faturamento"]').checked = !!item.faturamento;
  document.getElementById("item-prescricao-descricao").value = item.dsc_prescricao;
  abrirModal("modal-item-prescricao");
}
