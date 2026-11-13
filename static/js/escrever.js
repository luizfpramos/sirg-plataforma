/*
 * Editor de documento do SiRG ("Escrever o relatório").
 *
 * O relatório inteiro aparece como uma folha. A pessoa clica no texto de uma seção que pode
 * alterar e digita direto ali, como num editor de texto:
 *   - ao clicar, o trecho é reservado para ela (os colegas veem "Fulano está escrevendo aqui");
 *   - o texto é salvo sozinho, 1,5 s depois que ela para de digitar, e ao sair do trecho;
 *   - a cada 20 s o editor confere o que os colegas mudaram e atualiza os outros trechos;
 *   - com o "Controle de alterações" ligado (revisao.js), o que se digita ou apaga fica marcado como
 *     sugestão, com o nome de quem fez, até alguém aceitar ou recusar.
 */
(function () {
  "use strict";
  var T = window.SIRGTexto;
  var RV = window.SIRGRevisao;
  var CFG = T.cfg;
  var base = T.base;
  var app = document.getElementById("doc-app");
  if (!app) return;
  var barra = app.querySelector(".js-barra");
  var statusEl = app.querySelector(".js-status");
  var estiloSel = app.querySelector(".js-estilo");

  var ativo = null;          // trecho aberto
  var avisouLeitura = false; // o aviso de "somente leitura" aparece uma vez só
  var ultimoClique = null;   // posição do clique, para pôr o cursor onde a pessoa clicou

  function modo() { return "editar"; }
  function hora() { return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
  function status(tipo, texto) {
    var icone = { ok: "bi-cloud-check", salvando: "bi-arrow-repeat", pendente: "bi-pencil", erro: "bi-exclamation-triangle", sugestao: "bi-lightbulb" }[tipo] || "bi-info-circle";
    statusEl.className = "js-status st-" + tipo;
    statusEl.innerHTML = '<i class="bi ' + icone + '"></i> ' + T.esc(texto);
  }
  function alvo() {
    if (!ativo) return null;
    return { area: ativo.area, bloco: ativo.id, secao: ativo.secao, secaoChave: ativo.secaoChave, sujo: marcarSujo,
      rastrear: !!ativo.rastrear };
  }
  function ligarBarra(on) {
    barra.dataset.ativa = on ? "1" : "0";
    app.querySelector(".js-dica-barra").textContent = on
      ? (ativo && ativo.rastrear ? "Controle de alterações ligado em: " + ativo.titulo : "Escrevendo em: " + ativo.titulo)
      : "Clique num texto que você pode alterar para usar as ferramentas.";
    if (ativo) ativo.area.classList.toggle("rastreando", !!ativo.rastrear);
  }

  // ---- abrir um trecho -----------------------------------------------------------------
  function podeAbrir(area) { return area.classList.contains("editavel"); }
  function abrir(area) {
    if ((ativo && ativo.area === area) || area.classList.contains("abrindo")) return Promise.resolve();
    return fechar().then(function (ok) {
      if (ok === false) return;
      var m = modo();
      var id = area.dataset.bloco;
      area.classList.add("abrindo");
      return T.post(base + "blocos/" + id + "/travar/", { modo: m }).then(function (r) {
        area.classList.remove("abrindo");
        if (!r.ok) {
          T.aviso(r.erro || "Não foi possível abrir este trecho.", "warning");
          if (r.erro && r.erro.indexOf("está editando") >= 0) mostrarTrava(area, r.erro.split(" está editando")[0]);
          return;
        }
        var sec = area.closest("section[data-secao]");
        var titulo = sec ? (sec.querySelector(".doc-h-sec, .doc-h-sub, .doc-h-cap") || {}).textContent : "";
        if (!titulo && area.closest("[data-titulo]")) titulo = area.closest("[data-titulo]").getAttribute("data-titulo");
        if (r.versao && r.versao !== area.dataset.versao) area.innerHTML = r.html;   // alguém mudou depois que a página abriu
        area.dataset.versao = r.versao || area.dataset.versao;
        ativo = { area: area, id: id, secao: area.dataset.secao, secaoChave: area.dataset.secaoChave, versao: area.dataset.versao,
          modo: m, sujo: false, salvando: false, original: area.innerHTML, titulo: (titulo || "").trim(),
          rastrear: !!(RV && RV.ligado) };
        area.classList.remove("vazio");
        area.classList.add("ativo");
        area.closest(".doc-bloco").classList.add("ativo");
        if (!area.textContent.trim() && !area.querySelector(".sirg-num")) area.innerHTML = "<p><br></p>";
        area.contentEditable = "true";
        area.spellcheck = true;
        area.lang = "pt-BR";
        document.execCommand("defaultParagraphSeparator", false, "p");
        area.focus();
        posicionarCursor(area);
        ligarBarra(true);
        T.desfazerIniciar(id, area);
        status("ok", "Tudo salvo");
        ativo.mexeu = Date.now();
        if (m === "editar") ativo.pulso = setInterval(function () {
          if (!ativo) return;
          if (Date.now() - ativo.mexeu > 10 * 60000) {   // 10 min parado: libera o trecho para os colegas
            fechar().then(function () { T.aviso("Você ficou 10 minutos sem escrever, então o trecho foi liberado para os colegas. Clique nele de novo para continuar.", "dark"); });
            return;
          }
          T.post(base + "blocos/" + ativo.id + "/travar/", { modo: "editar" });
        }, 60000);
        recuperarRascunho();
      });
    });
  }
  function posicionarCursor(area) {
    var c = ultimoClique;
    ultimoClique = null;
    if (!c || Date.now() - c.t > 4000) return;
    var faixa = null;
    if (document.caretRangeFromPoint) faixa = document.caretRangeFromPoint(c.x, c.y);
    else if (document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(c.x, c.y);
      if (p) { faixa = document.createRange(); faixa.setStart(p.offsetNode, p.offset); }
    }
    if (faixa && area.contains(faixa.startContainer)) {
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(faixa);
    }
  }
  function mostrarTrava(area, nome) {
    var b = area.closest(".doc-bloco").querySelector(".doc-trava");
    if (!b) return;
    if (nome) { b.querySelector("span").textContent = nome; b.classList.remove("d-none"); area.classList.add("ocupado"); }
    else { b.classList.add("d-none"); area.classList.remove("ocupado"); }
  }

  // ---- salvar ----------------------------------------------------------------------------
  var espera = null;
  var DIGITACAO = /^(insertText|insertCompositionText|deleteContentBackward|deleteContentForward|insertParagraph|insertLineBreak)$/;
  function marcarSujo(tipoEntrada, semRegistro) {
    if (!ativo) return;
    if (!semRegistro) T.desfazerRegistrar(ativo.id, typeof tipoEntrada === "string" && DIGITACAO.test(tipoEntrada) &&
                                          tipoEntrada !== "insertParagraph");
    ativo.sujo = true;
    ativo.mexeu = Date.now();
    status("pendente", "Alterações ainda não salvas…");
    try {
      localStorage.setItem("sirg-rascunho-" + ativo.id, JSON.stringify({ html: ativo.area.innerHTML, versao: ativo.versao, quando: new Date().toLocaleString("pt-BR") }));
    } catch (e) { /* navegador sem armazenamento: segue sem rascunho */ }
    clearTimeout(espera);
    espera = setTimeout(function () { salvar(); }, 1500);
  }
  function recuperarRascunho() {
    var r = null;
    try { r = JSON.parse(localStorage.getItem("sirg-rascunho-" + ativo.id) || "null"); } catch (e) { r = null; }
    if (r && ativo.modo === "editar" && r.versao === ativo.versao && r.html !== ativo.area.innerHTML &&
        confirm("Este trecho tem um texto que não chegou a ser salvo (" + r.quando + "), talvez por queda de rede ou energia.\n\nRecuperar esse texto?")) {
      ativo.area.innerHTML = r.html;
      marcarSujo();
    }
  }
  function limparRascunho(id) { try { localStorage.removeItem("sirg-rascunho-" + id); } catch (e) { /* sem armazenamento */ } }

  function salvar(opcoes) {
    opcoes = opcoes || {};
    if (!ativo || ativo.modo !== "editar") return Promise.resolve(true);
    clearTimeout(espera);
    var a = ativo;
    if (a.salvando) return a.salvando.then(function () { return a.sujo ? salvar(opcoes) : true; });
    if (!a.sujo) return Promise.resolve(true);
    status("salvando", "Salvando…");
    var dados = { html: T.limpar(a.area.innerHTML), versao: a.versao, liberar: !!opcoes.liberar };
    var enviado = dados.html;
    a.salvando = T.post(base + "blocos/" + a.id + "/texto/", dados, opcoes.keepalive ? { keepalive: true } : {}).then(function (r) {
      a.salvando = false;
      if (!r.ok) {
        status("erro", "Não foi possível salvar");
        T.aviso(r.erro || "Não foi possível salvar o texto.", "danger");
        return false;
      }
      limparRascunho(a.id);
      a.versao = r.versao; a.area.dataset.versao = r.versao;
      if (T.limpar(a.area.innerHTML) === enviado) a.sujo = false;   // não digitou nada enquanto salvava
      a.renderizado = r.html;
      if (a.sujo) { espera = setTimeout(function () { salvar(); }, 800); }
      else status("ok", "Tudo salvo às " + hora());
      return true;
    });
    return a.salvando;
  }

  // ---- sair do trecho ------------------------------------------------------------------------
  function fechar() {
    if (!ativo) return Promise.resolve(true);
    var a = ativo;
    return salvar({ liberar: true }).then(function (ok) {
      if (ok === false) {
        if (!confirm("O texto não foi salvo. Se você sair deste trecho agora, a última alteração pode se perder.\n\nSair mesmo assim?")) {
          a.area.focus();
          return false;
        }
      }
      encerrar(a);
      T.post(base + "blocos/" + a.id + "/travar/", { liberar: true });
      if (a.renderizado && !a.sujo) a.area.innerHTML = a.renderizado;
      T.desfazerEncerrar(a.id, a.area);
      return true;
    });
  }
  function encerrar(a) {
    clearInterval(a.pulso);
    esconderChip();
    esconderChipNome();
    a.area.contentEditable = "false";
    a.area.classList.remove("ativo", "rastreando");
    a.area.closest(".doc-bloco").classList.remove("ativo");
    if (!a.area.textContent.trim() && !a.area.querySelector(".sirg-num")) { a.area.innerHTML = ""; a.area.classList.add("vazio"); }
    if (ativo === a) ativo = null;
    ligarBarra(false);
  }
  // ---- eventos -------------------------------------------------------------------------------
  document.addEventListener("mousedown", function (e) {
    var area = e.target.closest(".doc-texto");
    // clique num xxxxx (ou número de tabela) que a pessoa preenche: abre só o campo do número (preencher.js)
    if (area && !area.classList.contains("ativo") && e.target.closest(".sirg-campo.pode, .sirg-num[data-pode='1'], .pg .sirg-num.pendente[data-quadro]")) {
      e.preventDefault();               // sem foco no trecho: o editor de texto não abre
      if (ativo) fechar();
      return;
    }
    if (area) {
      ultimoClique = { x: e.clientX, y: e.clientY, t: Date.now() };
      if (!podeAbrir(area) && !area.classList.contains("ativo")) {
        if (area.classList.contains("ocupado")) T.aviso("Um colega está escrevendo neste trecho agora. Tente daqui a pouco.", "warning");
        else if (!avisouLeitura) {
          avisouLeitura = true;
          T.aviso("Este trecho é somente leitura para você. Para propor uma mudança, selecione o trecho e clique em Comentar. " +
            "As suas seções têm a faixa verde e o lápis no sumário.", "dark");
        }
        return;
      }
      if (!area.classList.contains("ativo")) { e.preventDefault(); abrir(area); }
      return;
    }
    if (e.target.closest(".doc-barra button, .doc-barra .dropdown-menu")) { e.preventDefault(); return; }
    if (!ativo) return;
    if (e.target.closest(".doc-ferramentas, .modal, .dropdown-menu, .toast, .chip-destaque, .doc-revisao, .pop-campo, .doc-gaveta")) return;
    fechar();
  });
  document.addEventListener("focusin", function (e) {
    var area = e.target.closest && e.target.closest(".doc-texto");
    if (area && !area.classList.contains("ativo") && podeAbrir(area)) abrir(area);
  });
  document.addEventListener("input", function (e) {
    if (ativo && e.target.closest(".doc-texto.ativo")) marcarSujo(e.inputType);
  });
  // desfazer/refazer pelo menu do navegador também usam o histórico do SiRG
  document.addEventListener("beforeinput", function (e) {
    if (!ativo || !e.target.closest(".doc-texto.ativo")) return;
    if (e.inputType === "historyUndo" || e.inputType === "historyRedo") {
      e.preventDefault();
      if (e.inputType === "historyUndo" ? T.desfazer(ativo.id) : T.refazer(ativo.id)) marcarSujo(null, true);
    }
  });
  document.addEventListener("drop", function (e) {
    if (ativo && e.target.closest(".doc-texto.ativo")) T.soltar(e, alvo());
  });
  document.addEventListener("paste", function (e) {
    if (ativo && e.target.closest(".doc-texto.ativo")) T.colar(e, alvo());
  });
  document.addEventListener("keydown", function (e) {
    if (!ativo || !e.target.closest(".doc-texto.ativo")) return;
    ativo.mexeu = Date.now();
    if (T.teclaDesfazer(e, ativo.id, function () { marcarSujo(null, true); })) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); salvar(); }
    if (e.key === "Escape") { e.preventDefault(); fechar(); }
  });
  // selo flutuante sobre o trecho em amarelo: mostra como estava e conclui o destaque
  var chip = document.getElementById("chip-destaque");
  var marcaAtual = null;
  function esconderChip() { if (chip) chip.classList.add("d-none"); marcaAtual = null; }
  function mostrarChip(m) {
    if (!chip) return;
    marcaAtual = m;
    var orig = m.getAttribute("data-orig") || "";
    chip.querySelector(".chip-antes").textContent = orig && orig !== "figura" ? "No RG " + (CFG.ano - 1) + ": “" + (orig.length > 160 ? orig.slice(0, 157) + "…" : orig) + "”" : "Trecho marcado para atualizar.";
    chip.classList.remove("d-none");
    var r = m.getBoundingClientRect();
    var topo = r.top + window.scrollY - chip.offsetHeight - 8;
    var css = getComputedStyle(document.documentElement);
    var limite = window.scrollY + (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90) + 4;
    if (topo < limite) topo = r.bottom + window.scrollY + 8;
    chip.style.top = topo + "px";
    chip.style.left = Math.max(8, Math.min(r.left + window.scrollX, window.innerWidth - chip.offsetWidth - 16)) + "px";
  }
  if (chip) chip.querySelector(".js-chip-concluir").addEventListener("mousedown", function (e) {
    e.preventDefault();
    if (!ativo || !marcaAtual) return;
    var pai = marcaAtual.parentNode;
    while (marcaAtual.firstChild) pai.insertBefore(marcaAtual.firstChild, marcaAtual);
    pai.removeChild(marcaAtual);
    pai.normalize();
    esconderChip();
    marcarSujo();
  });
  // selo sobre a menção ao CEFET-MG em amarelo: a pessoa escolhe CEFET-MG (fato histórico) ou UFCIMG
  var chipNome = document.getElementById("chip-nome");
  var nomeAtual = null;
  function esconderChipNome() { if (chipNome) chipNome.classList.add("d-none"); nomeAtual = null; }
  function nomeNoCursor(area) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var n = sel.anchorNode;
    var el = n && (n.nodeType === 1 ? n : n.parentNode);
    var m = el && el.closest ? el.closest("mark.nome-inst") : null;
    return m && area.contains(m) ? m : null;
  }
  function mostrarChipNome(m) {
    if (!chipNome) return;
    nomeAtual = m;
    chipNome.querySelector(".js-nome-depois").textContent = m.getAttribute("data-depois") || "UFCIMG";
    chipNome.querySelector(".js-nome-antes").textContent = m.getAttribute("data-antes") || m.textContent;
    var n = ativo ? ativo.area.querySelectorAll("mark.nome-inst").length : 0;
    var todas = chipNome.querySelector(".js-nome-todas");
    todas.classList.toggle("d-none", n < 2);
    todas.querySelector("span").textContent = n;
    chipNome.classList.remove("d-none");
    var r = m.getBoundingClientRect();
    var topo = r.top + window.scrollY - chipNome.offsetHeight - 8;
    var css = getComputedStyle(document.documentElement);
    var limite = window.scrollY + (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90) + 4;
    if (topo < limite) topo = r.bottom + window.scrollY + 8;
    chipNome.style.top = topo + "px";
    chipNome.style.left = Math.max(8, Math.min(r.left + window.scrollX, window.innerWidth - chipNome.offsetWidth - 16)) + "px";
  }
  function escolherNome(qual) {
    if (!ativo || !nomeAtual) return;
    var texto = nomeAtual.getAttribute(qual === "ufcimg" ? "data-depois" : "data-antes") || nomeAtual.textContent;
    var pai = nomeAtual.parentNode;
    if (ativo.rastrear && qual === "ufcimg" && texto !== nomeAtual.textContent) RV.trocar(nomeAtual, texto);
    else pai.replaceChild(document.createTextNode(texto), nomeAtual);
    pai.normalize();
    esconderChipNome();
    marcarSujo();
    var prox = ativo.area.querySelector("mark.nome-inst");
    T.aviso(qual === "ufcimg" ? "Trocado por “" + texto + "”." : "Mantido “" + texto + "”." , "success");
    if (prox) prox.scrollIntoView({ block: "nearest" });
  }
  function trocarTodasNoTrecho() {
    if (!ativo) return;
    var ms = ativo.area.querySelectorAll("mark.nome-inst");
    ms.forEach(function (m) {
      var pai = m.parentNode;
      var novo = m.getAttribute("data-depois") || "UFCIMG";
      if (ativo.rastrear && novo !== m.textContent) RV.trocar(m, novo);
      else pai.replaceChild(document.createTextNode(novo), m);
      pai.normalize();
    });
    esconderChipNome();
    if (ms.length) { marcarSujo(); T.aviso(ms.length + " menç" + (ms.length > 1 ? "ões trocadas" : "ão trocada") + " por UFCIMG neste trecho. Ctrl+Z desfaz.", "success"); }
  }
  if (chipNome) {
    chipNome.querySelector(".js-nome-todas").addEventListener("mousedown", function (e) { e.preventDefault(); trocarTodasNoTrecho(); });
    chipNome.querySelector(".js-nome-ufcimg").addEventListener("mousedown", function (e) { e.preventDefault(); escolherNome("ufcimg"); });
    chipNome.querySelector(".js-nome-cefet").addEventListener("mousedown", function (e) { e.preventDefault(); escolherNome("cefet"); });
  }
  document.addEventListener("selectionchange", function () {
    if (ativo) {
      var m = T.marcaNoCursor(ativo.area);
      if (m && ativo.modo === "editar") mostrarChip(m); else esconderChip();
      var mn = nomeNoCursor(ativo.area);
      if (mn && ativo.modo === "editar") mostrarChipNome(mn); else esconderChipNome();
    }
    if (!ativo || !estiloSel) return;
    var sel = window.getSelection();
    if (!sel.rangeCount || !ativo.area.contains(sel.anchorNode)) return;
    var n = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentNode;
    var bl = n.closest("h3, h4, blockquote, p, li");
    estiloSel.value = bl && ["H3", "H4", "BLOCKQUOTE"].indexOf(bl.tagName) >= 0 ? bl.tagName.toLowerCase() : "p";
  });
  if (estiloSel) estiloSel.addEventListener("change", function () {
    if (!ativo) return;
    ativo.area.focus();
    T.formatar(this.value);
    marcarSujo();
  });

  document.addEventListener("click", function (e) {
    var bt = e.target.closest(".doc-barra button[data-cmd]");
    if (bt) {
      if (!ativo) { T.aviso("Primeiro clique no texto que você quer alterar.", "dark"); return; }
      if (bt.dataset.cmd === "numero") { T.abrirNumeros(alvo()); return; }
      if (bt.dataset.cmd === "imagem") { T.escolherImagem(alvo()); return; }
      if (bt.dataset.cmd === "undo" || bt.dataset.cmd === "redo") {
        if (bt.dataset.cmd === "undo" ? T.desfazer(ativo.id) : T.refazer(ativo.id)) marcarSujo(null, true);
        else T.aviso(bt.dataset.cmd === "undo" ? "Nada para desfazer neste trecho." : "Nada para refazer.", "dark");
        return;
      }
      if (bt.dataset.cmd === "concluir") {
        if (!T.concluirDestaque(alvo())) T.aviso("Coloque o cursor dentro de um trecho em amarelo (ou selecione vários) e clique de novo.", "dark");
        else { esconderChip(); T.aviso("Destaque concluído.", "success"); }
        return;
      }
      if (bt.dataset.cmd === "destacar") {
        if (!T.destacar(alvo())) T.aviso("Selecione com o mouse o trecho que deve ficar destacado para atualizar.", "dark");
        return;
      }
      T.formatar(bt.dataset.cmd);
      marcarSujo();
      return;
    }
    var ins = e.target.closest(".js-inserir-texto");
    if (ins) { inserirTexto(ins.dataset.secao, ins.closest(".doc-inserir")); return; }
    var ex = e.target.closest(".js-excluir-texto");
    if (ex) { excluirTexto(ex.closest(".doc-bloco")); return; }
    var hb = e.target.closest(".js-hist-bloco");
    if (hb) { var id = hb.closest(".doc-bloco").dataset.bloco; T.historico(id, urlVolta(id)); return; }
    var cm = e.target.closest(".js-comentar");
    if (cm) { if (RV) RV.comentarBloco(cm.closest(".doc-bloco")); else comentar(cm.closest(".doc-bloco")); return; }
    var dv = e.target.closest(".js-devolver");
    if (dv) {
      var f = document.getElementById("form-devolver");
      f.action = dv.dataset.url;
      document.getElementById("devolver-voltar").value = dv.dataset.voltar;
      document.getElementById("modal-devolver-titulo").textContent = "Devolver “" + dv.dataset.titulo + "” ao setor";
      bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-devolver")).show();
    }
  });

  function chaveDaSecao(el) { var a = el.querySelector(".doc-texto"); return a ? a.dataset.secaoChave : ""; }
  function urlVolta(id) {
    var el = document.getElementById("bloco-" + id);
    return location.pathname + "?secao=" + encodeURIComponent(el ? chaveDaSecao(el) : "") + "#bloco-" + id;
  }
  function comentar(bloco) {
    var chave = chaveDaSecao(bloco);
    var f = document.getElementById("form-comentar");
    f.action = base + "secoes/" + encodeURIComponent(chave) + "/comentar/";
    document.getElementById("comentar-bloco").value = bloco.dataset.bloco;
    document.getElementById("comentar-voltar").value = urlVolta(bloco.dataset.bloco);
    bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-comentar")).show();
    setTimeout(function () { document.getElementById("comentar-texto").focus(); }, 300);
  }
  function inserirTexto(secao, ondeAntes) {
    fechar().then(function (ok) {
      if (ok === false) return;
      T.post(base + "escrever/inserir/", { secao: secao }).then(function (r) {
        if (!r.ok) { T.aviso(r.erro || "Não foi possível criar o trecho.", "danger"); return; }
        var tmp = document.createElement("div");
        tmp.innerHTML = r.html;
        var novo = tmp.firstElementChild;
        var vazia = ondeAntes.parentNode.querySelector(".doc-vazia");
        if (vazia) vazia.remove();
        ondeAntes.parentNode.insertBefore(novo, ondeAntes);
        var area = novo.querySelector(".doc-texto");
        area.scrollIntoView({ block: "center", behavior: "smooth" });
        abrir(area);
      });
    });
  }
  function excluirTexto(bloco) {
    if (!confirm("Apagar este trecho de texto do relatório?\n\nEle continua guardado no histórico.")) return;
    var id = bloco.dataset.bloco;
    var a = ativo && ativo.id === id ? ativo : null;
    if (a) { a.sujo = false; encerrar(a); }
    T.post(base + "blocos/" + id + "/excluir-texto/", {}).then(function (r) {
      if (!r.ok) { T.aviso(r.erro || "Não foi possível apagar.", "danger"); return; }
      limparRascunho(id);
      bloco.remove();
      T.aviso("Trecho apagado.", "success");
    });
  }

  // ---- textos do relatório anterior (referência) -------------------------------------------------
  var btRef = document.querySelector(".js-ref-todos");
  if (btRef) btRef.addEventListener("click", function () {
    var abrir = btRef.getAttribute("aria-pressed") !== "true";
    document.querySelectorAll("details.js-ref").forEach(function (d) { d.open = abrir; });
    btRef.setAttribute("aria-pressed", abrir ? "true" : "false");
    btRef.querySelector("span").textContent = (abrir ? "Ocultar os textos de " : "Textos de ") + (CFG.ano - 1);
  });

  // ---- o que os colegas estão fazendo (a cada 20 s) ----------------------------------------------
  function atualizarEstado() {
    if (document.hidden) return;
    T.get(base + "escrever/estado/").then(function (j) {
      Object.keys(j.blocos).forEach(function (id) {
        var area = document.querySelector('.doc-texto[data-bloco="' + id + '"]');
        if (!area || (ativo && ativo.id === id)) return;
        var e = j.blocos[id];
        mostrarTrava(area, e.por);
        if (e.v !== area.dataset.versao) {
          T.get(base + "blocos/" + id + "/html/").then(function (b) {
            if (ativo && ativo.id === id) return;
            area.innerHTML = b.html;
            area.dataset.versao = b.v;
            area.classList.toggle("vazio", !b.html);
            area.classList.add("atualizado");
            setTimeout(function () { area.classList.remove("atualizado"); }, 2500);
          });
        }
      });
    }).catch(function () { /* sem rede: tenta na próxima */ });
  }
  setInterval(atualizarEstado, 20000);

  window.SIRGEditor = { ativoId: function () { return ativo ? ativo.id : null; } };
  if (RV) RV.ligar({
    ativo: function () { return ativo; },
    mudou: function (tipo) { marcarSujo(tipo); },
    fechar: function () { return fechar(); },
    status: function () { if (ativo) { ativo.rastrear = RV.ligado; ligarBarra(true); } }
  });

  window.addEventListener("beforeunload", function (e) {
    if (!ativo) return;
    if (ativo.modo === "editar") {
      if (ativo.sujo) salvar({ liberar: true, keepalive: true });
      T.post(base + "blocos/" + ativo.id + "/travar/", { liberar: true }, { keepalive: true });
    }
    if (ativo.sujo) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---- metas do PDI: preenchidas no próprio documento (salvam ao sair do campo) -------------------
  function salvarMeta(el) {
    var anterior = el.dataset.anterior !== undefined ? el.dataset.anterior : el.defaultValue;
    var novo = el.value.trim();
    if (novo === (anterior || "").trim()) return;
    var td = el.closest("td, .meta-campos, .meta-campo-linha") || el.parentNode;
    td.classList.remove("salvo", "falhou"); td.classList.add("salvando");
    T.post(base + "celula/", { linha: el.dataset.l, coluna: el.dataset.c, valor: novo, anterior: anterior }).then(function (r) {
      td.classList.remove("salvando");
      if (!r.ok) {
        td.classList.add("falhou");
        if (r.conflito) { el.value = r.atual || ""; el.dataset.anterior = r.atual || ""; }
        T.aviso(r.erro || "Não foi possível salvar.", "danger");
        return;
      }
      el.dataset.anterior = r.edicao; el.value = r.edicao;
      td.classList.add("salvo");
      setTimeout(function () { td.classList.remove("salvo"); }, 2000);
      status("ok", "Tudo salvo às " + hora());
      var fig = el.closest(".metas-editar");
      var faltam = 0;
      if (fig.classList.contains("metas-2026")) {
        fig.querySelectorAll(".meta-card").forEach(function (card) {
          var sit = card.querySelector(".meta-sit");
          if (!sit) return;
          var v = function (t) { var x = card.querySelector('[data-tipo="' + t + '"] textarea'); return x ? x.value.trim() : "x"; };
          if (!sit.value) faltam++;
          else if ((sit.value === "Não iniciado" || sit.value === "Interrompido") && !v("justificativa")) faltam++;
          else if ((sit.value === "Em andamento" || sit.value === "Concluído") && !v("evidencia")) faltam++;
        });
        fig.querySelector(".js-metas-faltam").textContent = faltam ? "Faltam " + faltam : "Tudo preenchido";
      } else {
        fig.querySelectorAll(".meta-campo").forEach(function (x) { if (!x.value.trim()) faltam++; });
        fig.querySelector(".js-metas-faltam").textContent = faltam ? "Faltam " + faltam + " campo" + (faltam > 1 ? "s" : "") + "." : "Tudo preenchido.";
      }
    });
  }
  document.addEventListener("focusin", function (e) {
    var el = e.target.closest && e.target.closest(".meta-campo");
    if (el && el.dataset.anterior === undefined) el.dataset.anterior = el.tagName === "SELECT" ? el.value : el.defaultValue;
  });
  document.addEventListener("focusout", function (e) {
    var el = e.target.closest && e.target.closest(".meta-campo");
    if (el) salvarMeta(el);
  });
  document.addEventListener("change", function (e) {
    var el = e.target.closest && e.target.closest("input.meta-campo, select.meta-campo");
    if (el) salvarMeta(el);       // escolheu um status na lista
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".js-metas-todas");
    if (!b) return;
    var on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.textContent = on ? "mostrar só as da minha unidade" : "mostrar todas as metas";
    b.closest(".metas-editar").querySelectorAll(".meta-card.de-outra").forEach(function (c) { c.hidden = !on; });
  });

  // ---- sumário: chave "Só o que eu escrevo" -------------------------------------------------------
  var soMinhas = document.querySelector(".js-so-minhas");
  function filtrarSumario() {
    var on = soMinhas && soMinhas.checked;
    var cap = null, capTem = false;
    function fecharCap() { if (cap) cap.hidden = on && !capTem && !cap.dataset.interessa; }
    document.querySelectorAll(".js-sumario a").forEach(function (a) {
      if (a.classList.contains("cap")) { fecharCap(); cap = a; capTem = false; return; }
      var mostra = !on || !!a.dataset.interessa;
      a.hidden = !mostra;
      if (mostra) capTem = true;
    });
    fecharCap();
  }
  if (soMinhas) {
    try { if (localStorage.getItem("sirg-so-minhas") === "0") soMinhas.checked = false; } catch (e) { /* sem armazenamento */ }
    soMinhas.addEventListener("change", function () {
      try { localStorage.setItem("sirg-so-minhas", soMinhas.checked ? "1" : "0"); } catch (e) { /* sem armazenamento */ }
      filtrarSumario();
    });
    filtrarSumario();
  }

  // ---- sumário: destaca a seção visível e abre na seção pedida -----------------------------------
  var links = {};
  document.querySelectorAll(".doc-sumario a").forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
  if ("IntersectionObserver" in window) {
    var obs = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        if (!en.isIntersecting) return;
        Object.keys(links).forEach(function (k) { links[k].classList.remove("atual"); });
        var l = links[en.target.id];
        if (l) { l.classList.add("atual"); if (l.scrollIntoViewIfNeeded) l.scrollIntoViewIfNeeded(false); }
      });
    }, { rootMargin: "-30% 0px -60% 0px" });
    document.querySelectorAll(".doc-sec, .doc-cap").forEach(function (s) { obs.observe(s); });
  }
  function rolarPara(el, instantaneo) {
    var css = getComputedStyle(document.documentElement);
    var folga = (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90) + 12;
    window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - folga), behavior: instantaneo ? "instant" : "smooth" });
  }
  var alvoInicial = location.hash ? document.getElementById(location.hash.slice(1)) : (CFG.inicio && document.getElementById("sec-" + CFG.inicio));
  if (alvoInicial) setTimeout(function () { rolarPara(alvoInicial, true); }, 60);
  document.querySelectorAll(".doc-sumario a").forEach(function (a) {
    a.addEventListener("click", function (e) {
      var el = document.getElementById(a.getAttribute("href").slice(1));
      if (el) { e.preventDefault(); rolarPara(el); history.replaceState(null, "", a.getAttribute("href")); }
    });
  });
})();
