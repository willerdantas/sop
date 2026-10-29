/**
 * exportar.js - exportacao de tabelas renderizadas para PDF e Excel.
 * Le a tabela ja exibida na tela (respeitando os filtros aplicados no
 * momento), ignorando a coluna "Ações" e a linha de "vazio-estado".
 * Usa SheetJS (xlsx) e jsPDF + jspdf-autotable, carregados via CDN.
 */

function extrairDadosTabela(tabelaId) {
  const tabela = document.getElementById(tabelaId);
  const headers = Array.from(tabela.querySelectorAll("thead th")).map((th) => th.textContent.trim());
  const indicesValidos = headers
    .map((h, i) => (h === "Ações" ? -1 : i))
    .filter((i) => i !== -1);
  const cabecalhos = indicesValidos.map((i) => headers[i]);

  const linhas = Array.from(tabela.querySelectorAll("tbody tr"))
    .filter((tr) => tr.children.length > 1)
    .map((tr) => {
      const celulas = Array.from(tr.querySelectorAll("td"));
      return indicesValidos.map((i) => (celulas[i] ? celulas[i].textContent.trim().replace(/\s+/g, " ") : ""));
    });

  return { cabecalhos, linhas };
}

function exportarExcel(tabelaId, nomeArquivo) {
  const { cabecalhos, linhas } = extrairDadosTabela(tabelaId);
  if (!linhas.length) {
    alert("Nenhum dado para exportar.");
    return;
  }
  const planilha = XLSX.utils.aoa_to_sheet([cabecalhos, ...linhas]);
  const livro = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(livro, planilha, "Dados");
  XLSX.writeFile(livro, `${nomeArquivo}.xlsx`);
}

function exportarPDF(tabelaId, titulo, nomeArquivo) {
  const { cabecalhos, linhas } = extrairDadosTabela(tabelaId);
  if (!linhas.length) {
    alert("Nenhum dado para exportar.");
    return;
  }
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "landscape" });
  doc.setFontSize(14);
  doc.text(titulo, 14, 15);
  doc.setFontSize(9);
  doc.text(new Date().toLocaleString("pt-BR"), 14, 21);
  doc.autoTable({
    head: [cabecalhos],
    body: linhas,
    startY: 26,
    styles: { fontSize: 8 },
    headStyles: { fillColor: [0, 128, 128] },
  });
  doc.save(`${nomeArquivo}.pdf`);
}
