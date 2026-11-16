/* Editor visual de blocos (administrador): desenhar, mover, redimensionar, juntar e apagar blocos na página. */
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("dados-editor").textContent);
  var raiz = document.getElementById("editor");
  var URL_BASE = raiz.dataset.url.replace(/x\/$/, "");
  var CSRF = raiz.dataset.csrf;
  var pg = document.getElementById("ed-pg"), caixas = document.getElementById("ed-caixas");
  var painel = document.getElementById("ed-painel"), statusEl = document.getElementById("ed-status");
  var escala = document.getElementById("ed-escala");
  var LEITURA = !!D.somente_leitura;
  var blocos = D.blocos, sel = [], rascunho = null, z = 1, arrasto = null, salvarTimer = null;

  function $(s, r) { return (r || document).querySelector(s); }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function num(v) { return Math.round(v * 10) / 10; }
  function achar(id) { for (var i = 0; i < blocos.length; i++) if (blocos[i].id === id) return blocos[i]; return null; }
  function dizer(txt, erro) {
    statusEl.textContent = txt || "";
    statusEl.className = "ed-status mini" + (erro ? " text-danger fw-semibold" : " text-success");
    if (txt && !erro) setTimeout(function () { if (statusEl.textContent === txt) statusEl.textContent = ""; }, 3500);
  }

  // ---- servidor ---------------------------------------------------------------------------------------------
  function enviar(acao, dados, confirmado) {
    if (confirmado) dados.confirmar = true;
    return fetch(URL_BASE + acao + "/", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF }, body: JSON.stringify(dados)
    }).then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
      .then(function (r) {
        if (r.status === 409 && r.j.confirmar) {
          if (window.confirm(r.j.confirmar)) return enviar(acao, dados, true);
          return null;
        }
        if (!r.j.ok) { dizer(r.j.erro || "Não foi possível salvar.", true); return null; }
        blocos = r.j.blocos;
        sel = (r.j.selecionar || []).filter(function (id) { return achar(id); });
        rascunho = null;
        desenhar(); montarPainel();
        dizer(r.j.mensagem);
        return r.j;
      }).catch(function () { dizer("Sem conexão com o servidor.", true); return null; });
  }

  // ---- desenho ---------------------------------------------------------------------------------------------
  function desenhar() {
    caixas.innerHTML = "";
    blocos.forEach(function (b) {
      var e = document.createElement("div");
      e.className = "ed-bloco ed-" + b.tipo + (sel.indexOf(b.id) >= 0 ? " sel" : "");
      e.dataset.id = b.id;
      e.style.cssText = "left:" + b.x + "px;top:" + b.y + "px;width:" + b.w + "px;height:" + b.h + "px;--cor:" + b.cor;
      var h = '<div class="ed-conteudo"' + (b.tipo === "texto" ? ' style="' + esc(b.css) + '"' : "") + ">";
      if (b.tipo === "texto") h += b.html || '<span class="ed-vazio">(vazio)</span>';
      else h += '<span class="ed-rotulo-obj"><i class="bi bi-' + (b.tipo === "grafico" ? "bar-chart" : b.tipo === "imagem" ? "image" : "table") + '"></i> ' + esc(b.tipo_nome) + (b.titulo ? ": " + esc(b.titulo) : "") + "</span>";
      h += "</div>";
      if (b.siglas || b.travado_por) h += '<span class="ed-chip">' + (b.travado_por ? '<i class="bi bi-pencil-fill"></i> ' + esc(b.travado_por) + " · " : "") + esc(b.siglas) + "</span>";
      e.innerHTML = h;
      if (sel.length === 1 && sel[0] === b.id && !LEITURA) {
        ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(function (p) {
          var a = document.createElement("span"); a.className = "ed-al ed-al-" + p; a.dataset.al = p; e.appendChild(a);
        });
      }
      caixas.appendChild(e);
    });
    if (rascunho) {
      var r = document.createElement("div");
      r.className = "ed-rascunho";
      r.style.cssText = "left:" + rascunho.x + "px;top:" + rascunho.y + "px;width:" + rascunho.w + "px;height:" + rascunho.h + "px";
      caixas.appendChild(r);
    }
  }

  function ajustarZoom(v) {
    z = v;
    pg.style.transform = "scale(" + z + ")";
    escala.style.width = Math.round(D.largura * z) + "px";
    escala.style.height = Math.round(D.altura * z) + "px";
  }

  // ---- painel ----------------------------------------------------------------------------------------------
  function opcoes(lista, atual, vazio, rotulo) {
    var h = vazio != null ? '<option value="">' + esc(vazio) + "</option>" : "";
    lista.forEach(function (o) { h += '<option value="' + o.id + '"' + (String(o.id) === String(atual) ? " selected" : "") + ">" + esc(o[rotulo]) + "</option>"; });
    return h;
  }
  function camposComuns(b, novo) {
    var g = b || rascunho;
    var h = "";
    if (novo) {
      h += '<label class="form-label mini mb-0" for="f-tipo">Tipo</label><select class="form-select form-select-sm mb-2" id="f-tipo"><option value="texto">Texto</option><option value="grafico">Gráfico de um quadro</option><option value="tabela">Tabela de um quadro</option><option value="imagem">Imagem</option></select>';
      h += '<div id="f-quadro-box" class="d-none"><label class="form-label mini mb-0" for="f-quadro">Quadro de números</label><select class="form-select form-select-sm mb-2" id="f-quadro">' + opcoes(D.opcoes.quadros, "", "(escolha)", "titulo") + "</select></div>";
    } else {
      h += '<p class="mini mb-2"><strong>' + esc(b.tipo_nome) + "</strong>" + (b.tipo === "texto" ? " · " + b.caracteres + " caracteres" : "") + (b.editado ? " · <span class=\"text-primary\">tem texto escrito pelos setores</span>" : "") + "</p>";
      if (b.travado_por) h += '<p class="mini text-warning-emphasis mb-2"><i class="bi bi-pencil-fill"></i> ' + esc(b.travado_por) + " está editando este texto agora.</p>";
      if (b.comentarios || b.sugestoes) h += '<p class="mini mb-2"><i class="bi bi-chat-left-text"></i> ' + b.comentarios + " comentário(s), " + b.sugestoes + " sugestão(ões) pendente(s).</p>";
    }
    h += '<label class="form-label mini mb-0" for="f-secao">Seção</label><select class="form-select form-select-sm mb-2" id="f-secao">' + opcoes(D.opcoes.secoes, g.secao, null, "titulo") + "</select>";
    h += '<label class="form-label mini mb-0" for="f-setor">Setor responsável</label><select class="form-select form-select-sm mb-2" id="f-setor">' + opcoes(D.opcoes.setores, g.setor, "(o da seção)", "sigla") + "</select>";
    h += '<label class="form-label mini mb-0" for="f-desc">Conteúdo esperado</label><textarea class="form-control form-control-sm mb-2" id="f-desc" rows="3">' + esc(g.descricao || "") + "</textarea>";
    h += '<div class="row g-2 mb-2"><div class="col"><label class="form-label mini mb-0" for="f-min">Mín. caracteres</label><input class="form-control form-control-sm" id="f-min" type="number" min="0" value="' + (g.min == null ? "" : g.min) + '"></div>';
    h += '<div class="col"><label class="form-label mini mb-0" for="f-max">Máx. caracteres</label><input class="form-control form-control-sm" id="f-max" type="number" min="0" value="' + (g.max == null ? "" : g.max) + '"></div></div>';
    h += '<div class="row g-2 mb-3">' + ["x", "y", "w", "h"].map(function (k) {
      return '<div class="col-3"><label class="form-label mini mb-0" for="f-' + k + '">' + ({ x: "X", y: "Y", w: "Larg.", h: "Alt." })[k] + '</label><input class="form-control form-control-sm px-1" id="f-' + k + '" type="number" step="0.5" value="' + g[k] + '"></div>';
    }).join("") + "</div>";
    return h;
  }
  function lerCampos() {
    var d = { secao: $("#f-secao").value, setor: $("#f-setor").value, descricao: $("#f-desc").value, min: $("#f-min").value, max: $("#f-max").value };
    ["x", "y", "w", "h"].forEach(function (k) { d[k] = $("#f-" + k).value; });
    return d;
  }
  function secaoPerto(r) {
    var melhor = null, dist = 1e9, cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    blocos.forEach(function (b) {
      var d = Math.abs(b.x + b.w / 2 - cx) + Math.abs(b.y + b.h / 2 - cy) * 0.6;
      if (b.tipo === "texto" && d < dist) { dist = d; melhor = b; }
    });
    return melhor ? melhor.secao : D.secao_da_pagina;
  }

  function montarPainel() {
    var h = "";
    if (LEITURA) {
      painel.innerHTML = '<p class="mini text-secondary">O ciclo está encerrado: somente leitura.</p>';
      return;
    }
    if (rascunho) {
      h = '<h2 class="h6">Novo bloco</h2>' + camposComuns(null, true) +
        '<div class="d-flex gap-2"><button class="btn btn-sm btn-primary" id="b-criar"><i class="bi bi-plus-lg"></i> Criar bloco</button><button class="btn btn-sm btn-outline-secondary" id="b-cancelar">Cancelar</button></div>';
      painel.innerHTML = h;
      $("#f-tipo").onchange = function () { $("#f-quadro-box").classList.toggle("d-none", this.value === "texto" || this.value === "imagem"); };
      ["x", "y", "w", "h"].forEach(function (k) {
        $("#f-" + k).oninput = function () { rascunho[k] = parseFloat(this.value) || 0; desenhar(); };
      });
      $("#b-cancelar").onclick = function () { rascunho = null; desenhar(); montarPainel(); };
      $("#b-criar").onclick = function () {
        var d = lerCampos(); d.tipo = $("#f-tipo").value; d.quadro = $("#f-quadro").value;
        enviar("criar", d);
      };
    } else if (sel.length === 1) {
      var b = achar(sel[0]);
      h = '<h2 class="h6">Bloco selecionado</h2>' + camposComuns(b, false) +
        '<div class="d-flex flex-wrap gap-2"><button class="btn btn-sm btn-primary" id="b-salvar"><i class="bi bi-check-lg"></i> Salvar</button><button class="btn btn-sm btn-outline-danger ms-auto" id="b-apagar"><i class="bi bi-trash"></i> Apagar</button></div>';
      if (b.previa) h += '<p class="mini text-secondary mt-3 mb-0">' + esc(b.previa) + (b.caracteres > 120 ? "…" : "") + "</p>";
      painel.innerHTML = h;
      $("#b-salvar").onclick = function () { var d = lerCampos(); d.id = b.id; enviar("salvar", d); };
      $("#b-apagar").onclick = function () { enviar("apagar", { id: b.id }); };
    } else if (sel.length > 1) {
      h = '<h2 class="h6">' + sel.length + " blocos selecionados</h2><ul class=\"mini ps-3\">";
      sel.forEach(function (id) { var b = achar(id); h += "<li>" + esc(b.tipo_nome) + (b.previa ? ": " + esc(b.previa.slice(0, 50)) : "") + "</li>"; });
      h += '</ul><p class="mini text-secondary">Juntar cria um só bloco que cobre todos, com o texto na ordem de leitura. A fonte do bloco é a do primeiro.</p>' +
        '<button class="btn btn-sm btn-primary" id="b-juntar"><i class="bi bi-union"></i> Juntar em um bloco</button>';
      painel.innerHTML = h;
      $("#b-juntar").onclick = function () { enviar("juntar", { ids: sel.slice() }); };
    } else {
      painel.innerHTML = '<h2 class="h6">Blocos da página ' + D.pagina + "</h2><p class=\"mini text-secondary\">" + blocos.length + ' bloco(s). Clique em um bloco para ver e mudar os atributos, ou arraste no fundo da página para desenhar um bloco novo.</p>' +
        '<ul class="mini ed-legenda ps-0"><li><span class="ed-leg" style="--cor:#6c757d"></span> a cor do contorno é a do setor do bloco</li></ul>';
    }
  }

  // ---- mouse -----------------------------------------------------------------------------------------------
  function ponto(e) {
    var r = pg.getBoundingClientRect();
    return { x: (e.clientX - r.left) / z, y: (e.clientY - r.top) / z };
  }
  pg.addEventListener("pointerdown", function (e) {
    if (LEITURA || e.button !== 0) return;
    var p = ponto(e), al = e.target.closest(".ed-al"), alvo = e.target.closest(".ed-bloco");
    if (al && sel.length === 1) {
      var b = achar(sel[0]);
      arrasto = { modo: "alca", al: al.dataset.al, id: b.id, ini: p, orig: { x: b.x, y: b.y, w: b.w, h: b.h }, mexeu: false };
    } else if (alvo) {
      var id = parseInt(alvo.dataset.id, 10);
      rascunho = null;
      if (e.shiftKey) { sel = sel.indexOf(id) >= 0 ? sel.filter(function (s) { return s !== id; }) : sel.concat(id); arrasto = null; }
      else {
        if (sel.indexOf(id) < 0) sel = [id];
        var bb = achar(id);
        arrasto = { modo: "mover", id: id, ini: p, orig: { x: bb.x, y: bb.y, w: bb.w, h: bb.h }, mexeu: false };
      }
      desenhar(); montarPainel();
    } else {
      sel = []; rascunho = null;
      arrasto = { modo: "novo", ini: p, mexeu: false };
      desenhar(); montarPainel();
    }
    if (arrasto) { pg.setPointerCapture(e.pointerId); e.preventDefault(); }
  });
  pg.addEventListener("pointermove", function (e) {
    if (!arrasto) return;
    var p = ponto(e), dx = p.x - arrasto.ini.x, dy = p.y - arrasto.ini.y;
    if (!arrasto.mexeu && Math.abs(dx) + Math.abs(dy) < 3) return;
    arrasto.mexeu = true;
    if (arrasto.modo === "novo") {
      rascunho = { x: num(Math.min(p.x, arrasto.ini.x)), y: num(Math.min(p.y, arrasto.ini.y)), w: num(Math.abs(dx)), h: num(Math.abs(dy)) };
    } else {
      var b = achar(arrasto.id), o = arrasto.orig;
      if (arrasto.modo === "mover") { b.x = num(o.x + dx); b.y = num(o.y + dy); }
      else {
        var a = arrasto.al, x = o.x, y = o.y, w = o.w, h = o.h;
        if (a.indexOf("e") >= 0) w = o.w + dx;
        if (a.indexOf("s") >= 0) h = o.h + dy;
        if (a.indexOf("w") >= 0) { x = o.x + dx; w = o.w - dx; }
        if (a.indexOf("n") >= 0) { y = o.y + dy; h = o.h - dy; }
        if (w < 12) { if (a.indexOf("w") >= 0) x -= 12 - w; w = 12; }
        if (h < 12) { if (a.indexOf("n") >= 0) y -= 12 - h; h = 12; }
        b.x = num(x); b.y = num(y); b.w = num(w); b.h = num(h);
      }
    }
    desenhar();
  });
  function soltar() {
    if (!arrasto) return;
    var a = arrasto; arrasto = null;
    if (a.modo === "novo") {
      if (rascunho && rascunho.w >= 12 && rascunho.h >= 12) { rascunho.secao = secaoPerto(rascunho); rascunho.setor = ""; rascunho.descricao = ""; rascunho.min = null; rascunho.max = null; }
      else rascunho = null;
      desenhar(); montarPainel();
    } else if (a.mexeu) {
      var b = achar(a.id);
      enviar("salvar", { id: b.id, x: b.x, y: b.y, w: b.w, h: b.h });
    } else montarPainel();
  }
  pg.addEventListener("pointerup", soltar);
  pg.addEventListener("pointercancel", soltar);

  // ---- teclado ---------------------------------------------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    if (LEITURA || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
    if (e.key === "Escape") { sel = []; rascunho = null; desenhar(); montarPainel(); return; }
    if (sel.length === 1 && e.key === "Delete") { enviar("apagar", { id: sel[0] }); e.preventDefault(); return; }
    var passo = e.shiftKey ? 10 : 1, mov = { ArrowLeft: [-passo, 0], ArrowRight: [passo, 0], ArrowUp: [0, -passo], ArrowDown: [0, passo] }[e.key];
    if (!mov || sel.length !== 1) return;
    e.preventDefault();
    var b = achar(sel[0]); b.x = num(b.x + mov[0]); b.y = num(b.y + mov[1]);
    desenhar();
    clearTimeout(salvarTimer);
    salvarTimer = setTimeout(function () { enviar("salvar", { id: b.id, x: b.x, y: b.y, w: b.w, h: b.h }); }, 450);
  });

  // ---- início ----------------------------------------------------------------------------------------------
  var ir = document.getElementById("ed-ir");
  if (ir) ir.onchange = function () { window.location.href = this.value; };
  var zs = document.getElementById("ed-zoom");
  var cabe = Math.min(1.25, Math.max(0.5, Math.floor(((document.getElementById("ed-area").clientWidth - 24) / D.largura) * 20) / 20));
  var padrao = [0.5, 0.75, 1, 1.25].reduce(function (a, v) { return v <= cabe + 0.001 ? v : a; }, 0.5);
  zs.value = String(padrao); ajustarZoom(padrao);
  zs.onchange = function () { ajustarZoom(parseFloat(this.value)); };
  desenhar(); montarPainel();
})();
