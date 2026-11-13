/*
 * Ferramentas comuns aos editores de texto do SiRG (documento e seção):
 * avisos, chamadas ao servidor, limpeza do HTML, números vivos, imagens, desfazer e colar do Word.
 *
 * "alvo" = o trecho que está sendo editado: { area: elemento editável, bloco: id, secao: id,
 *           sujo(): marca que há alterações não salvas }.
 */
window.SIRGTexto = (function () {
  "use strict";
  var CFG = window.SIRG || {};
  var base = "/ciclos/" + CFG.ano + "/";

  var toastEl = document.getElementById("toast");
  var toast = toastEl && window.bootstrap ? bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4500 }) : null;
  function aviso(msg, tipo) {
    if (!toast) { alert(msg); return; }
    toastEl.className = "toast align-items-center border-0 text-bg-" + (tipo || "dark");
    toastEl.querySelector(".toast-body").textContent = msg;
    toast.show();
  }
  function post(url, dados, opcoes) {
    return fetch(url, Object.assign({ method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CFG.csrf }, body: JSON.stringify(dados || {}) }, opcoes || {}))
      .then(function (r) { return r.json().catch(function () { return { ok: false, erro: "Erro " + r.status }; }); })
      .catch(function () { return { ok: false, erro: "Sem conexão com o servidor. Verifique a rede e tente de novo." }; });
  }
  function get(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); });
  }

  var PERMITIDO = { ALLOWED_TAGS: ["p", "br", "strong", "b", "em", "i", "u", "s", "h3", "h4", "ul", "ol", "li", "a",
    "blockquote", "sup", "sub", "span", "mark", "table", "thead", "tbody", "tr", "th", "td", "img", "ins", "del"],
    ALLOWED_ATTR: ["href", "class", "data-ref", "data-col", "data-orig", "data-escala", "data-antes", "data-depois",
      "contenteditable", "colspan", "rowspan", "src", "alt", "data-s", "data-u", "data-a", "data-d", "data-c", "style"] };
  function limpar(html) {
    if (window.DOMPurify) return DOMPurify.sanitize(html, PERMITIDO);
    var d = document.createElement("div"); d.textContent = html; return d.innerHTML;
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function semAcento(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function palavras(el) { return (el.innerText || "").trim().split(/\s+/).filter(Boolean).length; }

  // ---- formatação ---------------------------------------------------------------------
  // "Limpar formatação" do navegador apaga as marcas <ins> (inserções sugeridas), que virariam texto aceito
  // sem ninguém aceitar. Durante o comando elas viram <del> marcadas, que ele não toca, e voltam depois.
  function trocarTag(el, tag) {
    var n = document.createElement(tag);
    for (var i = 0; i < el.attributes.length; i++) n.setAttribute(el.attributes[i].name, el.attributes[i].value);
    while (el.firstChild) n.appendChild(el.firstChild);
    el.parentNode.replaceChild(n, el);
    return n;
  }
  function protegendoInsercoes(fazer) {
    var raiz = document.activeElement && document.activeElement.closest ? document.activeElement.closest("[contenteditable=true]") : null;
    if (!raiz) { fazer(); return; }
    var sel = window.getSelection(), faixa = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
    raiz.querySelectorAll("ins[data-s]").forEach(function (el) { trocarTag(el, "del").setAttribute("data-era-ins", "1"); });
    if (faixa) { sel.removeAllRanges(); sel.addRange(faixa); }
    try { fazer(); } finally {
      raiz.querySelectorAll("del[data-era-ins]").forEach(function (el) { trocarTag(el, "ins").removeAttribute("data-era-ins"); });
    }
  }
  function formatar(cmd) {
    if (cmd === "removeFormat") { protegendoInsercoes(function () { document.execCommand("removeFormat", false, null); }); return; }
    if (cmd === "h3" || cmd === "h4" || cmd === "p" || cmd === "blockquote") document.execCommand("formatBlock", false, cmd);
    else if (cmd === "link") {
      var url = prompt("Endereço do link (começando com https://):", "https://");
      if (url && /^(https?:\/\/|mailto:)/i.test(url)) document.execCommand("createLink", false, url);
    } else document.execCommand(cmd, false, null);
  }

  // ---- números vivos ----------------------------------------------------------------------
  var numeros = null, faixa = null, alvoNum = null;
  var modalNum = document.getElementById("modal-numero");
  function abrirNumeros(alvo) {
    if (!alvo || !modalNum) return;
    alvoNum = alvo;
    var sel = window.getSelection();
    faixa = sel.rangeCount && alvo.area.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    var mostrar = function () {
      document.getElementById("numero-busca").value = "";
      desenharNumeros("");
      bootstrap.Modal.getOrCreateInstance(modalNum).show();
      setTimeout(function () { document.getElementById("numero-busca").focus(); }, 300);
    };
    if (numeros) { mostrar(); return; }
    get(base + "numeros/").then(function (j) { numeros = j.grupos; mostrar(); });
  }
  function desenharNumeros(filtro) {
    var lista = document.getElementById("numero-lista");
    var palavrasBusca = semAcento(filtro).split(/\s+/).filter(Boolean);
    var h = "";
    var preferida = alvoNum && alvoNum.secaoChave;
    var grupos = numeros.slice().sort(function (a, b) { return (b.secao_chave === preferida) - (a.secao_chave === preferida); });
    grupos.forEach(function (g) {
      var itens = g.itens.filter(function (n) {
        var onde = semAcento(g.quadro + " " + g.secao + " " + n.rotulo + " " + n.coluna);
        return palavrasBusca.every(function (p) { return onde.indexOf(p) >= 0; });   // todas as palavras, em qualquer ordem
      });
      if (!itens.length) return;
      h += '<div class="grupo-num"><div class="mini text-secondary">' + esc(g.secao) + "</div><strong>" + esc(g.quadro) + "</strong>";
      itens.forEach(function (n) {
        h += '<button type="button" class="btn btn-sm btn-light w-100 text-start d-flex js-num" data-ref="' + esc(n.ref) + '" data-col="' + esc(n.col) + '" data-valor="' + esc(n.valor) + '" data-origem="' + esc(g.quadro + " › " + n.rotulo + " (" + n.coluna + ") · " + g.secao) + '">' +
          '<span>' + esc(n.rotulo) + ' <span class="text-secondary">(' + esc(n.coluna) + ")</span></span><span class='ms-auto fw-semibold'>" + (esc(n.valor) || '<span class="text-secondary">ainda vazio</span>') + "</span></button>";
      });
      h += "</div>";
    });
    lista.innerHTML = h || '<p class="text-secondary">Nada encontrado. Tente outra palavra.</p>';
  }
  if (modalNum) {
    document.getElementById("numero-busca").addEventListener("input", function () { desenharNumeros(this.value); });
    document.getElementById("numero-lista").addEventListener("click", function (e) {
      var b = e.target.closest(".js-num");
      if (!b || !alvoNum) return;
      bootstrap.Modal.getOrCreateInstance(modalNum).hide();
      var rolagem = window.scrollY;
      alvoNum.area.focus({ preventScroll: true });       // a tela fica onde estava
      var sel = window.getSelection();
      if (faixa) { sel.removeAllRanges(); sel.addRange(faixa); }
      if (!faixa || faixa.startContainer === alvoNum.area) {
        // cursor fora de um parágrafo (ou nenhum): o número vai para o fim do último parágrafo
        var ultimo = alvoNum.area.lastElementChild || alvoNum.area;
        var r = document.createRange(); r.selectNodeContents(ultimo); r.collapse(false);
        sel.removeAllRanges(); sel.addRange(r);
      }
      var span = '<span class="sirg-num" data-ref="' + esc(b.dataset.ref) + '"' + (b.dataset.col ? ' data-col="' + esc(b.dataset.col) + '"' : "") +
        ' title="Vem de: ' + esc(b.dataset.origem || "") + '" contenteditable="false">' + esc(b.dataset.valor || "[a preencher]") + "</span>&nbsp;";
      if (alvoNum.rastrear && window.SIRGRevisao) window.SIRGRevisao.inserirHTML(alvoNum, span);   // entra como inserção
      else document.execCommand("insertHTML", false, span);
      window.scrollTo(0, rolagem);
      var s2 = window.getSelection();
      var perto = s2.rangeCount ? s2.getRangeAt(0).startContainer : null;
      var el = perto && (perto.nodeType === 1 ? perto : perto.parentNode);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
      alvoNum.sujo();
    });
  }

  // ---- imagens ------------------------------------------------------------------------------------
  var TAMANHO_MAX = 10 * 1024 * 1024;
  function guardarFaixa(area) {
    var sel = window.getSelection();
    return sel.rangeCount && area.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
  }
  function voltarFaixa(area, faixa) {
    area.focus();
    var sel = window.getSelection();
    sel.removeAllRanges();
    if (faixa && area.contains(faixa.startContainer)) { sel.addRange(faixa); return; }
    var r = document.createRange(); r.selectNodeContents(area); r.collapse(false); sel.addRange(r);
  }
  function enviarImagem(alvo, arquivo, faixa) {
    if (!alvo || !arquivo) return Promise.resolve(false);
    if (!/^image\/(png|jpe?g|gif|webp)$/i.test(arquivo.type)) { aviso("Use uma imagem PNG, JPG, GIF ou WEBP.", "warning"); return Promise.resolve(false); }
    if (arquivo.size > TAMANHO_MAX) { aviso("A imagem tem mais de 10 MB. Diminua o tamanho e tente de novo.", "warning"); return Promise.resolve(false); }
    faixa = faixa || guardarFaixa(alvo.area);
    var fd = new FormData();
    fd.append("arquivo", arquivo, arquivo.name || "imagem.png");
    if (alvo.secao) fd.append("secao", alvo.secao);
    aviso("Enviando a imagem…", "dark");
    return fetch(base + "imagens/enviar/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": CFG.csrf }, body: fd })
      .then(function (r) { return r.json().catch(function () { return { ok: false, erro: "Erro " + r.status }; }); })
      .catch(function () { return { ok: false, erro: "Sem conexão com o servidor. A imagem não foi enviada." }; })
      .then(function (r) {
        if (!r.ok) { aviso(r.erro || "Não foi possível enviar a imagem.", "danger"); return false; }
        voltarFaixa(alvo.area, faixa);
        var img = '<img src="' + esc(r.url) + '" alt="' + esc(r.nome || "") + '">';
        if (alvo.rastrear && window.SIRGRevisao) window.SIRGRevisao.inserirHTML(alvo, img);
        else document.execCommand("insertHTML", false, "<p>" + img + "</p><p><br></p>");
        alvo.sujo();
        aviso("Imagem inserida. Escreva a legenda logo abaixo dela, se quiser.", "success");
        return true;
      });
  }
  function escolherImagem(alvo) {
    if (!alvo) return;
    var faixa = guardarFaixa(alvo.area);
    var inp = document.createElement("input");
    inp.type = "file"; inp.accept = "image/png,image/jpeg,image/gif,image/webp";
    inp.addEventListener("change", function () { if (inp.files && inp.files[0]) enviarImagem(alvo, inp.files[0], faixa); });
    inp.click();
  }
  function imagensDe(dt) {
    var out = [];
    if (!dt) return out;
    Array.prototype.forEach.call(dt.files || [], function (f) { if (/^image\//.test(f.type)) out.push(f); });
    return out;
  }
  function soltar(e, alvo) {
    var imgs = imagensDe(e.dataTransfer);
    if (!imgs.length) return;
    e.preventDefault();
    var faixa = null;
    if (document.caretRangeFromPoint) faixa = document.caretRangeFromPoint(e.clientX, e.clientY);
    imgs.reduce(function (p, f) { return p.then(function () { return enviarImagem(alvo, f, faixa); }); }, Promise.resolve());
  }

  // ---- desfazer / refazer (Ctrl+Z / Ctrl+Y) ------------------------------------------------------
  // O navegador perde o "desfazer" quando o texto é salvo ou alterado pelas ferramentas (número vivo,
  // destaque, imagem). Por isso o SiRG guarda o próprio histórico de cada trecho.
  var pilhas = {};
  function caminhoCursor(area) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var r = sel.getRangeAt(0);
    if (!area.contains(r.startContainer)) return null;
    var p = [], n = r.startContainer;
    while (n && n !== area) { p.unshift(Array.prototype.indexOf.call(n.parentNode.childNodes, n)); n = n.parentNode; }
    return { p: p, o: r.startOffset };
  }
  function voltarCursor(area, c) {
    var n = area;
    if (c) {
      for (var i = 0; i < c.p.length && n; i++) n = n.childNodes[c.p[i]];
    }
    var r = document.createRange();
    try {
      if (c && n) { r.setStart(n, Math.min(c.o, n.nodeType === 3 ? n.length : n.childNodes.length)); r.collapse(true); }
      else { r.selectNodeContents(area); r.collapse(false); }
    } catch (e) { r.selectNodeContents(area); r.collapse(false); }
    var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
  }
  function foto(area) { return { html: area.innerHTML, cur: caminhoCursor(area) }; }
  function desfazerIniciar(id, area) {
    var H = pilhas[id];
    if (!H || H.marca !== limpar(area.innerHTML)) H = pilhas[id] = { pilha: [], futuro: [], t: 0 };
    H.area = area; H.estado = foto(area); H.agrupando = false;
  }
  function desfazerRegistrar(id, agrupavel) {
    var H = pilhas[id];
    if (!H || H.aplicando) return;
    if (H.area.innerHTML === H.estado.html) return;     // nada mudou desde a última foto
    var agora = Date.now();
    if (!(agrupavel && H.agrupando && agora - H.t < 1500)) {
      H.pilha.push(H.estado);
      if (H.pilha.length > 200) H.pilha.shift();
      H.futuro = [];
    }
    H.agrupando = !!agrupavel; H.t = agora;
    H.estado = foto(H.area);
  }
  function aplicarFoto(H, f) {
    H.aplicando = true;
    H.area.innerHTML = f.html;
    H.area.focus();
    voltarCursor(H.area, f.cur);
    H.estado = f; H.agrupando = false;
    H.aplicando = false;
  }
  function desfazer(id) {
    var H = pilhas[id];
    if (!H || !H.pilha.length) return false;
    H.futuro.push(foto(H.area));
    aplicarFoto(H, H.pilha.pop());
    return true;
  }
  function refazer(id) {
    var H = pilhas[id];
    if (!H || !H.futuro.length) return false;
    H.pilha.push(foto(H.area));
    aplicarFoto(H, H.futuro.pop());
    return true;
  }
  function desfazerEncerrar(id, area) { var H = pilhas[id]; if (H) H.marca = limpar(area.innerHTML); }
  /* Atalhos de teclado e comandos do navegador (menu Editar › Desfazer). Devolve true se tratou. */
  function teclaDesfazer(e, id, depois) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
    var k = e.key.toLowerCase();
    var feito = null;
    if (k === "z" && !e.shiftKey) feito = desfazer(id);
    else if (k === "y" || (k === "z" && e.shiftKey)) feito = refazer(id);
    else return false;
    e.preventDefault();
    if (feito) depois(); else aviso(k === "z" && !e.shiftKey ? "Nada para desfazer neste trecho." : "Nada para refazer.", "dark");
    return true;
  }

  // ---- colar do Word / da internet -------------------------------------------------------------
  function colar(e, alvo) {
    var cd = e.clipboardData || window.clipboardData;
    var imgs = imagensDe(cd);
    if (imgs.length && !cd.getData("text/plain")) {      // imagem copiada (print, imagem da internet)
      e.preventDefault();
      imgs.reduce(function (p, f) { return p.then(function () { return enviarImagem(alvo, f); }); }, Promise.resolve());
      return;
    }
    var html = cd.getData("text/html");
    e.preventDefault();
    if (alvo.rastrear && window.SIRGRevisao) {             // controle de alterações: entra como texto, marcado
      var tmp = document.createElement("div");
      tmp.innerHTML = html ? limpar(html.replace(/<!--[\s\S]*?-->/g, "")).replace(/<\/(p|li|h3|h4|blockquote|tr)>/g, "$&\n\n") : "";
      window.SIRGRevisao.colar(alvo, html ? tmp.textContent : cd.getData("text/plain"));
      return;
    }
    if (html) {
      document.execCommand("insertHTML", false, limpar(html.replace(/<!--[\s\S]*?-->/g, "")));
    } else {
      var t = cd.getData("text/plain");
      var partes = t.split(/\r?\n\r?\n/).map(function (p) { return "<p>" + esc(p).replace(/\r?\n/g, "<br>") + "</p>"; });
      document.execCommand("insertHTML", false, partes.join(""));
    }
    alvo.sujo();
  }

  // ---- trechos destacados para atualizar ---------------------------------------------------------
  function marcaNoCursor(area) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var n = sel.anchorNode;
    var el = n && (n.nodeType === 1 ? n : n.parentNode);
    var m = el && el.closest ? el.closest("mark.atualizar") : null;
    return m && area.contains(m) ? m : null;
  }
  function desembrulhar(m) {
    var pai = m.parentNode;
    while (m.firstChild) pai.insertBefore(m.firstChild, m);
    pai.removeChild(m);
    pai.normalize();
  }
  /* Tira o destaque do trecho onde está o cursor (ou de todos os trechos selecionados). */
  function concluirDestaque(alvo) {
    if (!alvo) return 0;
    var sel = window.getSelection();
    var marcas = [];
    var m = marcaNoCursor(alvo.area);
    if (m) marcas.push(m);
    if (sel.rangeCount && !sel.isCollapsed) {
      var r = sel.getRangeAt(0);
      alvo.area.querySelectorAll("mark.atualizar").forEach(function (x) { if (r.intersectsNode(x) && marcas.indexOf(x) < 0) marcas.push(x); });
    }
    marcas.forEach(desembrulhar);
    if (marcas.length) alvo.sujo();
    return marcas.length;
  }
  /* Destaca o texto selecionado como "precisa atualizar". */
  function destacar(alvo) {
    var sel = window.getSelection();
    if (!alvo || !sel.rangeCount || sel.isCollapsed) return false;
    var r = sel.getRangeAt(0);
    if (!alvo.area.contains(r.commonAncestorContainer)) return false;
    var m = document.createElement("mark");
    m.className = "atualizar";
    m.appendChild(r.extractContents());
    r.insertNode(m);
    alvo.sujo();
    return true;
  }

  // ---- versões de um trecho ---------------------------------------------------------------------
  function historico(id, voltarUrl) {
    get(base + "blocos/" + id + "/historico/").then(function (j) {
      var corpo = document.getElementById("hist-bloco-corpo");
      var h = "";
      j.itens.forEach(function (it, i) {
        h += '<div class="border-bottom pb-2 mb-2"><div class="d-flex gap-2 align-items-center flex-wrap"><strong>' + esc(it.quando) + "</strong><span class='mini text-secondary'>" + esc(it.quem) +
          (it.motivo ? " · " + esc(it.motivo) : "") + " · " + it.palavras + " palavras</span>";
        if (j.pode_restaurar && i > 0) {
          h += '<form method="post" class="ms-auto" action="' + base + "blocos/" + id + "/restaurar/" + it.id + '/"><input type="hidden" name="csrfmiddlewaretoken" value="' + esc(CFG.csrf) + '">' +
            (voltarUrl ? '<input type="hidden" name="voltar" value="' + esc(voltarUrl) + '">' : "") +
            '<button class="btn btn-sm btn-outline-secondary" onclick="return confirm(\'Voltar o texto para esta versão? O texto atual continua guardado no histórico.\')">Voltar para esta versão</button></form>';
        }
        h += '</div><div class="trecho-diff mini mt-1">' + it.diff + "</div></div>";
      });
      corpo.innerHTML = h || '<p class="text-secondary">Ainda não há versões guardadas deste trecho.</p>';
      bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-hist-bloco")).show();
    });
  }

  return { cfg: CFG, base: base, aviso: aviso, post: post, get: get, limpar: limpar, esc: esc, palavras: palavras,
    formatar: formatar, abrirNumeros: abrirNumeros, historico: historico,
    marcaNoCursor: marcaNoCursor, concluirDestaque: concluirDestaque, destacar: destacar, colar: colar,
    escolherImagem: escolherImagem, enviarImagem: enviarImagem, soltar: soltar,
    desfazerIniciar: desfazerIniciar, desfazerRegistrar: desfazerRegistrar, desfazer: desfazer, refazer: refazer,
    desfazerEncerrar: desfazerEncerrar, teclaDesfazer: teclaDesfazer };
})();
