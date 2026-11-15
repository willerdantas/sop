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
  return d.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    timeZone: "UTC",
  });
}

function formatarDataSimples(dateString) {
  if (!dateString) return "-";
  const d = new Date(dateString);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
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
    const valor = inputBusca.value.trim().toLowerCase();
    if (!valor) {
      resultados.innerHTML = "";
      return;
    }
    const encontrados = PROFISSIONAIS_CADASTRADOS.filter((nome) => nome.toLowerCase().includes(valor));
    if (!encontrados.length) {
      resultados.innerHTML = `<div>Nenhum profissional encontrado.</div>`;
      return;
    }
    resultados.innerHTML = encontrados.map((nome) => `
      <div style="padding:6px 0; cursor:pointer; border-bottom:1px solid var(--cor-borda);"
           onclick="selecionarProfissional(${argJs(nome)})">${esc(nome)}</div>
    `).join("");
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
