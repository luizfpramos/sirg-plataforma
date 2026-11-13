/*
 * Controle de alterações e comentários do SiRG (como no Word).
 *
 * - Com o controle ligado, o que a pessoa digita entra como inserção (<ins>, sublinhado em verde) e o que ela
 *   apaga continua no texto, riscado (<del>, em vermelho), com o nome de quem fez e quando. Enter, negrito,
 *   listas e títulos passam direto (só mudam a forma, não o texto).
 * - Cada alteração é aceita ou recusada separadamente: no próprio texto (clicando nela) ou no painel de revisão.
 * - Comentários ficam presos a um trecho selecionado, com respostas e "resolver".
 *
 * Usa o estado do editor de documento (escrever.js), que chama SIRGRevisao.ligar({...}).
 */
window.SIRGRevisao = (function () {
  "use strict";
  var T = window.SIRGTexto;
  var CFG = T.cfg;
  var base = T.base;
  var EU = CFG.usuario || { id: 0, nome: "" };
  var ed = null;          // ponte com o editor: { ativo(), mudou(tipo), fechar(), abrir(area) }

  // ---- utilidades de DOM ---------------------------------------------------------------------------
  var BLOCO = /^(P|LI|H3|H4|BLOCKQUOTE|TD|TH|DIV)$/;
  function acima(no, tag, limite) {
    var n = no && (no.nodeType === 1 ? no : no.parentNode);
    tag = tag.toUpperCase();
    while (n && n !== limite) {
      if (n.nodeName === tag) return n;
      if (n.classList && n.classList.contains("doc-texto")) return null;
      n = n.parentNode;
    }
    return null;
  }
  function minha(el) { return !!el && el.getAttribute("data-u") === String(EU.id); }
  function novoId() { return (Date.now().toString(36) + Math.random().toString(36).slice(2, 7)).slice(-12); }
  function agora() { return new Date().toISOString().slice(0, 19) + "Z"; }
  function criar(tag, id) {
    var el = document.createElement(tag);
    el.setAttribute("data-s", id);
    el.setAttribute("data-u", String(EU.id));
    el.setAttribute("data-a", EU.nome);
    el.setAttribute("data-d", agora());
    return el;
  }
  function attrsIns(id) {
    return 'data-s="' + id + '" data-u="' + EU.id + '" data-a="' + T.esc(EU.nome) + '" data-d="' + agora() + '"';
  }
  function atomico(n) {
    return n.nodeType === 1 && (n.nodeName === "IMG" || n.nodeName === "BR" ||
      (n.nodeName === "SPAN" && (n.classList.contains("sirg-num") || n.classList.contains("sirg-campo"))));
  }
  function desembrulhar(el) {
    var pai = el.parentNode;
    if (!pai) return;
    while (el.firstChild) pai.insertBefore(el.firstChild, el);
    pai.removeChild(el);
  }
  function vazio(el) { return !el.textContent && !el.querySelector("img, br, .sirg-num, .sirg-campo"); }
  function blocoDe(no, area) {
    var n = no.nodeType === 1 ? no : no.parentNode;
    while (n && n !== area) { if (BLOCO.test(n.nodeName)) return n; n = n.parentNode; }
    return area;
  }
  function selecao(area) {
    var s = window.getSelection();
    if (!s.rangeCount) return null;
    var r = s.getRangeAt(0);
    return area.contains(r.startContainer) && area.contains(r.endContainer) ? r : null;
  }
  function porCursor(r) { var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }
  function ponto(no, off) { var r = document.createRange(); r.setStart(no, off); r.collapse(true); return r; }
  function antes(no) { var r = document.createRange(); r.setStartBefore(no); r.collapse(true); return r; }
  function depois(no) { var r = document.createRange(); r.setStartAfter(no); r.collapse(true); return r; }
  function vizinho(r, lado) {
    var c = r.startContainer, o = r.startOffset;
    if (c.nodeType === 3) {
      if (lado < 0 ? o > 0 : o < c.length) return null;
      return lado < 0 ? c.previousSibling : c.nextSibling;
    }
    return lado < 0 ? c.childNodes[o - 1] || null : c.childNodes[o] || null;
  }
  function noInicio(r, el) {
    var t = document.createRange(); t.selectNodeContents(el); t.setEnd(r.startContainer, r.startOffset);
    return t.toString() === "" && !t.cloneContents().querySelector("img, .sirg-num, .sirg-campo");
  }
  /* Divide `el` no ponto `r`: o que vem depois do ponto vai para uma cópia de `el` logo em seguida.
     Devolve o ponto entre as duas metades (fora de `el`). */
  function dividir(el, r) {
    var t = document.createRange();
    t.setStart(r.startContainer, r.startOffset);
    t.setEnd(el, el.childNodes.length);
    var resto = t.extractContents();
    var dir = el.cloneNode(false);
    dir.appendChild(resto);
    el.parentNode.insertBefore(dir, el.nextSibling);
    var p = depois(el);
    if (vazio(dir)) dir.parentNode.removeChild(dir);
    if (vazio(el)) { p = antes(el); el.parentNode.removeChild(el); }
    return p;
  }

  // ---- inserir com controle ------------------------------------------------------------------------------
  function textoDepois(r, area) {
    var b = blocoDe(r.startContainer, area);
    var t = document.createRange(); t.setStart(r.startContainer, r.startOffset); t.setEnd(b, b.childNodes.length);
    return t.toString();
  }
  function charAntes(r) {
    if (r.startContainer.nodeType === 3 && r.startOffset > 0) return r.startContainer.data.charAt(r.startOffset - 1);
    var v = vizinho(r, -1);
    var t = v ? v.textContent : "";
    return t ? t.charAt(t.length - 1) : "";
  }
  /* Acha onde a inserção entra a partir do ponto `r`: fora de trechos riscados, fora da inserção de outra pessoa
     e, se houver, dentro da inserção vizinha de quem está escrevendo. Devolve {r, ins, id}. */
  function lugarDaInsercao(r, area, id) {
    // dentro de um trecho riscado: o texto novo vai para depois dele (ou antes, se o cursor está no começo)
    var d = acima(r.startContainer, "del", area);
    while (d) { r = noInicio(r, d) ? antes(d) : depois(d); d = acima(r.startContainer, "del", area); }
    var ins = acima(r.startContainer, "ins", area);
    if (ins && !minha(ins)) { r = dividir(ins, r); ins = null; }
    if (!ins) {
      // logo antes de um trecho riscado (depois do Backspace): escreve depois dele, como no Word
      var v = vizinho(r, 1), a = vizinho(r, -1);
      if (v && v.nodeName === "DEL" && !(a && a.nodeName === "INS" && minha(a))) {
        while (v && v.nodeName === "DEL") { r = depois(v); v = vizinho(r, 1); }
      }
      a = vizinho(r, -1); v = vizinho(r, 1);
      if (a && a.nodeName === "INS" && minha(a) && (!id || a.getAttribute("data-s") === id || !textoRiscadoAntes(a))) {
        ins = a; r = ponto(a, a.childNodes.length);
      } else if (v && v.nodeName === "INS" && minha(v) && (!id || v.getAttribute("data-s") === id)) {
        ins = v; r = ponto(v, 0);
      }
    }
    if (!ins && !id) {
      // logo depois de um trecho que a pessoa acabou de riscar: vira uma troca só ("trocou X por Y")
      var pv = vizinho(r, -1);
      if (pv && pv.nodeName === "DEL" && minha(pv) &&
          !area.querySelector('ins[data-s="' + pv.getAttribute("data-s") + '"]')) id = pv.getAttribute("data-s");
    }
    return { r: r, ins: ins, id: id };
  }
  /* Insere `texto` no ponto `r` (fechado) como inserção de quem está escrevendo. Devolve o ponto depois do texto. */
  function inserirNoPonto(r, texto, area, id) {
    var l = lugarDaInsercao(r, area, id);
    r = l.r;
    var ins = l.ins;
    if (texto === " " && (/[\s\u00a0]/.test(charAntes(r)) || !textoDepois(r, area))) texto = "\u00a0";
    if (!ins) {
      ins = criar("ins", l.id || novoId());
      ins.appendChild(document.createTextNode(texto));
      r.insertNode(ins);
      return ponto(ins.firstChild, texto.length);
    }
    var c = r.startContainer, o = r.startOffset;
    if (c.nodeType !== 3) {
      var prev = c.childNodes[o - 1];
      if (prev && prev.nodeType === 3) { c = prev; o = prev.length; }
      else { var tn = document.createTextNode(""); c.insertBefore(tn, c.childNodes[o] || null); c = tn; o = 0; }
    }
    // espaço sem quebra que ficou para trás vira espaço comum quando a palavra continua
    if (texto !== "\u00a0" && o > 0 && c.data.charAt(o - 1) === "\u00a0" && !/[\s\u00a0]/.test(c.data.charAt(o - 2) || "x")) {
      c.replaceData(o - 1, 1, " ");
    }
    c.insertData(o, texto);
    return ponto(c, o + texto.length);
  }
  /* Insere um pedaço de HTML (número vivo, imagem) no cursor, como inserção. */
  function inserirHTML(a, html) {
    a.area.focus({ preventScroll: true });
    var r = selecao(a.area);
    if (!r) { r = document.createRange(); var ult = a.area.lastElementChild || a.area; r.selectNodeContents(ult); r.collapse(false); }
    if (!r.collapsed) { var t = apagarFaixa(r.cloneRange(), a.area, false); if (t) r = t; }
    var tmp = document.createElement("div");
    tmp.innerHTML = html;
    var frag = document.createDocumentFragment();
    while (tmp.firstChild) frag.appendChild(tmp.firstChild);
    var ultimo = frag.lastChild;
    var l = lugarDaInsercao(r.cloneRange(), a.area, null);
    if (l.ins) l.r.insertNode(frag);
    else { var ins = criar("ins", l.id || novoId()); ins.appendChild(frag); l.r.insertNode(ins); }
    var fim = document.createRange();
    if (ultimo.nodeType === 3) fim.setStart(ultimo, ultimo.length); else fim.setStartAfter(ultimo);
    fim.collapse(true);
    porCursor(fim);
    ed && ed.mudou("insertHTML");
  }
  function textoRiscadoAntes(ins) { var p = ins.previousSibling; return !!(p && p.nodeName === "DEL"); }

  // ---- apagar com controle ---------------------------------------------------------------------------------
  function unidades(r, area) {
    // separa os textos nas pontas do intervalo e devolve os pedaços (texto, número vivo, imagem) dentro dele
    if (r.startContainer === r.endContainer && r.startContainer.nodeType === 3) {
      var t0 = r.startContainer, a0 = r.startOffset, b0 = r.endOffset;
      if (b0 < t0.length) t0.splitText(b0);
      var meio = a0 > 0 ? t0.splitText(a0) : t0;
      r.setStart(meio, 0); r.setEnd(meio, meio.length);
    } else {
      if (r.endContainer.nodeType === 3 && r.endOffset > 0 && r.endOffset < r.endContainer.length) {
        r.endContainer.splitText(r.endOffset);
      }
      if (r.startContainer.nodeType === 3 && r.startOffset > 0 && r.startOffset < r.startContainer.length) {
        var t1 = r.startContainer.splitText(r.startOffset);
        var fim = r.endContainer === r.startContainer ? null : [r.endContainer, r.endOffset];
        r.setStart(t1, 0);
        if (fim) r.setEnd(fim[0], fim[1]); else r.setEnd(t1, t1.length);
      }
    }
    var out = [];
    var raiz = r.commonAncestorContainer.nodeType === 3 ? r.commonAncestorContainer.parentNode : r.commonAncestorContainer;
    var w = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: function (n) {
        if (n.nodeType === 1) return atomico(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        if (n.parentNode && n.parentNode.closest && n.parentNode.closest(".sirg-num, .sirg-campo")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      } });
    var n = r.commonAncestorContainer.nodeType === 3 ? r.commonAncestorContainer : w.nextNode();
    if (r.commonAncestorContainer.nodeType === 3) { if (n.length) out.push(n); return out; }
    while (n) {
      var dentro = false;
      try {
        var t = document.createRange(); t.selectNode(n);
        dentro = r.compareBoundaryPoints(Range.START_TO_START, t) <= 0 && r.compareBoundaryPoints(Range.END_TO_END, t) >= 0;
      } catch (e) { dentro = false; }
      if (dentro && area.contains(n)) {
        if (n.nodeType === 3) {
          // espaços de formatação entre parágrafos não são texto
          if (n.length && !(n.parentNode === area && !n.data.trim())) out.push(n);
        } else out.push(n);
      }
      n = w.nextNode();
    }
    return out;
  }
  /* Marca o intervalo `r` como removido. Devolve o ponto onde o cursor deve ficar, ou null se não havia texto. */
  function apagarFaixa(r, area, paraTras, id) {
    var us = unidades(r, area);
    if (!us.length) return null;
    var primeiro = us[0], ultimo = us[us.length - 1];
    var riscadas = us.filter(function (u) { return acima(u, "del", area); });
    if (riscadas.length === us.length) {             // já estava tudo riscado: só passa o cursor por cima
      return paraTras ? antes(acima(primeiro, "del", area)) : depois(acima(ultimo, "del", area));
    }
    // id: continua a remoção vizinha de quem está escrevendo (Backspace seguido), senão uma nova
    if (!id) {
      var cand = paraTras ? ultimo.nextSibling : primeiro.previousSibling;
      id = cand && cand.nodeName === "DEL" && minha(cand) ? cand.getAttribute("data-s") : novoId();
    }
    var marcaAtual = null, insVazios = [];
    var antesDoPrimeiro = null, depoisDoUltimo = null;
    us.forEach(function (u) {
      var ins = acima(u, "ins", area);
      if (ins) {                                     // texto que ainda era sugestão: sai de verdade
        if (!antesDoPrimeiro) antesDoPrimeiro = antes(u);
        u.parentNode.removeChild(u);
        if (insVazios.indexOf(ins) < 0) insVazios.push(ins);
        marcaAtual = null;
        return;
      }
      if (acima(u, "del", area)) { marcaAtual = null; return; }
      if (marcaAtual && marcaAtual.parentNode === u.parentNode && u.previousSibling === marcaAtual) {
        marcaAtual.appendChild(u);
      } else {
        var p = u.previousSibling;
        if (p && p.nodeName === "DEL" && p.getAttribute("data-s") === id) { marcaAtual = p; p.appendChild(u); }
        else { marcaAtual = criar("del", id); u.parentNode.insertBefore(marcaAtual, u); marcaAtual.appendChild(u); }
      }
      var nx = marcaAtual.nextSibling;
      if (nx && nx.nodeName === "DEL" && nx.getAttribute("data-s") === id) {
        while (nx.firstChild) marcaAtual.appendChild(nx.firstChild);
        nx.parentNode.removeChild(nx);
      }
      if (!antesDoPrimeiro) antesDoPrimeiro = antes(marcaAtual);
      depoisDoUltimo = depois(marcaAtual);
    });
    insVazios.forEach(function (i) { if (i.parentNode && vazio(i)) i.parentNode.removeChild(i); });
    if (paraTras) {
      var d0 = acima(primeiro, "del", area);
      return d0 ? antes(d0) : (antesDoPrimeiro || depoisDoUltimo);
    }
    var d1 = ultimo.parentNode ? acima(ultimo, "del", area) : null;
    return d1 ? depois(d1) : (depoisDoUltimo || antesDoPrimeiro);
  }

  function faixaDoApagar(e, area) {
    var tr = e.getTargetRanges ? e.getTargetRanges() : [];
    if (tr && tr.length) {
      var r = document.createRange();
      try { r.setStart(tr[0].startContainer, tr[0].startOffset); r.setEnd(tr[0].endContainer, tr[0].endOffset); }
      catch (x) { r = null; }
      if (r && !r.collapsed && area.contains(r.startContainer) && area.contains(r.endContainer)) return r;
    }
    var s = window.getSelection();
    if (!s.rangeCount) return null;
    if (!s.isCollapsed) return s.getRangeAt(0).cloneRange();
    if (!s.modify) return null;
    var guarda = s.getRangeAt(0).cloneRange();
    var para = /Backward/.test(e.inputType) ? "backward" : "forward";
    var und = /Word/.test(e.inputType) ? "word" : /(Soft|Hard)Line/.test(e.inputType) ? "lineboundary" : "character";
    s.modify("extend", para, und);
    var r2 = s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
    porCursor(guarda);
    return r2 && !r2.collapsed ? r2 : null;
  }

  // ---- eventos do teclado -----------------------------------------------------------------------------------
  function alvo(e) {
    var a = ed && ed.ativo();
    if (!a || !a.rastrear || !e.target.closest || !e.target.closest(".doc-texto.ativo")) return null;
    return a;
  }
  function trocarSelecao(a, paraTras) {
    var r = selecao(a.area);
    if (!r || r.collapsed) return null;
    var id = novoId();
    var p = apagarFaixa(r.cloneRange(), a.area, !!paraTras, id);
    if (p) porCursor(p);
    return { id: id, ponto: p };
  }
  document.addEventListener("beforeinput", function (e) {
    var a = alvo(e);
    if (!a) return;
    var t = e.inputType;
    if (t === "insertText" || t === "insertReplacementText") {
      var texto = e.data != null ? e.data : (e.dataTransfer ? e.dataTransfer.getData("text/plain") : "");
      if (!texto) return;
      e.preventDefault();
      var id = null;
      if (t === "insertReplacementText" && e.getTargetRanges && e.getTargetRanges().length) {
        var tr = e.getTargetRanges()[0], r0 = document.createRange();
        r0.setStart(tr.startContainer, tr.startOffset); r0.setEnd(tr.endContainer, tr.endOffset);
        porCursor(r0);
      }
      var troca = trocarSelecao(a, false);
      if (troca) id = troca.id;
      var r = selecao(a.area);
      if (!r) return;
      porCursor(inserirNoPonto(r.cloneRange(), texto.replace(/\r?\n/g, " "), a.area, id));
      ed.mudou("insertText");
      return;
    }
    if (/^delete/.test(t)) {
      var faixa = faixaDoApagar(e, a.area);
      if (!faixa) return;
      var p = apagarFaixa(faixa, a.area, /Backward/.test(t));
      if (!p) return;                               // só junta parágrafos (Backspace no início): passa direto
      e.preventDefault();
      porCursor(p);
      ed.mudou("deleteContentBackward");
      return;
    }
    if (t === "insertParagraph" || t === "insertLineBreak") {
      var s = window.getSelection();
      if (s.rangeCount && !s.isCollapsed) {
        e.preventDefault();
        trocarSelecao(a, false);
        setTimeout(function () { document.execCommand(t); ed.mudou(t); }, 0);
      }
      return;
    }
    if (t === "insertFromDrop" || t === "deleteByDrag") { e.preventDefault(); return; }
  }, true);
  // acentos com tecla morta / teclados de composição: a seleção vira remoção antes de compor
  document.addEventListener("keydown", function (e) {
    var a = alvo(e);
    if (!a || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Dead" || e.key === "Process") {
      var s = window.getSelection();
      if (s.rangeCount && !s.isCollapsed) { trocarSelecao(a, false); ed.mudou("deleteContentBackward"); }
    }
  }, true);
  document.addEventListener("compositionend", function (e) {
    var a = alvo(e);
    if (!a || !e.data) return;
    var s = window.getSelection();
    if (!s.rangeCount) return;
    var c = s.focusNode, o = s.focusOffset;
    if (!c || c.nodeType !== 3 || o < e.data.length || c.data.slice(o - e.data.length, o) !== e.data) return;
    var ins = acima(c, "ins", a.area);
    if (ins && minha(ins) && !acima(c, "del", a.area)) return;     // já está dentro de uma inserção sua
    // tira o texto composto do lugar e insere de novo, com controle
    c.deleteData(o - e.data.length, e.data.length);
    porCursor(inserirNoPonto(ponto(c, o - e.data.length), e.data, a.area, null));
    ed.mudou("insertText");
  }, true);
  document.addEventListener("dragstart", function (e) { if (alvo(e)) e.preventDefault(); }, true);

  /* Colar com o controle ligado: entra como texto simples, marcado como inserção. */
  function colar(a, texto) {
    var troca = trocarSelecao(a, false);
    var id = troca ? troca.id : novoId();
    var pars = texto.replace(/\r/g, "").split(/\n\s*\n/).map(function (p) { return p.replace(/\s*\n\s*/g, " ").trim(); })
      .filter(Boolean);
    pars.forEach(function (p, i) {
      if (i > 0) document.execCommand("insertParagraph");
      var r = selecao(a.area);
      if (r) porCursor(inserirNoPonto(r.cloneRange(), p, a.area, id));
    });
    ed.mudou("insertFromPaste");
  }
  /* HTML de uma inserção (número vivo, imagem), já com quem inseriu. */
  function embrulhar(html) { return "<ins " + attrsIns(novoId()) + ">" + html + "</ins>"; }
  function apagarSelecao(a) { var t = trocarSelecao(a, false); return !!t; }
  /* Troca (CEFET-MG → UFCIMG) como alteração controlada: risca o antigo e insere o novo. */
  function trocar(el, novo) {
    var id = novoId();
    var d = criar("del", id), i = criar("ins", id);
    d.textContent = el.textContent;
    i.textContent = novo;
    el.parentNode.insertBefore(d, el);
    el.parentNode.insertBefore(i, el);
    el.parentNode.removeChild(el);
  }

  // ---- aceitar e recusar ------------------------------------------------------------------------------------
  function resolverNoDom(area, ids, aceitar) {
    var n = 0;
    area.querySelectorAll("ins[data-s], del[data-s]").forEach(function (el) {
      if (ids && ids.indexOf(el.getAttribute("data-s")) < 0) return;
      n++;
      if ((el.nodeName === "INS") !== !!aceitar) el.parentNode.removeChild(el); else desembrulhar(el);
    });
    area.querySelectorAll("p, li, h3, h4").forEach(function (b) { if (vazio(b) && b.parentNode) b.parentNode.removeChild(b); });
    area.normalize();
    return n;
  }
  function areaDoBloco(id) { return document.querySelector('.doc-bloco[data-bloco="' + id + '"] .texto-rg'); }
  function resolver(blocoId, ids, aceitar) {
    var a = ed && ed.ativo();
    if (a && String(a.id) === String(blocoId)) {
      if (resolverNoDom(a.area, ids, aceitar)) ed.mudou("resolver");
      atualizarLogo();
      return Promise.resolve(true);
    }
    return T.post(base + "revisao/resolver/", { bloco: blocoId, ids: ids, aceitar: aceitar }).then(function (r) {
      if (!r.ok) { T.aviso(r.erro || "Não foi possível.", "danger"); return false; }
      aplicarBlocos(r.blocos);
      return true;
    });
  }
  function resolverSecao(secao, aceitar) {
    var a = ed && ed.ativo();
    var antes = a && String(a.secao) === String(secao) ? ed.fechar() : Promise.resolve(true);
    return antes.then(function (ok) {
      if (ok === false) return false;
      return T.post(base + "revisao/resolver/", { secao: secao, aceitar: aceitar }).then(function (r) {
        if (!r.ok) { T.aviso(r.erro || "Não foi possível.", "danger"); return false; }
        aplicarBlocos(r.blocos);
        T.aviso(r.n + " alteraç" + (r.n === 1 ? "ão " : "ões ") + (aceitar ? "aceita" : "recusada") + (r.n === 1 ? "" : "s") + "." +
          (r.avisos && r.avisos.length ? " " + r.avisos[0] : ""), r.avisos && r.avisos.length ? "warning" : "success");
        return true;
      });
    });
  }
  function aplicarBlocos(blocos) {
    Object.keys(blocos || {}).forEach(function (id) {
      var area = areaDoBloco(id);
      if (!area) return;
      area.innerHTML = blocos[id].html;
      if (area.dataset) area.dataset.versao = blocos[id].versao;
      area.classList.toggle("vazio", !blocos[id].html);
    });
    atualizarLogo();
  }

  // ---- lista das alterações do documento --------------------------------------------------------------------
  function secaoDe(el) {
    var s = el.closest("[data-secao]");
    var sec = el.closest(".doc-sec, .doc-cap");
    var h = sec ? sec.querySelector(".doc-h-sec, .doc-h-sub, .doc-h-cap") : null;
    var card = el.closest(".sec-card, .pg-cx, .pg-obj");      // nas páginas do RG, cada caixa diz de quem é
    var podeEscrever = !!(card && card.classList.contains("pode"));
    var comTitulo = el.closest("[data-titulo]");
    return { pk: s ? s.getAttribute("data-secao") : "",
             titulo: h ? h.textContent.trim() : (comTitulo ? comTitulo.getAttribute("data-titulo") : ""),
             pode: podeEscrever && !!CFG.master, escreve: podeEscrever };
  }
  function alteracoes() {
    var mapa = {}, lista = [];
    document.querySelectorAll(".folha .texto-rg").forEach(function (area) {
      var bl = area.closest(".doc-bloco");
      if (!bl) return;
      area.querySelectorAll("ins[data-s], del[data-s]").forEach(function (el) {
        var id = el.getAttribute("data-s"), k = bl.dataset.bloco + ":" + id;
        var it = mapa[k];
        if (!it) {
          var sc = secaoDe(bl);
          it = mapa[k] = { id: id, bloco: bl.dataset.bloco, el: el, autor: el.getAttribute("data-a") || "?",
            autorId: el.getAttribute("data-u"), data: el.getAttribute("data-d") || "", inserido: "", removido: "",
            secao: sc.pk, secaoTitulo: sc.titulo, pode: sc.pode,
            desfazer: !sc.pode && sc.escreve && el.getAttribute("data-u") === String(EU.id) };
          lista.push(it);
        }
        var t = el.textContent || (el.querySelector("img") ? "[imagem]" : "");
        if (el.nodeName === "INS") it.inserido += t; else it.removido += t;
      });
    });
    lista.forEach(function (it) { it.inserido = it.inserido.replace(/\s+/g, " ").trim(); it.removido = it.removido.replace(/\s+/g, " ").trim(); });
    return lista;
  }

  // ---- comentários: destaque do trecho -------------------------------------------------------------------------
  var comentarios = [];
  var temHighlight = !!(window.CSS && CSS.highlights && window.Highlight);
  function mapaTexto(area) {
    // texto do trecho com os espaços juntados, e a posição de cada letra no DOM
    var txt = "", mapa = [], ultimoEspaco = true;
    var w = document.createTreeWalker(area, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = w.nextNode())) {
      var d = n.data;
      for (var i = 0; i < d.length; i++) {
        var ch = d.charAt(i);
        if (/[\s ]/.test(ch)) {
          if (ultimoEspaco) continue;
          ch = " "; ultimoEspaco = true;
        } else ultimoEspaco = false;
        txt += ch; mapa.push([n, i]);
      }
    }
    return { txt: txt, mapa: mapa };
  }
  function normalizar(s) { return (s || "").replace(/[\s ]+/g, " "); }
  function faixaDoComentario(c) {
    if (!c.bloco || !c.trecho) return null;
    var area = areaDoBloco(c.bloco);
    if (!area) return null;
    var m = mapaTexto(area), tr = normalizar(c.trecho).trim();
    if (!tr) return null;
    var i = -1;
    var an = normalizar(c.antes);
    if (an) { var j = m.txt.indexOf(an + tr); if (j >= 0) i = j + an.length; }
    if (i < 0) i = m.txt.indexOf(tr);
    if (i < 0) return null;
    var a = m.mapa[i], b = m.mapa[i + tr.length - 1];
    if (!a || !b) return null;
    var r = document.createRange();
    try { r.setStart(a[0], a[1]); r.setEnd(b[0], b[1] + 1); } catch (e) { return null; }
    return r;
  }
  function destacar() {
    comentarios.forEach(function (c) { c.faixa = c.resolvido ? null : faixaDoComentario(c); });
    if (!temHighlight) return;
    var h = new Highlight(), h2 = new Highlight();
    comentarios.forEach(function (c) {
      if (!c.faixa) return;
      (String(c.id) === String(painel.ativo) ? h2 : h).add(c.faixa);
    });
    CSS.highlights.set("sirg-coment", h);
    CSS.highlights.set("sirg-coment-ativo", h2);
  }
  function carregarComentarios() {
    return T.get(base + "revisao/comentarios/").then(function (j) {
      comentarios = j.comentarios || [];
      destacar();
      desenhar();
    }).catch(function () { /* sem rede: tenta depois */ });
  }

  // ---- painel de revisão -----------------------------------------------------------------------------------------
  var painel = { el: document.getElementById("doc-revisao"), aba: "sugestoes", ativo: null, resolvidos: false, novo: null };
  var corpo = document.getElementById("doc-corpo");
  function abrirPainel(aba) {
    if (!painel.el) return;
    if (aba) painel.aba = aba;
    painel.el.hidden = false;
    if (corpo) corpo.classList.add("com-revisao");
    desenhar();
  }
  function fecharPainel() {
    if (!painel.el) return;
    painel.el.hidden = true;
    painel.novo = null;
    if (corpo) corpo.classList.remove("com-revisao");
  }
  function dataBR(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  function iniciais(nome) {
    var p = (nome || "?").trim().split(/\s+/);
    return ((p[0] || "?").charAt(0) + (p.length > 1 ? p[p.length - 1].charAt(0) : "")).toUpperCase();
  }
  function corta(t, n) { t = t || ""; return t.length > n ? t.slice(0, n - 1) + "…" : t; }
  function descricao(it) {
    if (it.inserido && it.removido) return 'Trocou <del>' + T.esc(corta(it.removido, 90)) + '</del> por <ins>' + T.esc(corta(it.inserido, 140)) + "</ins>";
    if (it.inserido) return 'Inseriu <ins>' + T.esc(corta(it.inserido, 200)) + "</ins>";
    if (!it.removido) return "Apagou um espaço ou quebra de linha";
    return 'Apagou <del>' + T.esc(corta(it.removido, 200)) + "</del>";
  }
  var ultimaLista = [];
  function contadores(lista) {
    var nAbertos = comentarios.filter(function (c) { return !c.resolvido; }).length;
    document.querySelectorAll(".js-cont-sug").forEach(function (b) {
      b.querySelector("span").textContent = lista.length + " alteraç" + (lista.length === 1 ? "ão" : "ões");
      b.classList.toggle("tem", lista.length > 0);
    });
    document.querySelectorAll(".js-cont-com").forEach(function (b) {
      b.querySelector("span").textContent = nAbertos + " comentário" + (nAbertos === 1 ? "" : "s");
      b.classList.toggle("tem", nAbertos > 0);
    });
    if (!painel.el) return;
    painel.el.querySelector(".js-aba-n-sug").textContent = lista.length;
    painel.el.querySelector(".js-aba-n-com").textContent = nAbertos;
  }
  function desenhar() {
    var lista = alteracoes();
    ultimaLista = lista;
    contadores(lista);
    if (!painel.el || painel.el.hidden) return;
    painel.el.querySelectorAll("[data-aba]").forEach(function (b) {
      var on = b.dataset.aba === painel.aba;
      b.classList.toggle("active", on); b.setAttribute("aria-selected", on ? "true" : "false");
    });
    var alvoEl = painel.el.querySelector(".js-rev-lista");
    alvoEl.innerHTML = painel.aba === "sugestoes" ? htmlSugestoes(lista) : htmlComentarios();
    var foco = alvoEl.querySelector(".js-novo-texto");
    if (foco && painel.novo && painel.novo.focar) { painel.novo.focar = false; foco.focus(); }
  }
  function htmlSugestoes(lista) {
    if (!lista.length) return '<div class="rev-vazio"><i class="bi bi-check2-all"></i> Nenhuma alteração esperando revisão.' +
      '<div class="mini mt-2">Ligue o <strong>Controle de alterações</strong> no alto para que o que você digitar ou apagar fique marcado, com o seu nome.</div></div>';
    var h = "", sec = null;
    lista.forEach(function (it) {
      if (it.secao !== sec) {
        if (sec !== null) h += "</div>";
        sec = it.secao;
        var daSecao = lista.filter(function (x) { return x.secao === sec; });
        h += '<div class="rev-grupo"><div class="rev-grupo-cab"><span>' + T.esc(it.secaoTitulo || "Seção") + "</span>" +
          (it.pode && daSecao.length > 1 ? '<span class="rev-grupo-acoes"><button type="button" class="btn btn-link btn-sm p-0 js-sec-aceitar" data-secao="' + T.esc(sec) + '">Aceitar as ' + daSecao.length + '</button> · <button type="button" class="btn btn-link btn-sm p-0 text-danger js-sec-recusar" data-secao="' + T.esc(sec) + '">Recusar</button></span>' : "") + "</div>";
      }
      h += '<div class="rev-item js-ir-sug" data-bloco="' + T.esc(it.bloco) + '" data-id="' + T.esc(it.id) + '" tabindex="0">' +
        '<div class="rev-quem"><span class="rev-av' + (it.autorId === String(EU.id) ? " eu" : "") + '">' + T.esc(iniciais(it.autor)) + '</span><strong>' + T.esc(it.autor) + '</strong><span class="mini text-secondary ms-auto">' + T.esc(dataBR(it.data)) + "</span></div>" +
        '<div class="rev-desc">' + descricao(it) + "</div>" +
        (it.pode ? '<div class="rev-acoes"><button type="button" class="btn btn-sm btn-outline-success js-aceitar"><i class="bi bi-check-lg"></i> Aceitar</button><button type="button" class="btn btn-sm btn-outline-danger js-recusar"><i class="bi bi-x-lg"></i> Recusar</button></div>' :
          it.desfazer ? '<div class="rev-acoes"><button type="button" class="btn btn-sm btn-outline-secondary js-recusar" title="Volta o texto como estava"><i class="bi bi-arrow-counterclockwise"></i> Desfazer</button><span class="mini text-secondary align-self-center">O Master aceita na revisão.</span></div>' :
          '<div class="mini text-secondary mt-1">O Master aceita ou recusa na revisão.</div>') + "</div>";
    });
    return h + "</div>";
  }
  function htmlComentarios() {
    var h = "";
    if (painel.novo) {
      h += '<div class="rev-novo"><div class="mini text-secondary mb-1">Novo comentário' + (painel.novo.trecho ? " sobre:" : " neste trecho de texto") + "</div>" +
        (painel.novo.trecho ? '<blockquote class="rev-trecho">“' + T.esc(corta(painel.novo.trecho, 220)) + "”</blockquote>" : "") +
        '<textarea class="form-control form-control-sm js-novo-texto" rows="3" placeholder="Escreva o comentário" aria-label="Comentário"></textarea>' +
        '<div class="d-flex gap-2 mt-2"><button type="button" class="btn btn-sm btn-primary js-novo-enviar">Comentar</button><button type="button" class="btn btn-sm btn-link js-novo-cancelar">Cancelar</button></div></div>';
    }
    var lista = comentarios.filter(function (c) { return painel.resolvidos || !c.resolvido; });
    var nRes = comentarios.length - comentarios.filter(function (c) { return !c.resolvido; }).length;
    if (!lista.length && !painel.novo) {
      h += '<div class="rev-vazio"><i class="bi bi-chat-left"></i> Nenhum comentário aberto.<div class="mini mt-2">Selecione um trecho do texto e clique em <strong>Comentar</strong>.</div></div>';
    }
    // na ordem do documento (os que não se acham no texto vão para o fim da seção)
    var ordem = {};
    document.querySelectorAll(".folha .doc-bloco[data-bloco]").forEach(function (b, i) { ordem[b.dataset.bloco] = i; });
    lista.sort(function (a, b) {
      var oa = a.bloco != null && ordem[a.bloco] != null ? ordem[a.bloco] : 1e6, ob = b.bloco != null && ordem[b.bloco] != null ? ordem[b.bloco] : 1e6;
      if (oa !== ob) return oa - ob;
      if (a.faixa && b.faixa) return a.faixa.compareBoundaryPoints(Range.START_TO_START, b.faixa);
      return a.id - b.id;
    });
    lista.forEach(function (c) {
      var perdido = c.trecho && !c.faixa && !c.resolvido;
      h += '<div class="rev-item rev-com js-ir-com' + (String(c.id) === String(painel.ativo) ? " ativo" : "") + (c.resolvido ? " resolvido" : "") + '" data-id="' + c.id + '" tabindex="0">' +
        '<div class="mini text-secondary mb-1">' + T.esc(c.secao_titulo) + "</div>" +
        (c.trecho ? '<blockquote class="rev-trecho' + (perdido ? " perdido" : "") + '">“' + T.esc(corta(c.trecho, 160)) + "”" + (perdido ? '<span class="d-block mini">o trecho mudou depois do comentário</span>' : "") + "</blockquote>" : "") +
        '<div class="rev-quem"><span class="rev-av' + (c.meu ? " eu" : "") + '">' + T.esc(iniciais(c.autor)) + '</span><strong>' + T.esc(c.autor) + '</strong><span class="mini text-secondary ms-auto">' + T.esc(c.quando) + "</span></div>" +
        '<div class="rev-texto">' + T.esc(c.texto) + "</div>";
      (c.respostas || []).forEach(function (r) {
        h += '<div class="rev-resp"><div class="rev-quem"><span class="rev-av pq' + (r.meu ? " eu" : "") + '">' + T.esc(iniciais(r.autor)) + '</span><strong>' + T.esc(r.autor) + '</strong><span class="mini text-secondary ms-auto">' + T.esc(r.quando) + '</span></div><div class="rev-texto">' + T.esc(r.texto) + "</div></div>";
      });
      if (c.resolvido) {
        h += '<div class="mini text-secondary mt-1"><i class="bi bi-check2-circle"></i> Resolvido por ' + T.esc(c.resolvido_por) + '. <button type="button" class="btn btn-link btn-sm p-0 mini js-com-reabrir">Reabrir</button></div>';
      } else {
        h += '<div class="rev-responder"><input class="form-control form-control-sm js-resp" placeholder="Responder…" aria-label="Responder ao comentário"></div>' +
          '<div class="rev-acoes">' + (c.pode_resolver ? '<button type="button" class="btn btn-sm btn-outline-secondary js-com-resolver"><i class="bi bi-check2"></i> Resolver</button>' : "") +
          (c.meu && !(c.respostas || []).length ? '<button type="button" class="btn btn-sm btn-link text-danger js-com-excluir">Apagar</button>' : "") + "</div>";
      }
      h += "</div>";
    });
    if (nRes) h += '<div class="text-center my-2"><button type="button" class="btn btn-link btn-sm js-ver-resolvidos">' + (painel.resolvidos ? "Esconder" : "Mostrar") + " os " + nRes + " resolvido" + (nRes === 1 ? "" : "s") + "</button></div>";
    return h;
  }
  function piscar(el) {
    if (!el) return;
    el.classList.remove("rev-piscar"); void el.offsetWidth; el.classList.add("rev-piscar");
    setTimeout(function () { el.classList.remove("rev-piscar"); }, 1800);
  }
  function rolarAte(el) {
    if (!el) return;
    var r = (el.getBoundingClientRect ? el : el.startContainer.parentNode).getBoundingClientRect();
    var css = getComputedStyle(document.documentElement);
    var folga = (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90);
    window.scrollTo({ top: Math.max(0, r.top + window.scrollY - folga - (window.innerHeight - folga) / 3), behavior: "smooth" });
  }
  function irParaSugestao(blocoId, id) {
    var area = areaDoBloco(blocoId);
    if (!area) return;
    var els = area.querySelectorAll('[data-s="' + id + '"]');
    if (!els.length) return;
    rolarAte(els[0]);
    els.forEach(piscar);
  }
  function irParaComentario(c) {
    painel.ativo = c.id;
    destacar();
    if (c.faixa) {
      var r = c.faixa.getBoundingClientRect();
      var css = getComputedStyle(document.documentElement);
      var folga = (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90);
      window.scrollTo({ top: Math.max(0, r.top + window.scrollY - folga - (window.innerHeight - folga) / 3), behavior: "smooth" });
    } else if (c.bloco) {
      var b = document.getElementById("bloco-" + c.bloco);
      if (b) { rolarAte(b); piscar(b); }
    } else {
      var s = document.querySelector('[data-secao="' + c.secao + '"]');
      if (s) rolarAte(s);
    }
  }

  if (painel.el) {
    painel.el.addEventListener("click", function (e) {
      var t = e.target;
      if (t.closest(".js-rev-fechar")) { fecharPainel(); return; }
      var aba = t.closest("[data-aba]");
      if (aba) { painel.aba = aba.dataset.aba; desenhar(); return; }
      var it = t.closest(".js-ir-sug");
      if (it) {
        if (t.closest(".js-aceitar, .js-recusar")) {
          var aceitar = !!t.closest(".js-aceitar");
          resolver(it.dataset.bloco, [it.dataset.id], aceitar).then(function (ok) {
            if (ok) T.aviso(aceitar ? "Alteração aceita." : "Alteração recusada.", "success");
          });
          return;
        }
        irParaSugestao(it.dataset.bloco, it.dataset.id);
        return;
      }
      var sa = t.closest(".js-sec-aceitar, .js-sec-recusar");
      if (sa) {
        var ac = sa.classList.contains("js-sec-aceitar");
        if (confirm((ac ? "Aceitar" : "Recusar") + " todas as alterações sugeridas nesta seção?")) resolverSecao(sa.dataset.secao, ac);
        return;
      }
      if (t.closest(".js-ver-resolvidos")) { painel.resolvidos = !painel.resolvidos; desenhar(); return; }
      if (t.closest(".js-novo-cancelar")) { painel.novo = null; desenhar(); return; }
      if (t.closest(".js-novo-enviar")) { enviarNovo(); return; }
      var cm = t.closest(".js-ir-com");
      if (cm) {
        var c = comentarios.find(function (x) { return String(x.id) === cm.dataset.id; });
        if (!c) return;
        if (t.closest(".js-com-resolver")) { acaoComentario(c, "resolver"); return; }
        if (t.closest(".js-com-reabrir")) { acaoComentario(c, "reabrir"); return; }
        if (t.closest(".js-com-excluir")) { if (confirm("Apagar este comentário?")) acaoComentario(c, "excluir"); return; }
        if (t.closest(".js-resp, .rev-responder")) return;
        irParaComentario(c);
        painel.el.querySelectorAll(".js-ir-com").forEach(function (x) { x.classList.toggle("ativo", x === cm); });
      }
    });
    painel.el.addEventListener("keydown", function (e) {
      var inp = e.target.closest(".js-resp");
      if (inp && e.key === "Enter" && inp.value.trim()) {
        e.preventDefault();
        var cm = inp.closest(".js-ir-com");
        var c = comentarios.find(function (x) { return String(x.id) === cm.dataset.id; });
        T.post(base + "revisao/comentar/", { secao: c.secao, pai: c.id, texto: inp.value.trim() }).then(function (r) {
          if (!r.ok) { T.aviso(r.erro || "Não foi possível responder.", "danger"); return; }
          carregarComentarios();
        });
        return;
      }
      if (e.target.closest(".js-novo-texto") && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enviarNovo(); }
      var it = e.target.closest(".js-ir-sug, .js-ir-com");
      if (it && e.target === it && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); it.click(); }
    });
  }
  function acaoComentario(c, acao) {
    T.post(base + "revisao/comentarios/" + c.id + "/" + acao + "/", {}).then(function (r) {
      if (!r.ok) { T.aviso(r.erro || "Não foi possível.", "danger"); return; }
      if (acao === "resolver") T.aviso("Comentário resolvido.", "success");
      carregarComentarios();
    });
  }
  function enviarNovo() {
    var n = painel.novo;
    var txt = painel.el.querySelector(".js-novo-texto");
    if (!n || !txt || !txt.value.trim()) { if (txt) txt.focus(); return; }
    T.post(base + "revisao/comentar/", { secao: n.secao, bloco: n.bloco, trecho: n.trecho, antes: n.antes, texto: txt.value.trim() }).then(function (r) {
      if (!r.ok) { T.aviso(r.erro || "Não foi possível comentar.", "danger"); return; }
      painel.novo = null;
      painel.ativo = r.id;
      carregarComentarios().then(function () {
        var c = comentarios.find(function (x) { return x.id === r.id; });
        if (c) destacar();
      });
    });
  }
  /* Comentar: o trecho selecionado (ou o trecho de texto inteiro, pelo botão do trecho). */
  function comentarSelecao() {
    var s = window.getSelection();
    var r = s.rangeCount ? s.getRangeAt(0) : null;
    var area = r ? (r.commonAncestorContainer.nodeType === 1 ? r.commonAncestorContainer : r.commonAncestorContainer.parentNode).closest(".texto-rg") : null;
    if (!r || r.collapsed || !area || !area.closest(".folha")) {
      var ini = r ? (r.startContainer.nodeType === 1 ? r.startContainer : r.startContainer.parentNode).closest(".texto-rg") : null;
      T.aviso(ini && !r.collapsed ? "Selecione um trecho dentro de um mesmo texto." : "Selecione com o mouse o trecho que você quer comentar e clique em Comentar.", "dark");
      return;
    }
    var bl = area.closest(".doc-bloco");
    var m = mapaTexto(area);
    // posição da seleção no texto (com os espaços juntados)
    var ini2 = -1, fim = -1;
    for (var i = 0; i < m.mapa.length; i++) {
      var p = m.mapa[i];
      var t = document.createRange(); t.setStart(p[0], p[1]); t.setEnd(p[0], p[1] + 1);
      var dentro = r.compareBoundaryPoints(Range.START_TO_START, t) <= 0 && r.compareBoundaryPoints(Range.END_TO_END, t) >= 0;
      if (dentro) { if (ini2 < 0) ini2 = i; fim = i + 1; }
    }
    if (ini2 < 0) { T.aviso("Selecione um trecho com texto.", "dark"); return; }
    while (ini2 < fim && m.txt.charAt(ini2) === " ") ini2++;
    while (fim > ini2 && m.txt.charAt(fim - 1) === " ") fim--;
    var sc = secaoDe(bl);
    painel.novo = { secao: sc.pk, bloco: bl.dataset.bloco, trecho: m.txt.slice(ini2, fim), antes: m.txt.slice(Math.max(0, ini2 - 60), ini2), focar: true };
    abrirPainel("comentarios");
  }
  function comentarBloco(bl) {
    var sc = secaoDe(bl);
    painel.novo = { secao: sc.pk, bloco: bl.dataset.bloco, trecho: "", antes: "", focar: true };
    abrirPainel("comentarios");
  }

  // ---- selo sobre uma alteração no texto (clicar nela) ----------------------------------------------------------
  var chip = document.getElementById("chip-revisao");
  var chipAlvo = null;
  function esconderSelo() { if (chip) chip.classList.add("d-none"); chipAlvo = null; }
  function mostrarSelo(el) {
    if (!chip) return;
    var bl = el.closest(".doc-bloco");
    if (!bl) return;
    var id = el.getAttribute("data-s");
    var it = ultimaLista.find(function (x) { return x.id === id && x.bloco === bl.dataset.bloco; }) || alteracoes().find(function (x) { return x.id === id && x.bloco === bl.dataset.bloco; });
    if (!it) return;
    chipAlvo = it;
    chip.querySelector(".js-selo-quem").textContent = it.autor + (it.data ? " · " + dataBR(it.data) : "");
    chip.querySelector(".js-selo-desc").innerHTML = descricao(it);
    chip.querySelector(".js-selo-acoes").classList.toggle("d-none", !it.pode && !it.desfazer);
    chip.querySelector(".js-selo-aceitar").classList.toggle("d-none", !it.pode);
    chip.querySelector(".js-selo-recusar").innerHTML = it.pode ? '<i class="bi bi-x-lg"></i> Recusar' : '<i class="bi bi-arrow-counterclockwise"></i> Desfazer';
    chip.classList.remove("d-none");
    var rc = el.getBoundingClientRect();
    var topo = rc.bottom + window.scrollY + 6;
    chip.style.top = topo + "px";
    chip.style.left = Math.max(8, Math.min(rc.left + window.scrollX, window.innerWidth - chip.offsetWidth - 16)) + "px";
  }
  if (chip) {
    chip.addEventListener("mousedown", function (e) {
      var b = e.target.closest("button");
      if (!b || !chipAlvo) return;
      e.preventDefault();
      var it = chipAlvo;
      esconderSelo();
      resolver(it.bloco, [it.id], b.classList.contains("js-selo-aceitar"));
    });
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("#chip-revisao")) return;
    var el = e.target.closest(".folha ins[data-s], .folha del[data-s]");
    if (el) { mostrarSelo(el); } else esconderSelo();
    // clicou num trecho comentado: mostra o comentário no painel
    if (!el && e.target.closest(".folha .texto-rg") && comentarios.length) {
      var p = null;
      if (document.caretRangeFromPoint) p = document.caretRangeFromPoint(e.clientX, e.clientY);
      else if (document.caretPositionFromPoint) {
        var cp = document.caretPositionFromPoint(e.clientX, e.clientY);
        if (cp) { p = document.createRange(); p.setStart(cp.offsetNode, cp.offset); }
      }
      if (!p) return;
      var c = comentarios.find(function (x) { return x.faixa && x.faixa.isPointInRange(p.startContainer, p.startOffset); });
      if (c) {
        painel.ativo = c.id;
        abrirPainel("comentarios");
        destacar();
        var it = painel.el.querySelector('.js-ir-com[data-id="' + c.id + '"]');
        if (it) it.scrollIntoView({ block: "nearest" });
      }
    }
  });
  document.addEventListener("selectionchange", function () {
    var a = ed && ed.ativo();
    if (!a) return;
    var s = window.getSelection();
    if (!s.rangeCount || !s.isCollapsed || !a.area.contains(s.anchorNode)) return;
    var el = acima(s.anchorNode, "ins", a.area) || acima(s.anchorNode, "del", a.area);
    if (el && !minha(el)) mostrarSelo(el); else if (!el) esconderSelo();
  });

  // ---- recalcular quando o texto muda --------------------------------------------------------------------------
  var espera = null;
  function atualizarLogo() { clearTimeout(espera); espera = setTimeout(function () { destacar(); desenhar(); }, 250); }
  var folha = document.querySelector(".folha");
  if (folha && window.MutationObserver) {
    new MutationObserver(function () { atualizarLogo(); }).observe(folha, { childList: true, subtree: true, characterData: true });
  }

  // ---- ligar e desligar o controle -----------------------------------------------------------------------------
  function lerPreferencia() {
    if (CFG.rastreioObrigatorio) return true;       // quem não é Master sempre escreve com o controle ligado
    try { var v = localStorage.getItem("sirg-rastreio"); if (v === "1" || v === "0") return v === "1"; } catch (e) { /* sem armazenamento */ }
    return !!CFG.rastreioPadrao;
  }
  var ligado = lerPreferencia();
  function mostrarBotao() {
    document.querySelectorAll(".js-rastreio").forEach(function (b) {
      b.classList.toggle("on", ligado);
      b.setAttribute("aria-pressed", ligado ? "true" : "false");
      b.querySelector("span").textContent = ligado ? "Controle de alterações ligado" : "Controlar alterações";
    });
    document.documentElement.classList.toggle("rastreando", ligado);
  }
  document.querySelectorAll(".js-rastreio").forEach(function (b) {
    b.addEventListener("mousedown", function (e) { e.preventDefault(); });
    b.addEventListener("click", function () {
      ligado = !ligado;
      try { localStorage.setItem("sirg-rastreio", ligado ? "1" : "0"); } catch (e) { /* sem armazenamento */ }
      mostrarBotao();
      var a = ed && ed.ativo();
      if (a) a.rastrear = ligado;
      if (ed && ed.status) ed.status();
      T.aviso(ligado ? "Controle de alterações ligado: o que você digitar ou apagar fica marcado, com o seu nome, até alguém aceitar ou recusar."
        : "Controle de alterações desligado: você escreve direto no texto.", "dark");
    });
  });
  mostrarBotao();
  document.querySelectorAll(".js-comentar-sel").forEach(function (b) {
    b.addEventListener("mousedown", function (e) { e.preventDefault(); });
    b.addEventListener("click", comentarSelecao);
  });
  document.querySelectorAll(".js-cont-sug").forEach(function (b) { b.addEventListener("click", function () { abrirPainel("sugestoes"); }); });
  document.querySelectorAll(".js-cont-com").forEach(function (b) { b.addEventListener("click", function () { abrirPainel("comentarios"); }); });
  document.addEventListener("click", function (e) {
    if (e.target.closest(".js-cont-com-bloco")) abrirPainel("comentarios");
    if (e.target.closest(".js-cont-sug-sec")) abrirPainel("sugestoes");
  });

  carregarComentarios();
  setInterval(function () { if (!document.hidden) carregarComentarios(); }, 60000);
  desenhar();
  if (/[?&]revisao=1/.test(location.search)) abrirPainel("sugestoes");

  return {
    ligar: function (ponte) { ed = ponte; },
    get ligado() { return ligado; },
    colar: colar, embrulhar: embrulhar, apagarSelecao: apagarSelecao, trocar: trocar, inserirHTML: inserirHTML,
    comentarBloco: comentarBloco, atualizar: atualizarLogo, abrirPainel: abrirPainel,
    resolverNoDom: resolverNoDom
  };
})();
