/**
 * main.js
 * - Controla a sidebar recolhivel (expande ao clicar, some os labels quando recolhida)
 * - Controla o overlay de carregamento com a logo, exibido na transicao entre paginas
 * - Utilitarios de fetch/JSON usados pelas paginas do sistema
 */

document.addEventListener("DOMContentLoaded", () => {
  initSidebar();
  initPageTransition();
  initUserMenu();
  initModals();
});

/* ---------------------------------------------------------
 * MODAIS GENERICOS
 * --------------------------------------------------------- */
function initModals() {
  document.querySelectorAll("[data-fechar-modal]").forEach((el) => {
    el.addEventListener("click", () => {
      fecharModal(el.getAttribute("data-fechar-modal"));
    });
  });
  document.querySelectorAll(".modal-fundo").forEach((fundo) => {
    fundo.addEventListener("click", (ev) => {
      if (ev.target === fundo) fundo.classList.remove("aberto");
    });
  });
}

function abrirModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("aberto");
}

function fecharModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("aberto");
}

/* ---------------------------------------------------------
 * SIDEBAR
 * --------------------------------------------------------- */
function initSidebar() {
  const sidebar = document.querySelector(".sidebar");
  const toggleBtn = document.querySelector(".sidebar-toggle");
  if (!sidebar || !toggleBtn) return;

  // Restaura preferencia salva
  const salvo = localStorage.getItem("sidebar-expandida");
  if (salvo === "true") sidebar.classList.add("expandida");

  toggleBtn.addEventListener("click", () => {
    sidebar.classList.toggle("expandida");
    localStorage.setItem("sidebar-expandida", sidebar.classList.contains("expandida"));
  });
}

/* ---------------------------------------------------------
 * TRANSICAO ENTRE PAGINAS (overlay com logo)
 * --------------------------------------------------------- */
function initPageTransition() {
  const overlay = document.getElementById("loading-overlay");
  if (!overlay) return;

  // Ao carregar a pagina, esconde o overlay suavemente (com um pequeno
  // atraso minimo para a animacao nao "piscar" em conexoes rapidas).
  window.addEventListener("load", () => {
    setTimeout(() => overlay.classList.add("hidden"), 280);
  });

  // Intercepta cliques em links internos de navegacao para mostrar
  // o overlay antes de trocar de pagina.
  document.querySelectorAll("a[data-nav]").forEach((link) => {
    link.addEventListener("click", (ev) => {
      const href = link.getAttribute("href");
      if (!href || href.startsWith("#") || link.target === "_blank") return;

      ev.preventDefault();
      overlay.classList.remove("hidden");
      setTimeout(() => {
        window.location.href = href;
      }, 320);
    });
  });

  // Formularios tambem podem disparar o overlay (ex: login, salvar e voltar)
  document.querySelectorAll("form[data-nav-loading]").forEach((form) => {
    form.addEventListener("submit", () => {
      overlay.classList.remove("hidden");
    });
  });
}

function mostrarOverlayCarregamento() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.remove("hidden");
}

function esconderOverlayCarregamento() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.add("hidden");
}

/* ---------------------------------------------------------
 * MENU DE USUARIO (logout)
 * --------------------------------------------------------- */
function initUserMenu() {
  const chip = document.querySelector(".usuario-chip");
  if (!chip) return;
  chip.addEventListener("click", () => {
    if (confirm("Deseja sair do sistema?")) {
      window.location.href = "/logout";
    }
  });
}

/* ---------------------------------------------------------
 * UTILITARIOS COMPARTILHADOS
 * --------------------------------------------------------- */
/**
 * Escapa um valor para ser inserido em HTML (conteudo ou atributo entre
 * aspas). TODO dado vindo do servidor/usuario interpolado em innerHTML
 * deve passar por aqui, senao um nome como <img src=x onerror=...>
 * executaria codigo no navegador de quem abrir a tela (XSS).
 */
