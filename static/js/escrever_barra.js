/*
 * Barra flutuante de cada trecho (Escrever o relatório): Concluí / Desfazer, anterior / próximo entre os
 * trechos pendentes da pessoa, versões anteriores e, nos blocos de imagem, inserir ou trocar a imagem.
 * Aparece ao passar o mouse ou focar num trecho que a pessoa escreve. Depende de escrever.js (SIRGEscrever).
 */
(function () {
  "use strict";
  var T = window.SIRGTexto, E = window.SIRGEscrever;
  var barra = document.getElementById("bloco-barra");
  if (!T || !E || !barra) return;
  var base = T.base;
  var atual = null, escondeTimer = null;

  function meus() { return Array.prototype.slice.call(document.querySelectorAll(".doc-bloco[data-pode-concluir]")); }
  function pendentes() { return meus().filter(function (b) { return !b.hasAttribute("data-concluido"); }); }
  function id(b) { return b.dataset.bloco; }

  function posicionar() {
    if (!atual || barra.hidden) return;
    var r = atual.getBoundingClientRect(), css = getComputedStyle(document.documentElement);
    var topo = (parseInt(css.getPropertyValue("--topo-h"), 10) || 53) + (parseInt(css.getPropertyValue("--ferr-h"), 10) || 90);
    if (r.bottom < topo || r.top > window.innerHeight) { barra.style.visibility = "hidden"; return; }
    barra.style.visibility = "visible";
    var h = barra.offsetHeight, w = barra.offsetWidth;
    var x = Math.min(Math.max(8, r.right - w), window.innerWidth - w - 8);
    // 2.22 (S3): a barra não cobre texto. Tenta em cima do trecho e embaixo: primeiro onde não encosta em nada,
    // depois onde só encosta em gráfico ou imagem (nunca em texto). Sem lugar assim, fica em cima (como antes).
    var raiz = atual.closest(".pg") || document;       // só os blocos da mesma página (rolagem leve)
    var rects = function (sel) {
      return Array.prototype.filter.call(raiz.querySelectorAll(sel), function (b) {
        return b !== atual && !b.contains(atual) && !atual.contains(b);
      }).map(function (b) { return b.getBoundingClientRect(); });
    };
    var textos = rects(".pg-cx, .doc-bloco:not(.pg-obj)"), todos = textos.concat(rects(".pg-obj"));
    var cobre = function (lista, yy) {
      return lista.some(function (o) { return o.width && o.left < x + w && o.right > x && o.top < yy + h && o.bottom > yy; });
    };
    var cima = r.top - h - 2, baixo = r.bottom + 2;
    var cabe = function (yy) { return yy >= topo && yy + h <= window.innerHeight - 4; };
    var opcoes = [[cima, todos], [baixo, todos], [cima, textos], [baixo, textos]];
    var y = null;
    for (var i = 0; i < opcoes.length && y === null; i++) {
      if (cabe(opcoes[i][0]) && !cobre(opcoes[i][1], opcoes[i][0])) y = opcoes[i][0];
    }
    if (y === null) y = cabe(cima) ? cima : Math.min(r.top + 4, window.innerHeight - h - 4);
    barra.style.top = Math.round(y) + "px";
    barra.style.left = Math.round(x) + "px";
  }
  function atualizar() {
    if (!atual) return;
    var concl = atual.hasAttribute("data-concluido"), tipo = atual.dataset.tipo || "texto";
    barra.querySelector(".js-bb-concluir").hidden = concl;
    barra.querySelector(".js-bb-desfazer").hidden = !concl;
    barra.querySelector(".js-bb-versoes").hidden = tipo !== "texto";
    barra.querySelector(".js-bb-ref").hidden = !atual.hasAttribute("data-tem-ref");
    barra.querySelector(".js-bb-imagem").hidden = tipo !== "imagem" || concl;
    var p = pendentes(), i = p.indexOf(atual);
    barra.querySelector(".js-bb-n").textContent = p.length ? (concl ? p.length + " pendentes" : (i + 1) + " de " + p.length) : "tudo concluído";
    barra.querySelector(".js-bb-ant").disabled = !p.length || (i <= 0 && !concl);
    barra.querySelector(".js-bb-prox").disabled = !p.length || (i === p.length - 1);
  }
  function mostrar(b) {
    clearTimeout(escondeTimer);
    atual = b;
    barra.hidden = false;
    atualizar();
    posicionar();
  }
  function esconder() {
    clearTimeout(escondeTimer);
    escondeTimer = setTimeout(function () {
      if (barra.matches(":hover") || barra.contains(document.activeElement)) return;
      var a = E.ativo && E.ativo();
      if (a && atual && atual.contains(a.area)) return;      // escrevendo: a barra fica
      barra.hidden = true; atual = null;
    }, 350);
  }

  document.addEventListener("mouseover", function (e) {
    var b = e.target.closest && e.target.closest(".doc-bloco[data-pode-concluir]");
    if (b) mostrar(b);
  });
  document.addEventListener("mouseout", function (e) {
    if (e.target.closest && e.target.closest(".doc-bloco[data-pode-concluir], .bloco-barra")) esconder();
  });
  document.addEventListener("focusin", function (e) {
    var b = e.target.closest && e.target.closest(".doc-bloco[data-pode-concluir]");
    if (b) mostrar(b);
  });
  window.addEventListener("scroll", posicionar, { passive: true });
  window.addEventListener("resize", posicionar);

  // ---- anterior / próximo -----------------------------------------------------------------------
  function ir(sentido) {
    var p = pendentes();
    if (!p.length) return;
    var alvo = null;
    if (atual && p.indexOf(atual) >= 0) alvo = p[p.indexOf(atual) + sentido];
    else if (atual) {       // a partir de um concluído: o pendente mais próximo na ordem do documento
      var depois = p.filter(function (b) { return !!(atual.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); });
      alvo = sentido > 0 ? depois[0] : p[p.length - depois.length - 1];
    }
    if (!alvo) return;
    Promise.resolve(E.fechar()).then(function () {
      E.rolarPara(alvo);
      mostrar(alvo);
      alvo.classList.add("bloco-destaque");
      setTimeout(function () { alvo.classList.remove("bloco-destaque"); }, 1600);
      var area = alvo.querySelector(".doc-texto.editavel");
      if (area) setTimeout(function () { area.focus({ preventScroll: true }); }, 350);
    });
  }
  barra.querySelector(".js-bb-ant").addEventListener("click", function () { ir(-1); });
  barra.querySelector(".js-bb-prox").addEventListener("click", function () { ir(1); });

  // ---- concluir / desfazer ------------------------------------------------------------------------
  function marcar(b, concluido) {
    b.toggleAttribute("data-concluido", concluido);
    b.classList.toggle("concluido", concluido);
    var area = b.querySelector(".doc-texto");
    if (area) {
      area.classList.toggle("editavel", !concluido);
      if (concluido) { area.removeAttribute("tabindex"); area.removeAttribute("role"); }
      else { area.setAttribute("tabindex", "0"); area.setAttribute("role", "textbox"); }
    }
    var sel = b.querySelector(".bloco-selo");
    if (concluido && !sel) { sel = document.createElement("span"); sel.className = "bloco-selo d-print-none"; sel.innerHTML = '<i class="bi bi-check2-circle"></i> Concluído'; b.appendChild(sel); }
    if (!concluido && sel) sel.remove();
    var g = b.querySelector(".bloco-guia"); if (g) g.hidden = concluido;
    atualizar();
    posicionar();
  }
  function enviar(b, acao, confirmar) {
    return T.post(base + "blocos/" + id(b) + "/" + (acao === "concluir" ? "concluir" : "desfazer-conclusao") + "/",
      confirmar ? { confirmar: true } : {}).then(function (r) {
      if (r.confirmar) {
        if (confirm(r.confirmar)) return enviar(b, acao, true);
        return;
      }
      if (!r.ok) { T.aviso(r.erro || "Não foi possível concluir.", "warning"); return; }
      marcar(b, !!r.concluido);
      T.aviso(r.concluido ? "Trecho concluído. Use Reabrir o trecho se precisar mexer de novo." : "Trecho reaberto para edição.", "dark");
      var proximo = r.concluido ? pendentes()[0] : null;
      if (proximo && barra.querySelector(".js-bb-n").textContent === "tudo concluído") T.aviso("Você concluiu todos os seus trechos.", "success");
    });
  }
  barra.querySelector(".js-bb-concluir").addEventListener("click", function () {
    var b = atual; if (!b) return;
    Promise.resolve(E.fechar()).then(function (ok) { if (ok !== false) enviar(b, "concluir"); });
  });
  barra.querySelector(".js-bb-desfazer").addEventListener("click", function () { if (atual) enviar(atual, "desfazer"); });
  barra.querySelector(".js-bb-versoes").addEventListener("click", function () {
    var b = atual; if (!b) return;
    Promise.resolve(E.fechar()).then(function () { T.historico(id(b), E.urlVolta(id(b))); });
  });

  barra.querySelector(".js-bb-ref").addEventListener("click", function () {
    var b = atual, m = document.getElementById("modal-ref-bloco"); if (!b || !m) return;
    var corpo = m.querySelector(".js-ref-corpo");
    corpo.textContent = "Carregando…";
    bootstrap.Modal.getOrCreateInstance(m).show();
    T.get(base + "blocos/" + id(b) + "/referencia/").then(function (r) {
      corpo.innerHTML = r && r.html ? T.limpar(r.html) : "<p class=\"text-secondary\">Sem texto de referência.</p>";
    });
  });

  // ---- imagem do bloco ----------------------------------------------------------------------------
  var modal = document.getElementById("modal-imagem-bloco");
  var form = modal && modal.querySelector(".js-imagem-form");
  var alvoImagem = null;
  function mostrarImagemAtual(b) {
    var cx = modal.querySelector(".js-imagem-atual"), im = b.querySelector(".bloco-imagem img");
    cx.innerHTML = im ? '<img src="' + T.esc(im.getAttribute("src")) + '" alt="" style="max-width:100%;max-height:160px">' : '<p class="mini text-secondary mb-0">Ainda não há imagem neste trecho.</p>';
    form.querySelector("[name=alt]").value = im ? im.getAttribute("alt") || "" : "";
    form.querySelector("[name=ajuste]").value = (b.querySelector(".bloco-imagem") || {}).dataset ? (b.querySelector(".bloco-imagem").dataset.ajuste || "contain") : "contain";
    form.querySelector(".js-imagem-remover").hidden = !im;
    form.querySelector("[name=arquivo]").value = "";
    form.querySelector(".js-imagem-erro").textContent = "";
  }
  function enviarImagem(extra) {
    var fd = new FormData(form);
    if (!fd.get("arquivo") || !fd.get("arquivo").size) fd.delete("arquivo");
    if (extra) Object.keys(extra).forEach(function (k) { fd.set(k, extra[k]); });
    return fetch(base + "blocos/" + id(alvoImagem) + "/imagem/", { method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": T.cfg.csrf }, body: fd }).then(function (r) { return r.json().catch(function () { return { ok: false, erro: "Erro " + r.status }; }); })
      .then(function (r) {
        if (!r.ok) { form.querySelector(".js-imagem-erro").textContent = r.erro || "Não foi possível salvar."; return; }
        bootstrap.Modal.getOrCreateInstance(modal).hide();
        location.hash = "bloco-" + id(alvoImagem);
        location.reload();
      });
  }
  if (form) {
    barra.querySelector(".js-bb-imagem").addEventListener("click", function () {
      if (!atual) return; alvoImagem = atual; mostrarImagemAtual(atual);
      bootstrap.Modal.getOrCreateInstance(modal).show();
    });
    document.addEventListener("click", function (e) {      // clicar na área vazia do bloco de imagem também abre
      var v = e.target.closest && e.target.closest(".doc-bloco[data-pode-concluir][data-tipo=imagem] .bloco-imagem");
      if (!v) return;
      alvoImagem = v.closest(".doc-bloco"); mostrarImagemAtual(alvoImagem);
      bootstrap.Modal.getOrCreateInstance(modal).show();
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); enviarImagem(); });
    form.querySelector(".js-imagem-remover").addEventListener("click", function () {
      if (confirm("Tirar a imagem deste trecho?")) enviarImagem({ remover: "1" });
    });
  }
})();
