/*
 * Editor do texto do relatório (SiRG).
 * - Editar: reserva o trecho (ninguém mais edita ao mesmo tempo), salva sozinho a cada 20 s
 *   e ao concluir; guarda um rascunho no navegador contra queda de energia/rede.
 * - Sugerir (Master): mesmo editor, mas grava como sugestão para o setor aceitar ou recusar.
 * - Números vivos: botão "Número" insere um valor ligado a um quadro.
 * - Colar do Word: o HTML colado é limpo (sem estilos, cores e fontes).
 */
(function () {
  "use strict";
  var T = window.SIRGTexto;
  var CFG = T.cfg;
  var base = T.base;
  var aviso = T.aviso, post = T.post, limpar = T.limpar, esc = T.esc;

  var ativo = null;   // editor aberto

  function barra(modo) {
    var b = [
      ["bold", "bi-type-bold", "Negrito (Ctrl+B)"], ["italic", "bi-type-italic", "Itálico (Ctrl+I)"],
      ["underline", "bi-type-underline", "Sublinhado (Ctrl+U)"], ["|"],
      ["h3", "bi-type-h3", "Título"], ["h4", "bi-type-h4", "Subtítulo"], ["p", "bi-paragraph", "Parágrafo normal"], ["|"],
      ["insertUnorderedList", "bi-list-ul", "Lista"], ["insertOrderedList", "bi-list-ol", "Lista numerada"],
      ["blockquote", "bi-quote", "Citação/destaque"], ["link", "bi-link-45deg", "Link"], ["|"],
      ["numero", "bi-123", "Inserir número vivo (ligado a um quadro)"], ["imagem", "bi-image", "Inserir imagem"], ["removeFormat", "bi-eraser", "Limpar formatação"], ["|"],
      ["undo", "bi-arrow-counterclockwise", "Desfazer (Ctrl+Z)"], ["redo", "bi-arrow-clockwise", "Refazer"]
    ];
    var h = '<div class="ed-barra" role="toolbar" aria-label="Formatação">';
    b.forEach(function (x) {
      if (x[0] === "|") { h += '<span class="ed-sep"></span>'; return; }
      h += '<button type="button" class="btn btn-sm btn-light" data-cmd="' + x[0] + '" title="' + x[2] + '" aria-label="' + x[2] + '"><i class="bi ' + x[1] + '"></i>' + (x[0] === "numero" ? " Número" : "") + "</button>";
    });
    h += '<span class="ms-auto mini text-secondary ed-status" aria-live="polite"></span></div>';
    return h;
  }

  function abrir(sec, modo) {
    if (ativo) { aviso("Conclua o trecho que você já está editando.", "warning"); ativo.area.focus(); return; }
    var id = sec.dataset.bloco;
    post(base + "blocos/" + id + "/travar/", { modo: modo }).then(function (r) {
      if (!r.ok) { aviso(r.erro || "Não foi possível abrir o editor.", "danger"); return; }
      var corpo = sec.querySelector(".bloco-corpo");
      var rascunho = null;
      try { rascunho = JSON.parse(localStorage.getItem("sirg-rascunho-" + id) || "null"); } catch (e) { rascunho = null; }
      var ed = document.createElement("div");
      ed.className = "editor " + (modo === "sugerir" ? "modo-sugestao" : "");
      ed.innerHTML = (modo === "sugerir" ? '<div class="alert alert-info py-1 px-2 mini mb-1"><i class="bi bi-lightbulb"></i> Modo sugestão: o texto do setor não muda até que ele aceite.</div>' : "") +
        barra(modo) + '<div class="ed-area texto-rg" contenteditable="true" spellcheck="true" lang="pt-BR" aria-label="Texto do relatório"></div>' +
        (modo === "sugerir" ? '<input class="form-control form-control-sm mt-2 ed-comentario" placeholder="Comentário para o setor (opcional)" aria-label="Comentário da sugestão">' : "") +
        '<div class="d-flex gap-2 mt-2 align-items-center"><button type="button" class="btn btn-primary btn-sm ed-concluir"><i class="bi bi-check-lg"></i> ' +
        (modo === "sugerir" ? "Enviar sugestão" : "Salvar e concluir") + '</button><button type="button" class="btn btn-link btn-sm ed-cancelar">Cancelar</button>' +
        '<span class="ms-auto mini text-secondary ed-palavras"></span></div>';
      corpo.style.display = "none";
      corpo.parentNode.insertBefore(ed, corpo.nextSibling);
      sec.querySelectorAll(".js-editar").forEach(function (b) { b.disabled = true; });
      var area = ed.querySelector(".ed-area");
      area.innerHTML = r.html || "<p><br></p>";
      if (rascunho && rascunho.versao === r.versao && rascunho.modo === modo && rascunho.html !== area.innerHTML &&
          confirm("Há um rascunho deste trecho que não chegou a ser salvo (" + rascunho.quando + "). Recuperar?")) {
        area.innerHTML = rascunho.html;
      }
      ativo = { sec: sec, id: id, modo: modo, ed: ed, area: area, versao: r.versao, sujo: false, salvando: false };
      T.desfazerIniciar("s" + id, area);
      document.execCommand("defaultParagraphSeparator", false, "p");
      area.focus();
      contar();
      ativo.timer = setInterval(function () { if (ativo && ativo.sujo && ativo.modo === "editar") salvar(false); }, 20000);
      ativo.pulso = setInterval(function () { if (ativo && ativo.modo === "editar") post(base + "blocos/" + id + "/travar/", { modo: "editar" }); }, 120000);
    });
  }

  function contar() {
    if (!ativo) return;
    var n = (ativo.area.innerText || "").trim().split(/\s+/).filter(Boolean).length;
    ativo.ed.querySelector(".ed-palavras").textContent = n + " palavra" + (n === 1 ? "" : "s");
  }
  function status(t) { if (ativo) ativo.ed.querySelector(".ed-status").textContent = t; }

  function fechar(recarregar) {
    if (!ativo) return;
    clearInterval(ativo.timer); clearInterval(ativo.pulso);
    var a = ativo; ativo = null;
    if (a.modo === "editar") post(base + "blocos/" + a.id + "/travar/", { liberar: true });
    if (recarregar) { location.hash = "bloco-" + a.id; location.reload(); return; }
    a.ed.remove();
    a.sec.querySelector(".bloco-corpo").style.display = "";
    a.sec.querySelectorAll(".js-editar").forEach(function (b) { b.disabled = false; });
  }

  function salvar(concluir) {
    if (!ativo || ativo.salvando) return Promise.resolve();
    var a = ativo;
    a.salvando = true;
    status("salvando…");
    var dados = { html: limpar(a.area.innerHTML), versao: a.versao, liberar: !!concluir };
    if (a.modo === "sugerir") { dados.sugestao = true; dados.comentario = (a.ed.querySelector(".ed-comentario") || {}).value || ""; }
    return post(base + "blocos/" + a.id + "/texto/", dados).then(function (r) {
      a.salvando = false;
      if (!r.ok) { status(""); aviso(r.erro || "Não foi possível salvar.", "danger"); return; }
      try { localStorage.removeItem("sirg-rascunho-" + a.id); } catch (e) {}
      if (r.versao) a.versao = r.versao;
      a.sujo = false;
      var hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      status("salvo às " + hora);
      if (concluir || r.recarregar) {
        if (r.mensagem) aviso(r.mensagem, "success");
        fechar(true);
      }
    });
  }

  function alvo() {
    if (!ativo) return null;
    return { area: ativo.area, bloco: ativo.id, secao: CFG.secao, secaoChave: CFG.secaoChave,
      sujo: function () { if (ativo) { T.desfazerRegistrar("s" + ativo.id, false); ativo.sujo = true; status("alterações não salvas"); contar(); } } };
  }

  // ---- barra de ferramentas -------------------------------------------------------------
  document.addEventListener("mousedown", function (e) { if (e.target.closest(".ed-barra button")) e.preventDefault(); });

  document.addEventListener("click", function (e) {
    var bt = e.target.closest(".ed-barra button[data-cmd]");
    if (bt && ativo) {
      var c = bt.dataset.cmd;
      if (c === "numero") { T.abrirNumeros(alvo()); return; }
      if (c === "imagem") { T.escolherImagem(alvo()); return; }
      if (c === "undo" || c === "redo") {
        if (!(c === "undo" ? T.desfazer("s" + ativo.id) : T.refazer("s" + ativo.id))) aviso(c === "undo" ? "Nada para desfazer." : "Nada para refazer.", "dark");
        ativo.sujo = true; contar();
        return;
      }
      T.formatar(c);
      T.desfazerRegistrar("s" + ativo.id, false);
      ativo.sujo = true; contar();
      return;
    }
    var ed = e.target.closest(".js-editar");
    if (ed) { abrir(ed.closest(".bloco"), ed.dataset.modo); return; }
    if (e.target.closest(".ed-concluir")) { salvar(true); return; }
    if (e.target.closest(".ed-cancelar")) {
      if (ativo && ativo.sujo && !confirm("Descartar as alterações não salvas?")) return;
      try { if (ativo) localStorage.removeItem("sirg-rascunho-" + ativo.id); } catch (er) {}
      fechar(false); return;
    }
    var hb = e.target.closest(".js-hist-bloco");
    if (hb) { historico(hb.closest(".bloco").dataset.bloco); return; }
    var cm = e.target.closest(".js-comentar");
    if (cm) {
      document.getElementById("comentar-bloco").value = cm.closest(".bloco").dataset.bloco;
      bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-comentar")).show();
    }
  });

  document.addEventListener("input", function (e) {
    if (!ativo || !e.target.closest(".ed-area")) return;
    T.desfazerRegistrar("s" + ativo.id, /^(insertText|insertCompositionText|deleteContentBackward|deleteContentForward)$/.test(e.inputType || ""));
    ativo.sujo = true; status("alterações não salvas"); contar();
    try {
      localStorage.setItem("sirg-rascunho-" + ativo.id, JSON.stringify({ html: ativo.area.innerHTML, versao: ativo.versao,
        modo: ativo.modo, quando: new Date().toLocaleString("pt-BR") }));
    } catch (er) {}
  });
  document.addEventListener("keydown", function (e) {
    if (!ativo || !e.target.closest(".ed-area")) return;
    if (T.teclaDesfazer(e, "s" + ativo.id, function () { ativo.sujo = true; contar(); })) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); salvar(false); }
  });
  document.addEventListener("drop", function (e) {
    if (ativo && e.target.closest(".ed-area")) T.soltar(e, alvo());
  });
  document.addEventListener("paste", function (e) {
    if (!ativo || !e.target.closest(".ed-area")) return;
    T.colar(e, alvo());
  });
  window.addEventListener("beforeunload", function (e) { if (ativo && ativo.sujo) { e.preventDefault(); e.returnValue = ""; } });

  function historico(id) { T.historico(id); }

  // abre direto o editor de um bloco recém-criado
  if (CFG.editar) {
    var sec = document.getElementById("bloco-" + CFG.editar);
    if (sec && sec.querySelector('.js-editar[data-modo="editar"]')) { sec.scrollIntoView({ block: "center" }); abrir(sec, "editar"); }
  }
})();
