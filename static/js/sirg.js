/* Comportamentos gerais do SiRG (todas as telas). */
(function () {
  "use strict";
  // alturas das barras fixas, para os menus e o sumário do documento não ficarem por baixo delas
  function medir() {
    var topo = document.querySelector(".barra-topo");
    var ferr = document.querySelector(".doc-ferramentas");
    var raiz = document.documentElement.style;
    if (topo) raiz.setProperty("--topo-h", topo.offsetHeight + "px");
    if (ferr) raiz.setProperty("--ferr-h", ferr.offsetHeight + "px");
  }
  medir();
  window.addEventListener("resize", medir);
  if (window.ResizeObserver) {          // a barra muda de altura quando os botões mudam de texto
    var ro = new ResizeObserver(medir);
    [".barra-topo", ".doc-ferramentas"].forEach(function (s) { var el = document.querySelector(s); if (el) ro.observe(el); });
  }

  // caixas "Como usar esta tela": lembra se a pessoa fechou (só neste navegador)
  document.querySelectorAll("details.ajuda-tela[data-ajuda]").forEach(function (d) {
    var chave = "sirg-ajuda-" + d.dataset.ajuda;
    try { if (localStorage.getItem(chave) === "fechada") d.removeAttribute("open"); } catch (e) { /* sem armazenamento */ }
    d.addEventListener("toggle", function () {
      try { localStorage.setItem(chave, d.open ? "aberta" : "fechada"); } catch (e) { /* sem armazenamento */ }
      medir();
    });
  });
})();

/* Números vivos do texto: ao clicar ou passar o mouse, mostra de onde vem a informação (tabela, setor) e um link para ela. */
(function () {
  "use strict";
  var pop = null;
  function fechar() { if (pop) { pop.remove(); pop = null; } }
  function abrir(span) {
    fechar();
    if (!span.dataset.onde) return;
    pop = document.createElement("div");
    pop.className = "pop-num shadow-sm";
    pop.setAttribute("role", "dialog");
    var pendente = span.classList.contains("pendente");
    var h = document.createElement("div");
    h.className = "pop-num-tit";
    h.textContent = pendente ? "Número ainda não preenchido" : "Número ligado à tabela";
    pop.appendChild(h);
    function linha(rot, val) {
      if (!val) return;
      var d = document.createElement("div");
      var b = document.createElement("strong"); b.textContent = rot + " ";
      d.appendChild(b); d.appendChild(document.createTextNode(val));
      pop.appendChild(d);
    }
    linha("Vem de:", span.dataset.onde);
    linha("Seção:", span.dataset.secao);
    linha("Quem preenche:", span.dataset.setor);
    if (span.dataset.situacao) linha("Situação:", span.dataset.situacao.charAt(0).toUpperCase() + span.dataset.situacao.slice(1) + ".");
    if (pendente) {
      var p = document.createElement("div");
      p.className = "mini text-secondary mt-1";
      p.textContent = "O número aparece sozinho aqui assim que for digitado na tabela.";
      pop.appendChild(p);
    }
    if (span.dataset.link) {
      var a = document.createElement("a");
      a.href = span.dataset.link; a.className = "btn btn-sm btn-outline-primary mt-2";
      a.innerHTML = '<i class="bi bi-table"></i> Abrir a tabela';
      a.target = "_blank"; a.rel = "noopener";
      pop.appendChild(a);
    }
    document.body.appendChild(pop);
    var r = span.getBoundingClientRect();
    var left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12);
    pop.style.left = Math.max(8, left) + "px";
    pop.style.top = (window.scrollY + r.bottom + 6) + "px";
  }
  function preenchivel(span) {
    if (!span || !window.SIRG || !window.SIRG.preencher) return false;
    // no documento: quem pode digita ali mesmo; total ainda vazio abre a tabela (preencher.js)
    return span.dataset.pode === "1" || (span.classList.contains("pendente") && !!span.dataset.quadro && !!span.closest(".pg"));
  }
  document.addEventListener("click", function (e) {
    var span = e.target.closest ? e.target.closest(".sirg-num[data-onde]") : null;
    if (preenchivel(span)) return;            // no documento, quem preenche digita ali mesmo (preencher.js)
    if (span) { abrir(span); return; }
    if (pop && !pop.contains(e.target)) fechar();
  });
  // passar o mouse também mostra (depois de um instante), e some ao sair do número e do quadrinho
  var tAbrir = null, tFechar = null, atual = null;
  document.addEventListener("mouseover", function (e) {
    var span = e.target.closest ? e.target.closest(".sirg-num[data-onde]") : null;
    if (pop && pop.contains(e.target)) { clearTimeout(tFechar); return; }
    if (!span || preenchivel(span)) return;
    clearTimeout(tFechar);
    if (span.title) { span.dataset.dica = span.title; span.removeAttribute("title"); }   // evita duas dicas iguais
    if (atual === span && pop) return;
    clearTimeout(tAbrir);
    tAbrir = setTimeout(function () { atual = span; abrir(span); }, 350);
  });
  document.addEventListener("mouseout", function (e) {
    var de = e.target.closest ? e.target.closest(".sirg-num[data-onde], .pop-num") : null;
    if (!de) return;
    var para = e.relatedTarget;
    if (para && (de.contains(para) || (pop && pop.contains(para)) || (atual && atual.contains(para)))) return;
    clearTimeout(tAbrir);
    tFechar = setTimeout(function () { fechar(); atual = null; }, 300);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });
  window.addEventListener("scroll", fechar, { passive: true, capture: true });
})();

// ---- 2.13: páginas do RG do tamanho da tela (a página inteira cabe na largura, como no PDF) -------------------
(function () {
  function ajustar() {
    document.querySelectorAll(".pg-moldura").forEach(function (m) {
      var pg = m.querySelector(".pg");
      if (!pg) return;
      var k = m.clientWidth / (parseFloat(pg.dataset.largura) || 935.4);
      if (k > 0) pg.style.zoom = k.toFixed(4);
    });
    // tabelas por cima da página: diminuem até caber na área da tabela do RG
    document.querySelectorAll(".pg-obj").forEach(function (o) {
      var f = o.querySelector(".doc-figura"), fig = o.querySelector("figure");
      if (!f || !fig || !o.querySelector("table")) return;
      f.style.zoom = 1; f.style.height = "auto"; fig.style.height = "auto";
      var r = Math.min(o.clientHeight / Math.max(1, fig.scrollHeight), 1);
      f.style.height = ""; fig.style.height = "";
      if (r < 1) f.style.zoom = r.toFixed(3);
    });
  }
  window.SIRGPaginas = { ajustar: ajustar };
  if (!document.querySelector(".pg-moldura")) return;
  ajustar();
  var t = null;
  window.addEventListener("resize", function () { clearTimeout(t); t = setTimeout(ajustar, 80); });
  if (window.ResizeObserver) {
    var mesa = document.querySelector(".doc-mesa");
    if (mesa) new ResizeObserver(function () { clearTimeout(t); t = setTimeout(ajustar, 60); }).observe(mesa);
  }
  window.addEventListener("beforeprint", function () { document.querySelectorAll(".pg").forEach(function (p) { p.dataset.z = p.style.zoom; p.style.zoom = 1; }); });
  window.addEventListener("afterprint", ajustar);
})();