function esc(valor) {
  if (valor === null || valor === undefined) return "";
  return String(valor)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/`/g, "&#96;");
}

/** Valor para usar como argumento de funcao em onclick="...": JSON escapado para atributo. */
function argJs(valor) {
  return esc(JSON.stringify(valor === undefined ? null : valor));
}

/** Etiqueta colorida do destino da alta (Residência, Outro hospital,
 * Óbito), no mesmo padrao usado na lista de Altas do SOP. */
const DESTINO_BADGE_CLASSE = {
  "Residência": "badge-ok",
  "Outro hospital": "badge-media",
  "Óbito": "badge-pendencia",
};

function badgeDestino(destino) {
  if (!destino) return "-";
  return `<span class="badge ${DESTINO_BADGE_CLASSE[destino] || "badge-unidade"}">${esc(destino)}</span>`;
}

function tokenCsrf() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": tokenCsrf(),
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try { payload = await resp.json(); } catch (e) { /* resposta sem corpo */ }

  if (!resp.ok) {
    const erro = new Error((payload && payload.erro) || `Erro HTTP ${resp.status}`);
    erro.payload = payload;
    erro.status = resp.status;
    throw erro;
  }
  return payload;
}

function formatarData(isoString) {
  if (!isoString) return "-";
  const d = new Date(isoString);
  // O backend serializa datetimes "naive" do Postgres (hora local, sem fuso)
  // como string RFC 1123 terminada em "GMT" (comportamento padrao do Flask),
  // sem na verdade converter nada. Aqui forcamos a leitura de volta em UTC
  // para recuperar exatamente a hora local gravada no banco, sem aplicar o
  // fuso do navegador por cima (o que deslocaria a hora de novo).
  if (isNaN(d)) return "-";
  return `${formatarDataSimples(isoString)} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** Data no padrao brasileiro dd/mm/aa (lida em UTC, ver formatarData). */
function formatarDataSimples(dateString) {
  if (!dateString) return "-";
  const d = new Date(dateString);
  if (isNaN(d)) return "-";
  const dois = (n) => String(n).padStart(2, "0");
  return `${dois(d.getUTCDate())}/${dois(d.getUTCMonth() + 1)}/${dois(d.getUTCFullYear() % 100)}`;
}

/** Hora hh:mm a partir de "14:30", "14:30:00" etc. */
function formatarHora(hora) {
  if (!hora) return "";
  const partes = String(hora).trim().split(":");
  if (partes.length < 2) return String(hora).trim();
  return `${partes[0].padStart(2, "0")}:${partes[1].padStart(2, "0")}`;
}

/** Etiqueta "24h" (fundo amarelo, letra vermelha) para internacao com
 * tempo total de 0 dias (entrada e alta no mesmo dia). */
function etiqueta24h(diasInternacao) {
  return diasInternacao === 0
    ? ` <span class="badge badge-24h" title="Internação de menos de um dia">24h</span>`
    : "";
}

/**
 * Formata um total de horas uteis (ja descontando sabados/domingos, calculado
 * no backend) como "Xh YYmin", colorindo em vermelho piscando acima de
 * limiteCritico e (se informado) em laranja acima de limiteAlerta.
 */
function formatarTimer(horas, limiteCritico, limiteAlerta) {
  if (horas === null || horas === undefined) return "-";

  const horasInt = Math.floor(horas);
  const minutos = Math.round((horas - horasInt) * 60);
  const texto = `${horasInt}h ${String(minutos).padStart(2, "0")}min`;

  let classe = "timer-normal";
  if (limiteCritico != null && horas > limiteCritico) classe = "timer-critico";
  else if (limiteAlerta != null && horas > limiteAlerta) classe = "timer-alerta";

  return `<span class="timer-alta ${classe}">${texto}</span>`;
}

/** Timer de Altas/Pendencias: laranja acima de 12h, vermelho piscando acima de 24h. */
function formatarTimerHorasUteis(horas) {
  return formatarTimer(horas, 24, 12);
}

/** Timer de tempo no SOP: vermelho piscando acima de 48h, sem alerta intermediario. */
function formatarTimerSOP(horas) {
  return formatarTimer(horas, 48, null);
}

/**
 * Etiqueta de dias desde a alta do prontuario:
 * ate 30d verde/branco, 30-60d amarelo/preto, 60-80d laranja/preto,
 * 80-90d vermelho/branco, acima de 90d preto/branco.
 */
function badgeDiasAlta(dias) {
  if (dias === null || dias === undefined) return "-";

  let fundo, cor;
  if (dias <= 30) { fundo = "#2E7D32"; cor = "#fff"; }
  else if (dias <= 60) { fundo = "#F2C94C"; cor = "#000"; }
  else if (dias <= 80) { fundo = "#F2994A"; cor = "#000"; }
  else if (dias <= 90) { fundo = "#D64545"; cor = "#fff"; }
  else { fundo = "#000"; cor = "#fff"; }

  return `<span class="badge" style="background:${fundo}; color:${cor};">${esc(dias)} dia${dias === 1 ? "" : "s"}</span>`;
}

const STATUS_BADGE_CLASSE = {
  unidade: "badge-unidade",
  sop: "badge-sop",
  contas_medicas: "badge-contas",
  pronto_faturamento: "badge-faturamento",
  auditoria: "badge-auditoria",
  finalizado: "badge-finalizado",
};

const STATUS_LABEL_JS = {
  unidade: "Na Unidade",
  sop: "SOP",
  contas_medicas: "Contas Medicas",
  pronto_faturamento: "Pronto p/ Faturamento",
  auditoria: "Auditoria",
  finalizado: "Finalizado",
};

function badgeStatus(status) {
  const classe = STATUS_BADGE_CLASSE[status] || "badge-unidade";
  const label = esc(STATUS_LABEL_JS[status] || status);
  return `<span class="badge ${classe}">${label}</span>`;
}

function badgeCriticidade(criticidade) {
  const mapa = { alta: "badge-critica", media: "badge-media", baixa: "badge-baixa" };
  return `<span class="badge ${mapa[criticidade] || "badge-media"}">${esc(criticidade || "-")}</span>`;
}

function badgeStatusPendencia(status) {
  const mapa = {
    aberta: '<span class="badge badge-pendencia">Aberta</span>',
    em_analise: '<span class="badge badge-media">Em análise</span>',
    resolvida: '<span class="badge badge-media">Resolvida (aguardando SOP)</span>',
    confirmada: '<span class="badge badge-ok">Confirmada</span>',
  };
  return mapa[status] || esc(status);
}

/**
 * Campo de busca de profissional cadastrado (usado no registro de
 * pendencias no SOP e em Contas Medicas). So aceita um profissional
 * selecionado na lista de resultados - texto livre nao e submetido.
 * Espera os elementos #input-busca-profissional, #input-profissional-selecionado
 * e #resultados-profissional, alem do array global PROFISSIONAIS_CADASTRADOS.
 */
function configurarBuscaProfissional() {
  const inputBusca = document.getElementById("input-busca-profissional");
  const inputSelecionado = document.getElementById("input-profissional-selecionado");
  const resultados = document.getElementById("resultados-profissional");
  if (!inputBusca) return;

  inputBusca.addEventListener("input", () => {
    inputSelecionado.value = "";
    // Sem acento e sem diferenciar maiusculas; a lista vem do sistema
    // hospitalar e pode ter milhares de nomes, entao mostra so os primeiros.
    const semAcento = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const valor = semAcento(inputBusca.value.trim());
    if (!valor) {
      resultados.innerHTML = "";
      return;
    }
    const encontrados = PROFISSIONAIS_CADASTRADOS.filter((nome) => semAcento(nome).includes(valor));
    if (!encontrados.length) {
      resultados.innerHTML = `<div>Nenhum profissional encontrado.</div>`;
      return;
    }
    const MAXIMO = 30;
    resultados.innerHTML = encontrados.slice(0, MAXIMO).map((nome) => `
      <div style="padding:6px 0; cursor:pointer; border-bottom:1px solid var(--cor-borda);"
           onclick="selecionarProfissional(${argJs(nome)})">${esc(nome)}</div>
    `).join("") + (encontrados.length > MAXIMO
      ? `<div>Mais ${encontrados.length - MAXIMO} resultado(s): continue digitando para refinar.</div>` : "");
  });
}

function selecionarProfissional(nome) {
  document.getElementById("input-busca-profissional").value = nome;
  document.getElementById("input-profissional-selecionado").value = nome;
  document.getElementById("resultados-profissional").innerHTML = "";
}

function limparBuscaProfissional() {
  const inputBusca = document.getElementById("input-busca-profissional");
  if (!inputBusca) return;
  inputBusca.value = "";
  document.getElementById("input-profissional-selecionado").value = "";
  document.getElementById("resultados-profissional").innerHTML = "";
}

/* ---------------------------------------------------------
 * ENVIO PARA A UNIDADE (SOP e Analise)
 * Abre um modal para escolher a unidade de destino: unidades do
 * historico de internacao do prontuario + unidades locais cadastradas.
 * aoConcluir() roda depois do envio com sucesso.
 * --------------------------------------------------------- */
async function enviarProntuarioParaUnidade(prontuarioId, aoConcluir) {
  let dados;
  try {
    dados = await apiFetch(`/api/prontuarios/${encodeURIComponent(prontuarioId)}/unidades-envio`);
  } catch (e) {
    alert(e.message);
    return;
  }
  if (!dados.unidades.length) {
    alert("Nenhuma unidade disponível para este prontuário. Cadastre a unidade em Unidades.");
    return;
  }

  let modal = document.getElementById("modal-enviar-unidade");
  if (!modal) {
    modal = document.createElement("div");
    modal.className = "modal-fundo";
    modal.id = "modal-enviar-unidade";
    modal.innerHTML = `
      <div class="modal-caixa">
        <h3>Enviar para a Unidade</h3>
        <form id="form-enviar-unidade">
          <div class="campo">
            <label for="select-unidade-envio">Unidade de destino *</label>
            <select id="select-unidade-envio" required></select>
            <small class="texto-suave">Unidades do histórico de internação do prontuário e unidades cadastradas no sistema.</small>
          </div>
          <div class="campo">
            <label for="obs-unidade-envio">Observação</label>
            <textarea id="obs-unidade-envio" rows="2" maxlength="1000"></textarea>
          </div>
          <div class="form-acoes">
            <button type="button" class="btn btn-ghost" id="btn-cancelar-envio-unidade">Cancelar</button>
            <button type="submit" class="btn btn-primario">Enviar</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener("click", (ev) => { if (ev.target === modal) fecharModal(modal.id); });
    document.getElementById("btn-cancelar-envio-unidade").addEventListener("click", () => fecharModal(modal.id));
  }

  const select = document.getElementById("select-unidade-envio");
  const placeholder = `<option value="">Selecione</option>`;
  select.innerHTML = placeholder + dados.unidades.map((u) =>
    `<option value="${esc(u.id)}" ${u.id === dados.atual ? "selected" : ""}>${esc(u.nome)}${u.id < 0 ? " (cadastrada no sistema)" : ""}</option>`
  ).join("");
  document.getElementById("obs-unidade-envio").value = "";

  // Recria o form para nao acumular handlers de envios anteriores.
  const formAntigo = document.getElementById("form-enviar-unidade");
  const form = formAntigo.cloneNode(true);
  formAntigo.replaceWith(form);
  form.querySelector("#select-unidade-envio").value = select.value;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const unidadeId = form.querySelector("#select-unidade-envio").value;
    if (!unidadeId) return;
    const botao = form.querySelector('button[type="submit"]');
    botao.disabled = true;
    try {
      await apiFetch(`/api/prontuarios/${encodeURIComponent(prontuarioId)}/mover`, {
        method: "POST",
        body: JSON.stringify({
          destino: "unidade",
          unidade_id: Number(unidadeId),
          observacao: form.querySelector("#obs-unidade-envio").value.trim(),
        }),
      });
      fecharModal("modal-enviar-unidade");
      if (aoConcluir) aoConcluir();
    } catch (e) {
      alert(e.message);
    } finally {
      botao.disabled = false;
    }
  });
  form.querySelector("#btn-cancelar-envio-unidade").addEventListener("click", () => fecharModal("modal-enviar-unidade"));
  abrirModal("modal-enviar-unidade");
}

/* ---------------------------------------------------------
 * PRESCRICOES, EVOLUCOES E EXAMES NO REGISTRO DE PENDENCIA (Analise SOP e
 * Contas Medicas). Tres listas suspensas (nao canceladas) da internacao.
 * So uma origem por pendencia: escolher uma limpa e desabilita as outras
 * duas. A escolha preenche unidade (quando disponivel), profissional, data
 * e um resumo no inicio da descricao.
 * --------------------------------------------------------- */
const ORIGENS_PENDENCIA = { prescricoes: null, evolucoes: null, exames: null };

/** Uma entrada por select: chave em ORIGENS_PENDENCIA e como montar os
 * dados para preencherPendencia() a partir do item escolhido. */
const CONFIG_SELECTS_PENDENCIA = [
  { id: "select-prescricao-pendencia", chave: "prescricoes",
    montar: (p) => ({ isnClinica: p.isn_clinica, dataHora: p.dat_prescricao,
                       profissionalNome: p.profissional_nome, resumo: resumoPrescricao(p) }) },
  { id: "select-evolucao-pendencia", chave: "evolucoes",
    montar: (ev) => ({ isnClinica: ev.isn_clinica, dataHora: ev.dat_cadastro,
                        profissionalNome: ev.profissional_nome, resumo: resumoEvolucao(ev) }) },
  { id: "select-exame-pendencia", chave: "exames",
    montar: (ex) => ({ isnClinica: null, dataHora: ex.dat_solicitacao,
                        profissionalNome: ex.solicitante_nome, resumo: resumoExame(ex) }) },
];

function profissionalComConselho(nome, conselho, numero) {
  if (!nome) return "-";
  const registro = [conselho, numero].filter(Boolean).join(" ");
  return registro ? `${nome} (${registro})` : nome;
}

function resumoPrescricao(p) {
  return [
    `Prescrição ${p.tipo ? p.tipo + " " : ""}de ${formatarData(p.dat_prescricao)}`,
    `Prescritor: ${profissionalComConselho(p.profissional_nome, p.profissional_conselho, p.profissional_num_conselho)}`,
    `Aprazamento: ${profissionalComConselho(p.aprazamento_nome, p.aprazamento_conselho, p.aprazamento_num_conselho)}`,
    `Local: ${[p.dsc_clinica, p.dsc_enfermaria, p.dsc_leito].filter(Boolean).join(" / ") || "-"}`,
  ].join(" | ");
}

function resumoEvolucao(ev) {
  return [
    `Evolução de ${formatarData(ev.dat_cadastro)}`,
    `Profissional: ${profissionalComConselho(ev.profissional_nome, ev.profissional_conselho, ev.profissional_num_conselho)}`,
    `Clínica: ${ev.dsc_clinica || "-"}`,
  ].join(" | ");
}

function resumoExame(ex) {
  return [
    `Exame ${ex.dsc_exame || ""}${ex.classificacao ? ` (${ex.classificacao})` : ""} solicitado em ${formatarData(ex.dat_solicitacao)}`,
    `Solicitante: ${profissionalComConselho(ex.solicitante_nome, ex.solicitante_conselho, ex.solicitante_num_conselho)}`,
    `Realização: ${profissionalComConselho(ex.realizacao_nome, ex.realizacao_conselho, ex.realizacao_num_conselho)}`,
  ].join(" | ");
}

/** Preenche uma lista suspensa (textContent: os nomes nao viram HTML). */
function montarSelectPendencia(select, itens, vazio, rotulo) {
  select.innerHTML = "";
  const primeira = document.createElement("option");
  primeira.value = "";
  primeira.textContent = itens.length ? "Nenhuma (não usar)" : vazio;
  select.appendChild(primeira);
  itens.forEach((item, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = rotulo(item);
    select.appendChild(opt);
  });
  select.disabled = !itens.length;
  select.value = "";
}

async function carregarListaPendencia(selectId, chave, url, vazio, rotulo) {
  const select = document.getElementById(selectId);
  if (!select) return;
  try {
    if (ORIGENS_PENDENCIA[chave] === null) {
      ORIGENS_PENDENCIA[chave] = await apiFetch(url);
    }
    montarSelectPendencia(select, ORIGENS_PENDENCIA[chave], vazio, rotulo);
  } catch (e) {
    select.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `Erro ao carregar: ${e.message}`;
    select.appendChild(opt);
    select.disabled = true;
  }
  atualizarDisponibilidadeSelectsPendencia();
}

/** So uma origem por pendencia: enquanto uma lista estiver com algo
 * escolhido, as outras ficam desabilitadas (alem de limpas), para a regra
 * ficar visivel e nao so "silenciosa" ao trocar de escolha. */
function atualizarDisponibilidadeSelectsPendencia() {
  const selects = CONFIG_SELECTS_PENDENCIA
    .map((cfg) => document.getElementById(cfg.id))
    .filter(Boolean);
  if (!selects.length) return;
  const algumEscolhido = selects.some((s) => s.value !== "");
  selects.forEach((sel, i) => {
    const temItens = (ORIGENS_PENDENCIA[CONFIG_SELECTS_PENDENCIA[i].chave] || []).length > 0;
    sel.disabled = !temItens || (algumEscolhido && sel.value === "");
  });
}

function carregarPrescricoesPendencia(prontuarioId) {
  ligarSelectsPendencia();
  return carregarListaPendencia(
    "select-prescricao-pendencia", "prescricoes",
    `/api/prontuarios/${encodeURIComponent(prontuarioId)}/prescricoes`,
    "Nenhuma prescrição (não cancelada) nesta internação",
    (p) => [formatarData(p.dat_prescricao), p.tipo || "Prescrição",
            profissionalComConselho(p.profissional_nome, p.profissional_conselho, p.profissional_num_conselho),
            [p.dsc_clinica, p.dsc_enfermaria, p.dsc_leito].filter(Boolean).join(" / ")]
      .filter(Boolean).join(" · "));
}

function carregarEvolucoesPendencia(prontuarioId) {
  ligarSelectsPendencia();
  return carregarListaPendencia(
    "select-evolucao-pendencia", "evolucoes",
    `/api/prontuarios/${encodeURIComponent(prontuarioId)}/evolucoes`,
    "Nenhuma evolução nesta internação",
    (ev) => [formatarData(ev.dat_cadastro),
             profissionalComConselho(ev.profissional_nome, ev.profissional_conselho, ev.profissional_num_conselho),
             ev.dsc_clinica].filter(Boolean).join(" · "));
}

function carregarExamesPendencia(prontuarioId) {
  ligarSelectsPendencia();
  return carregarListaPendencia(
    "select-exame-pendencia", "exames",
    `/api/prontuarios/${encodeURIComponent(prontuarioId)}/exames-pendencia`,
    "Nenhum exame (não cancelado) nesta internação",
    (ex) => [formatarData(ex.dat_solicitacao), ex.dsc_exame || "Exame", ex.classificacao,
             profissionalComConselho(ex.solicitante_nome, ex.solicitante_conselho, ex.solicitante_num_conselho)]
      .filter(Boolean).join(" · "));
}

/** Liga (uma vez) os eventos das listas: so uma origem por pendencia. */
function ligarSelectsPendencia() {
  const selects = CONFIG_SELECTS_PENDENCIA
    .map((cfg) => document.getElementById(cfg.id))
    .filter(Boolean);
  if (!selects.length || selects[0].dataset.ligado) return;
  selects.forEach((sel) => { sel.dataset.ligado = "1"; });

  CONFIG_SELECTS_PENDENCIA.forEach((cfg) => {
    const sel = document.getElementById(cfg.id);
    if (!sel) return;
    sel.addEventListener("change", () => {
      CONFIG_SELECTS_PENDENCIA.forEach((outro) => {
        if (outro.id === cfg.id) return;
        const outroSel = document.getElementById(outro.id);
        if (outroSel) outroSel.value = "";
      });
      atualizarDisponibilidadeSelectsPendencia();
      const item = sel.value === "" ? null : (ORIGENS_PENDENCIA[cfg.chave] || [])[Number(sel.value)];
      if (!item) { removerResumoPendencia(); return; }
      preencherPendencia(cfg.montar(item));
    });
  });
}

/** Tira da descricao o resumo colocado pela ultima escolha (se ainda estiver la). */
function removerResumoPendencia() {
  const area = document.querySelector('#form-nova-pendencia [name="descricao"]');
  if (!area) return;
  const resumo = area.dataset.resumoOrigem;
  if (resumo && area.value.startsWith(resumo)) {
    area.value = area.value.slice(resumo.length).replace(/^\n/, "");
  }
  delete area.dataset.resumoOrigem;
}

/** Preenche o formulario de pendencia: unidade (se for uma das opcoes),
 * data da ocorrencia, profissional (se estiver na lista) e um resumo no
 * inicio da descricao (trocado, e nao repetido, a cada nova escolha). */
function preencherPendencia({ isnClinica, dataHora, profissionalNome, resumo }) {
  const form = document.getElementById("form-nova-pendencia");
  if (!form) return;

  const selUnidade = form.querySelector('[name="unidade_id"]');
  if (isnClinica !== null && isnClinica !== undefined
      && selUnidade.querySelector(`option[value="${isnClinica}"]`)) {
    selUnidade.value = String(isnClinica);
  }

  const d = new Date(dataHora);
  if (dataHora && !isNaN(d)) {
    const dois = (n) => String(n).padStart(2, "0");
    form.querySelector('[name="data_ocorrencia"]').value =
      `${d.getUTCFullYear()}-${dois(d.getUTCMonth() + 1)}-${dois(d.getUTCDate())}`;
  }

  if (profissionalNome && typeof PROFISSIONAIS_CADASTRADOS !== "undefined"
      && PROFISSIONAIS_CADASTRADOS.includes(profissionalNome)) {
    selecionarProfissional(profissionalNome);
  }

  removerResumoPendencia();
  const area = form.querySelector('[name="descricao"]');
  area.value = area.value ? `${resumo}\n${area.value}` : `${resumo}\n`;
  area.dataset.resumoOrigem = resumo;
}
