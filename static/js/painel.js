/**
 * painel.js - Painel de chamada (tempo real)
 * Faz polling em /api/painel e mostra contadores, a ultima movimentacao em
 * destaque e uma lista das ultimas 20 movimentacoes com rolagem automatica
 * continua (ao chegar no final, volta para o inicio).
 */

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("painel-root");
  if (!root) return;
  const intervaloMs = parseInt(root.getAttribute("data-poll-interval") || "5000", 10);

  carregarPainel();
  setInterval(carregarPainel, intervaloMs);
  iniciarAutoScroll();
});

async function carregarPainel() {
  try {
    const dados = await apiFetch("/api/painel");
    atualizarContadores(dados.contadores);
    atualizarDestaque(dados.ultimo);
    atualizarLista(dados.ultimos);
  } catch (e) {
    // Mantem o ultimo estado exibido em caso de falha temporaria de rede.
  }
}

function atualizarContadores(c) {
  document.getElementById("kpi-altas").textContent = c.altas;
  document.getElementById("kpi-sop").textContent = c.sop;
  document.getElementById("kpi-contas").textContent = c.contas_medicas;
  document.getElementById("kpi-faturamento").textContent = c.pronto_faturamento;
}

function badgeEvento(u) {
  if (u.tipo === "alta") {
    return `<span class="badge badge-media">${u.destino_label}</span>`;
  }
  return badgeStatus(u.destino);
}

function atualizarDestaque(ultimo) {
  const numero = document.getElementById("destaque-numero");
  const paciente = document.getElementById("destaque-paciente");
  const destino = document.getElementById("destaque-destino");
  const dataHora = document.getElementById("destaque-data-hora");

  if (!ultimo) {
    numero.textContent = "-";
    paciente.textContent = "Nenhuma movimentação ainda";
    destino.innerHTML = "";
    dataHora.textContent = "";
    return;
  }

  numero.textContent = ultimo.numero_prontuario;
  paciente.textContent = ultimo.paciente_nome;
  destino.innerHTML = badgeEvento(ultimo);
  dataHora.textContent = formatarData(ultimo.data_hora);
}

function atualizarLista(lista) {
  const tbody = document.getElementById("tbody-ultimos");
  if (!lista || !lista.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="vazio-estado">Nenhuma movimentação registrada ainda.</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map((u) => `
    <tr>
      <td><strong>${u.numero_prontuario}</strong></td>
      <td>${u.paciente_nome}</td>
      <td>${badgeEvento(u)}</td>
      <td>${formatarData(u.data_hora)}</td>
      <td>${formatarTimerHorasUteis(u.horas_uteis)}</td>
    </tr>
  `).join("");
}

function iniciarAutoScroll() {
  const container = document.getElementById("painel-lista-scroll");
  if (!container) return;

  setInterval(() => {
    if (container.scrollHeight <= container.clientHeight) return;

    container.scrollTop += 1;
    if (container.scrollTop + container.clientHeight >= container.scrollHeight) {
      container.scrollTop = 0;
    }
  }, 40);
}
