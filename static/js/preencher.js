/*
 * Preencher no próprio documento (2.12).
 *  - xxxxx no texto (campo do ano): clicar abre um quadrinho para digitar o número.
 *  - número ligado a uma tabela (xxxxx ou valor): quem preenche aquela tabela digita ali mesmo.
 *  - tabela, gráfico ou painel de números: o botão "Dados" (ou um clique na figura) abre, ao lado, a tabela de
 *    dados para preencher; o gráfico e os números do texto se atualizam sozinhos.
 *  - "Faltam N": vai para o próximo número a preencher.
 */
(function () {
  "use strict";
  var T = window.SIRGTexto;
  var CFG = T.cfg;
  var base = T.base;

  // ---- quadrinho de preenchimento -------------------------------------------------------------------------
  var pop = null, popAlvo = null;
  function fecharPop() { if (pop) { pop.remove(); pop = null; popAlvo = null; } }
  function forma(orig) {
    orig = (orig || "").trim();
    var pre = /^R\$/.test(orig) ? "R$" : "";
    var resto = pre ? orig.slice(2).trim() : orig;
    var suf = "";
    var m = resto.match(/\s(milhões|milhão|mil)$/);
    if (m) { suf = " " + m[1]; resto = resto.slice(0, m.index).trim(); }
    if (/%$/.test(resto)) { suf = "%" + suf; resto = resto.slice(0, -1).trim(); }
    return { pre: pre, suf: suf, num: resto };
  }
  function abrirPop(el, opcoes) {
    fecharPop();
    popAlvo = el;
    pop = document.createElement("div");
    pop.className = "pop-campo shadow";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Preencher número");
    var f = forma(opcoes.orig || "");
    var h = "";
    if (opcoes.titulo) h += '<div class="pop-campo-tit">' + T.esc(opcoes.titulo) + "</div>";
    if (opcoes.antes) h += '<div class="pop-campo-antes">Em ' + (CFG.ano - 1) + ": <strong>" + T.esc(opcoes.antes) + "</strong></div>";
    h += '<div class="input-group input-group-sm">' + (f.pre ? '<span class="input-group-text">' + f.pre + "</span>" : "") +
      '<input class="form-control js-pop-valor" inputmode="decimal" autocomplete="off" value="' + T.esc(opcoes.valor || "") + '" aria-label="Valor de ' + CFG.ano + '">' +
      (f.suf ? '<span class="input-group-text">' + T.esc(f.suf.trim()) + "</span>" : "") + "</div>";
    h += '<div class="pop-campo-erro text-danger mini" hidden></div>';
    h += '<div class="pop-campo-acoes"><button type="button" class="btn btn-sm btn-primary js-pop-salvar">Salvar</button>';
    if (opcoes.manter) h += '<button type="button" class="btn btn-sm btn-outline-secondary js-pop-manter" title="O número continua o mesmo de ' + (CFG.ano - 1) + '">Manter ' + T.esc(opcoes.manter) + "</button>";
    if (opcoes.dados) h += '<button type="button" class="btn btn-sm btn-link js-pop-dados">Ver a tabela</button>';
    h += "</div>";
    if (opcoes.origem) h += '<div class="mini text-secondary mt-1">' + T.esc(opcoes.origem) + "</div>";
    pop.innerHTML = h;
    document.body.appendChild(pop);
    var r = el.getBoundingClientRect();
    var left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12);
    pop.style.left = Math.max(8, left) + "px";
    pop.style.top = (window.scrollY + r.bottom + 6) + "px";
    var inp = pop.querySelector(".js-pop-valor");
    inp.focus(); inp.select();
    pop.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); opcoes.salvar(inp.value, true); }
      if (e.key === "Escape") { e.preventDefault(); fecharPop(); el.focus && el.focus(); }
    });
    pop.querySelector(".js-pop-salvar").addEventListener("click", function () { opcoes.salvar(inp.value, false); });
    var mt = pop.querySelector(".js-pop-manter");
    if (mt) mt.addEventListener("click", function () { opcoes.salvar(opcoes.manter, false); });
    var dd = pop.querySelector(".js-pop-dados");
    if (dd) dd.addEventListener("click", function () { var q = opcoes.dados; fecharPop(); abrirGaveta(q); });
  }
  function erroPop(msg) {
    if (!pop) return;
    var e = pop.querySelector(".pop-campo-erro");
    e.textContent = msg; e.hidden = false;
    pop.querySelector(".js-pop-valor").setAttribute("aria-invalid", "true");
  }

  // campo do texto (xxxxx)
  function abrirCampo(span) {
    var bloco = span.closest(".doc-bloco");
    if (!bloco) return;
    var orig = span.getAttribute("data-orig") || "";
    var f = forma(orig);
    var atual = span.classList.contains("vazio") ? "" : forma(span.textContent).num;
    abrirPop(span, {
      orig: orig, antes: orig, valor: atual, manter: f.num,
      salvar: function (valor, proximo) {
        T.post(base + "campos/", { bloco: bloco.dataset.bloco, chave: span.dataset.c, valor: valor }).then(function (r) {
          if (!r.ok) { erroPop(r.erro || "Não foi possível salvar."); return; }
          span.textContent = r.exibido;
          span.classList.toggle("vazio", r.vazio);
          span.classList.add("salvo-agora");
          setTimeout(function () { span.classList.remove("salvo-agora"); }, 1500);
          fecharPop();
          atualizarContagens([secaoDe(span)]);
          if (proximo) irParaProximo(span.closest("[data-secao]"), span);
        });
      }
    });
  }
  // número ligado a uma tabela
  function numBr(s) {
    s = String(s || "").replace(/[^\d,.\-]/g, "");
    if (s.indexOf(",") >= 0) s = s.replace(/\./g, "").replace(",", ".");
    else if ((s.match(/\./g) || []).length > 1 || /\.\d{3}$/.test(s)) s = s.replace(/\./g, "");
    return parseFloat(s);
  }
  function abrirNumero(span) {
    var ref = span.dataset.ref || "";
    // número escrito em milhões ("R$ 570,87 milhões", "5,82") ou em mil: digita-se na mesma unidade
    var esc = span.dataset.escala || "", mult = (esc === "mi" || esc === "nmi") ? 1e6 : (esc === "mil" ? 1e3 : 1);
    var atual = span.dataset.edicao || "";
    if (mult > 1 && atual && !isNaN(numBr(atual))) atual = (numBr(atual) / mult).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
    abrirPop(span, {
      titulo: (span.dataset.onde || "") + (mult > 1 ? " — digite em " + (mult === 1e6 ? "milhões" : "milhares") + " de R$" : ""),
      valor: atual, origem: "Preenchido por " + (span.dataset.setor || "—") + ". O mesmo número aparece na tabela.",
      dados: quadroDaRef(ref),
      salvar: function (valor, proximo) {
        if (mult > 1 && String(valor).trim() && !isNaN(numBr(valor))) valor = (numBr(valor) * mult).toFixed(2).replace(".", ",");
        fetch("/ciclos/" + CFG.ano + "/celula/", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": CFG.csrf },
          body: JSON.stringify({ linha: span.dataset.l, coluna: span.dataset.c, valor: valor, anterior: span.dataset.edicao || "" })
        }).then(function (r) { return r.json(); }).then(function (r) {
          if (!r.ok) {
            if (r.conflito) { erroPop("Outra pessoa acabou de alterar este número (agora: " + (r.atual || "vazio") + "). Feche e abra de novo."); return; }
            erroPop(r.erro || "Não foi possível salvar.");
            return;
          }
          span.dataset.edicao = r.edicao;
          fecharPop();
          atualizarQuadros([ref.split(".")[0]]);
          if (proximo) irParaProximo(span.closest("[data-secao]"), span);
        }).catch(function () { erroPop("Sem conexão com o servidor."); });
      }
    });
  }
  var QUADROS = {};          // chave -> pk (dos botões "Dados" do documento)
  document.querySelectorAll(".doc-figura.com-dados").forEach(function (f) {
    var ids = (f.dataset.quadros || "").split(","), ch = (f.dataset.chaves || "").split(",");
    ch.forEach(function (c, i) { if (c) QUADROS[c] = ids[i]; });
  });
  function quadroDaRef(ref) { return QUADROS[(ref || "").split(".")[0]] || null; }

  // ---- gaveta com a tabela de dados ----------------------------------------------------------------------
  var gaveta = document.getElementById("doc-gaveta");
  var gavetaQuadro = null, sujos = {};
  function abrirGaveta(qid) {
    if (!gaveta || !qid) return;
    fecharPop();
    var rev = document.getElementById("doc-revisao");
    if (rev && !rev.hidden) rev.querySelector(".js-rev-fechar").click();
    gaveta.hidden = false;
    document.getElementById("doc-corpo").classList.add("com-gaveta");
    gavetaQuadro = String(qid);
    var corpo = gaveta.querySelector(".js-gaveta-corpo");
    corpo.innerHTML = '<div class="text-secondary p-3"><span class="spinner-border spinner-border-sm"></span> Abrindo os dados…</div>';
    T.get(base + "quadros/" + qid + "/gaveta/").then(function (j) {
      gaveta.querySelector(".js-gaveta-titulo").textContent = j.titulo;
      corpo.innerHTML = j.html;
      var inp = corpo.querySelector(".cel-input");
      var vazio = Array.prototype.find.call(corpo.querySelectorAll(".col-atual ~ td .cel-input, td.ed .cel-input"), function (i) { return !i.value; });
      var foco = vazio || inp;
      if (foco) foco.focus();
    }).catch(function () { corpo.innerHTML = '<div class="text-danger p-3">Não foi possível abrir os dados.</div>'; });
  }
  function fecharGaveta() {
    if (!gaveta || gaveta.hidden) return;
    var ativo = document.activeElement;
    if (ativo && ativo.classList && ativo.classList.contains("cel-input")) ativo.blur();      // salva a célula aberta
    // o número do botão Dados da seção acompanha o que ainda está vazio nesta tabela
    var vazias = Array.prototype.filter.call(gaveta.querySelectorAll('.cel-input[data-travada="0"]'), function (i) {
      return !i.value && !i.placeholder && i.closest("td") && !i.closest("td").classList.contains("calc"); }).length;
    document.querySelectorAll('.js-dados-secao[data-quadro="' + gavetaQuadro + '"]').forEach(function (it) {
      var bd = it.querySelector(".badge-faltam");
      if (vazias && bd) bd.textContent = vazias;
      else if (!vazias && bd) bd.outerHTML = '<i class="bi bi-check2 text-success"></i>';
    });
    var sec = document.querySelector('.js-dados-secao[data-quadro="' + gavetaQuadro + '"]');
    sec = sec && sec.closest("[data-secao]");
    var qualquer = sec || document.querySelector(".sec-card[data-secao]");
    if (qualquer) atualizarContagens([qualquer.getAttribute("data-secao")]);
    gaveta.hidden = true;
    document.getElementById("doc-corpo").classList.remove("com-gaveta");
    gaveta.querySelector(".js-gaveta-corpo").innerHTML = "";
    gavetaQuadro = null;
    publicar();
  }
  if (gaveta) gaveta.querySelector(".js-gaveta-fechar").addEventListener("click", fecharGaveta);
  // cada célula salva na gaveta: atualiza, logo depois, as tabelas, gráficos e números do documento
  var espera = null;
  document.addEventListener("sirg:celula", function () {
    var card = gaveta && gaveta.querySelector(".quadro[data-chave]");
    if (card) sujos[card.dataset.chave] = 1;
    clearTimeout(espera);
    espera = setTimeout(publicar, 900);
  });
  function publicar() {
    var ch = Object.keys(sujos);
    sujos = {};
    if (ch.length) atualizarQuadros(ch);
  }
  function atualizarQuadros(chaves) {
    var ativoId = window.SIRGEditor && window.SIRGEditor.ativoId ? window.SIRGEditor.ativoId() : null;
    var secoes = {};
    T.post(base + "escrever/atualizar/", { quadros: chaves }).then(function (r) {
      Object.keys(r.blocos || {}).forEach(function (id) {
        var it = r.blocos[id], el = document.getElementById("bloco-" + id);
        if (!el) return;
        secoes[secaoDe(el)] = 1;
        if (it.tipo === "texto") {
          if (String(ativoId) === String(id)) return;          // trecho aberto: atualiza quando for salvo
          var area = el.querySelector(".texto-rg");
          if (area) area.innerHTML = it.html;
        } else {
          var tmp = document.createElement("div");
          tmp.innerHTML = it.html;
          var novo = tmp.firstElementChild;
          if (novo) { el.replaceWith(novo); novo.classList.add("rev-piscar"); setTimeout(function () { novo.classList.remove("rev-piscar"); }, 1600); }
        }
      });
      if (window.SIRGPaginas) window.SIRGPaginas.ajustar();
      atualizarContagens(Object.keys(secoes));
    });
  }
  function secaoDe(el) { var s = el.closest("[data-secao]"); return s ? s.getAttribute("data-secao") : ""; }
  function atualizarContagens(secoes) {
    secoes = (secoes || []).filter(Boolean);
    if (!secoes.length) return;
    T.post(base + "escrever/atualizar/", { secoes: secoes }).then(function (r) {
      Object.keys(r.faltam || {}).forEach(function (pk) {
        var n = r.faltam[pk];
        document.querySelectorAll('.sec-card[data-secao="' + pk + '"] > .sec-card-cab .js-faltam-sec, section.sec-card[data-secao="' + pk + '"] > .sec-card-cab .js-faltam-sec').forEach(function (b) {
          if (n) b.textContent = "Faltam " + n;
          else { b.outerHTML = '<span class="badge badge-pronto"><i class="bi bi-check2"></i> Números completos</span>'; }
        });
      });
      if (r.total != null) {
        var g = document.querySelector(".js-faltam span");
        if (g) g.textContent = r.total ? "Faltam " + r.total : "Tudo preenchido";
      }
    });
  }

  // ---- próximo a preencher -------------------------------------------------------------------------------
  var CANDIDATOS = ".sirg-campo.vazio.pode, .sirg-num.pendente[data-pode='1'], .pg .sirg-num.pendente[data-quadro][data-meu], .doc-figura.com-dados .destaque.vazio, .doc-figura.com-dados td";
  function pendentesEm(raiz) {
    return Array.prototype.filter.call(raiz.querySelectorAll(CANDIDATOS), function (el) {
      if (el.tagName === "TD") return el.textContent.trim() === "xxxxx";
      return true;
    });
  }
  function irParaProximo(raiz, depoisDe) {
    raiz = raiz || document;
    var lista = function (sel) { return Array.prototype.concat.apply([], Array.prototype.map.call(document.querySelectorAll(sel), pendentesEm)); };
    var minhas;
    if (raiz === document) minhas = lista(".sec-card.pode, .pg-cx.pode");
    else if (raiz.closest && raiz.closest(".pg")) {          // nas páginas do RG: todas as caixas da mesma seção
      var pk = raiz.getAttribute("data-secao");
      minhas = lista('.pg-cx[data-secao="' + pk + '"], .pg-legado[data-secao="' + pk + '"]');
    } else minhas = pendentesEm(raiz);
    if (!minhas.length) {
      // nada mais no texto: o que falta está numa tabela da seção que não aparece nas páginas (botão Dados)
      var q = document.querySelector((raiz === document ? "" : '[data-secao="' + (raiz.getAttribute && raiz.getAttribute("data-secao")) + '"] ') +
        ".js-dados-secao .badge-faltam") || document.querySelector(".js-dados-secao .badge-faltam");
      if (q) { abrirGaveta(q.closest(".js-dados-secao").dataset.quadro); return; }
      T.aviso(raiz === document ? "Não há mais xxxxx nas suas seções. Se ainda faltar algum dado, ele está no botão Dados da seção." : "Nesta seção não há mais xxxxx no texto. Confira o botão Dados, no alto da seção.", "success");
      return;
    }
    var alvo = null;
    if (depoisDe) {
      alvo = minhas.find(function (el) { return depoisDe.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING; });
    } else {
      var topo = window.scrollY + 140;
      alvo = minhas.find(function (el) { return el.getBoundingClientRect().top + window.scrollY > topo; });
    }
    alvo = alvo || minhas[0];
    alvo.scrollIntoView({ block: "center", behavior: "smooth" });
    alvo.classList.add("rev-piscar");
    setTimeout(function () { alvo.classList.remove("rev-piscar"); }, 1600);
    setTimeout(function () {
      if (alvo.classList.contains("sirg-campo")) abrirCampo(alvo);
      else if (alvo.classList.contains("sirg-num")) { if (alvo.dataset.pode === "1") abrirNumero(alvo); else abrirGaveta(alvo.dataset.quadro); }
      else { var f = alvo.closest(".doc-figura"); if (f) abrirGaveta((alvo.dataset && alvo.dataset.quadro) || (f.dataset.quadros || "").split(",")[0]); }
    }, 450);
  }

  // ---- cliques --------------------------------------------------------------------------------------------
  document.addEventListener("click", function (e) {
    if (pop && pop.contains(e.target)) return;
    var dc = e.target.closest(".quadro-desc-curta");
    if (dc) { dc.classList.toggle("aberta"); return; }
    var c = e.target.closest(".folha .sirg-campo.pode");
    if (c) { e.preventDefault(); abrirCampo(c); return; }
    var n = e.target.closest(".folha .sirg-num[data-pode='1']");
    if (n) { e.preventDefault(); abrirNumero(n); return; }
    var tot = e.target.closest(".pg .sirg-num.pendente[data-quadro]");     // total ainda vazio: abre a tabela dele
    if (tot) { e.preventDefault(); abrirGaveta(tot.dataset.quadro); return; }
    var bt = e.target.closest(".js-dados");
    if (bt) { abrirGaveta(bt.dataset.quadro); return; }
    var card = e.target.closest(".doc-figura.com-dados .destaque[data-quadro]");
    if (card) { abrirGaveta(card.dataset.quadro); return; }
    var fig = e.target.closest(".doc-figura.com-dados");
    if (fig && !e.target.closest("a, button")) { abrirGaveta((fig.dataset.quadros || "").split(",")[0]); return; }
    var fs = e.target.closest(".js-faltam-sec");
    if (fs) { irParaProximo(fs.closest(".sec-card")); return; }
    if (e.target.closest(".js-faltam")) { irParaProximo(document); return; }
    var dq = e.target.closest(".js-dados-secao");
    if (dq) { abrirGaveta(dq.dataset.quadro); return; }
    if (pop) fecharPop();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && gaveta && !gaveta.hidden && !pop && !document.querySelector(".modal.show")) fecharGaveta();
    var c = e.target.closest && e.target.closest(".sirg-campo.pode, .sirg-num[data-pode='1']");
    if (c && (e.key === "Enter" || e.key === " ") && !c.closest("[contenteditable=true]")) {
      e.preventDefault();
      if (c.classList.contains("sirg-campo")) abrirCampo(c); else abrirNumero(c);
    }
  });
  window.addEventListener("resize", fecharPop);

  // dica do alto: some depois que a pessoa fecha
  var dica = document.querySelector(".js-dica-topo");
  try { if (dica && localStorage.getItem("sirg-dica-212") === "1") dica.remove(); } catch (e) { /* sem armazenamento */ }
  var fd = document.querySelector(".js-dica-fechar");
  if (fd) fd.addEventListener("click", function () {
    var d = fd.closest(".js-dica-topo"); if (d) d.remove();
    try { localStorage.setItem("sirg-dica-212", "1"); } catch (e) { /* sem armazenamento */ }
  });
  // campos que a pessoa pode preencher entram na ordem do Tab
  document.querySelectorAll(".sirg-campo.pode, .sirg-num[data-pode='1']").forEach(function (s) { if (!s.closest("[contenteditable=true]")) s.tabIndex = 0; });

  // vindo de "O que falta": abre direto os dados da tabela
  var mDados = location.search.match(/[?&]dados=(\d+)/);
  if (mDados) setTimeout(function () { abrirGaveta(mDados[1]); }, 600);

  window.SIRGPreencher = { abrirGaveta: abrirGaveta, fecharGaveta: fecharGaveta, proximo: irParaProximo };
})();
