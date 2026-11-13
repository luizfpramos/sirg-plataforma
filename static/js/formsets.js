/* Adiciona linhas aos formsets (linhas, colunas e regras do quadro). */
(function () {
  document.querySelectorAll(".js-mais").forEach(function (bt) {
    bt.addEventListener("click", function () {
      var p = bt.dataset.prefixo;
      var total = document.getElementById("id_" + p + "-TOTAL_FORMS");
      var tpl = document.getElementById("vazio-" + p);
      var corpo = document.querySelector("#tab-" + p + " tbody");
      if (!total || !tpl || !corpo) return;
      var n = parseInt(total.value, 10);
      var html = tpl.innerHTML.replace(/__prefix__/g, n);
      corpo.insertAdjacentHTML("beforeend", html);
      total.value = n + 1;
      var nova = corpo.lastElementChild;
      var ordem = nova.querySelector('input[name$="-ordem"]');
      if (ordem) {
        var max = 0;
        corpo.querySelectorAll('input[name$="-ordem"]').forEach(function (i) { max = Math.max(max, parseInt(i.value || "0", 10)); });
        ordem.value = max + 1;
      }
      var foco = nova.querySelector('input[name$="-rotulo"], input[name$="-descricao"]');
      if (foco) foco.focus();
    });
  });
})();
