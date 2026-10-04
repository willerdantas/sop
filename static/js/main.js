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
async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
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
  return d.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
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
  const label = STATUS_LABEL_JS[status] || status;
  return `<span class="badge ${classe}">${label}</span>`;
}
