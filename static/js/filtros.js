/*
 * Filtros na própria tela (sem recarregar): setor, capítulo, seção, situação, tipo e busca por palavra.
 *
 *   <div class="filtros" data-alvo="#lista">  ...  <select data-campo="setor">  <input data-campo="busca">
 *   itens filtrados:  [data-item] com data-f-setor="DIRGRAD DPPG" data-f-cap="12" data-f-cap-nome="..." ...
 *   grupos:           [data-grupo] somem quando nenhum item dentro deles aparece
 * As opções das listas vêm dos próprios itens (só aparece o que existe na tela).
 */
(function () {
  "use strict";
  function semAcento(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  document.querySelectorAll(".filtros[data-alvo]").forEach(function (caixa) {
    var alvo = document.querySelector(caixa.dataset.alvo);
    if (!alvo) return;
    var itens = Array.prototype.slice.call(alvo.querySelectorAll("[data-item]"));
    var campos = Array.prototype.slice.call(caixa.querySelectorAll("[data-campo]"));
    var chave = "sirg-filtros-" + location.pathname;
    var contador = caixa.querySelector(".js-filtro-n");
    var limpar = caixa.querySelector(".js-filtro-limpar");

    // monta as opções a partir dos itens
    campos.forEach(function (c) {
      if (c.tagName !== "SELECT" || c.dataset.fixo) return;
      var vistos = {}, opcoes = [];
      itens.forEach(function (it) {
        var v = it.getAttribute("data-f-" + c.dataset.campo);
        if (!v) return;
        var nome = it.getAttribute("data-f-" + c.dataset.campo + "-nome");
        v.split(" ").forEach(function (x, i) {
          if (!x || vistos[x]) return;
          vistos[x] = true;
          opcoes.push([x, nome && v.indexOf(" ") < 0 ? nome : x, it.getAttribute("data-f-" + c.dataset.campo + "-pai") || ""]);
        });
      });
      if (c.dataset.ordenar) opcoes.sort(function (a, b) { return a[1].localeCompare(b[1], "pt-BR"); });
      opcoes.forEach(function (o) {
        var op = document.createElement("option");
        op.value = o[0]; op.textContent = o[1]; op.dataset.pai = o[2];
        c.appendChild(op);
      });
    });

    function valores() {
      var v = {};
      campos.forEach(function (c) { v[c.dataset.campo] = c.value; });
      return v;
    }
    function aplicar() {
      var v = valores();
      // a lista de seções mostra só as do capítulo escolhido
      var secSel = caixa.querySelector('[data-campo="secao"]');
      if (secSel) {
        Array.prototype.forEach.call(secSel.options, function (o) { if (o.value) o.hidden = !!v.cap && o.dataset.pai !== v.cap; });
        if (secSel.selectedOptions[0] && secSel.selectedOptions[0].hidden) { secSel.value = ""; v.secao = ""; }
      }
      var palavras = semAcento(v.busca).split(/\s+/).filter(Boolean);
      var n = 0;
      itens.forEach(function (it) {
        var ok = campos.every(function (c) {
          var campo = c.dataset.campo, quer = v[campo];
          if (!quer || campo === "busca") return true;
          return (" " + (it.getAttribute("data-f-" + campo) || "") + " ").indexOf(" " + quer + " ") >= 0;
        });
        if (ok && palavras.length) {
          var txt = semAcento(it.textContent + " " + (it.getAttribute("data-f-busca") || ""));
          ok = palavras.every(function (p) { return txt.indexOf(p) >= 0; });
        }
        it.hidden = !ok;
        if (ok) n++;
      });
      alvo.querySelectorAll("[data-grupo]").forEach(function (g) {
        g.hidden = !g.querySelector("[data-item]:not([hidden])");
      });
      var ativos = campos.some(function (c) { return !!c.value; });
      if (contador) contador.textContent = ativos ? n + " de " + itens.length + " mostrados" : itens.length + " no total";
      if (limpar) limpar.hidden = !ativos;
      var vazio = alvo.querySelector(".js-filtro-vazio");
      if (vazio) vazio.hidden = n > 0 || !ativos;
      try { sessionStorage.setItem(chave, JSON.stringify(v)); } catch (e) { /* sem armazenamento */ }
    }
    campos.forEach(function (c) { c.addEventListener(c.tagName === "INPUT" ? "input" : "change", aplicar); });
    if (limpar) limpar.addEventListener("click", function () { campos.forEach(function (c) { c.value = ""; }); aplicar(); });
    // botões/cartões que aplicam um filtro (ex.: "a preencher")
    document.querySelectorAll("[data-filtrar]").forEach(function (b) {
      b.addEventListener("click", function (e) {
        var partes = b.dataset.filtrar.split("=");
        var c = caixa.querySelector('[data-campo="' + partes[0] + '"]');
        if (!c) return;
        e.preventDefault();
        c.value = c.value === partes[1] ? "" : partes[1];
        aplicar();
        caixa.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    var salvos = null;
    try { salvos = JSON.parse(sessionStorage.getItem(chave) || "null"); } catch (e) { salvos = null; }
    // filtros vindos no endereço (?setor=DPG) valem mais que os guardados
    var daUrl = {};
    try { new URLSearchParams(location.search).forEach(function (v, k) { daUrl[k] = v; }); } catch (e) { daUrl = {}; }
    if (campos.some(function (c) { return daUrl[c.dataset.campo]; })) salvos = daUrl;
    if (salvos) campos.forEach(function (c) {
      if (salvos[c.dataset.campo] && (c.tagName !== "SELECT" || c.querySelector('option[value="' + CSS.escape(salvos[c.dataset.campo]) + '"]'))) c.value = salvos[c.dataset.campo];
    });
    aplicar();
  });
})();
