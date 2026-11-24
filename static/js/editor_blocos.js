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
  var blocos = D.blocos, sel = [], rascunho = null, z = 1, arrasto = null, salvarTimer = null, area = null;
  var G = D.guias || { grade: {}, linhas: { v: [], h: [] }, pagina: { v: [], h: [] } };
  var guiaSel = null;                 // {eixo: "v"|"h", valor: pt}
  var reguaH = document.getElementById("ed-regua-h"), reguaV = document.getElementById("ed-regua-v");
  var camadaGrade = document.getElementById("ed-grade"), camadaGuias = document.getElementById("ed-guias");
  var verGuias = document.getElementById("ed-ver-guias"), chkEncaixar = document.getElementById("ed-encaixar");
  function lembrar(k, v) { try { window.localStorage.setItem(k, v ? "1" : "0"); } catch (e) { /* sem armazenamento */ } }
  function lembrado(k) { try { return window.localStorage.getItem(k) !== "0"; } catch (e) { return true; } }

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
        if (r.j.guias) G = r.j.guias;
        sel = (r.j.selecionar || []).filter(function (id) { return achar(id); });
        if (guiaSel && G.pagina[guiaSel.eixo].indexOf(guiaSel.valor) < 0) guiaSel = null;
        rascunho = null;
        desenhar(); desenharGuias(); montarPainel();
        dizer(r.j.mensagem);
        return r.j;
      }).catch(function () { dizer("Sem conexão com o servidor.", true); return null; });
  }

  // ---- desenho ---------------------------------------------------------------------------------------------
  function desenhar() {
    caixas.innerHTML = "";
    blocos.forEach(function (b) {
      var e = document.createElement("div");
      e.className = "ed-bloco ed-" + b.tipo + (sel.indexOf(b.id) >= 0 ? " sel" : "") + (b.fixo ? " ed-fixo" : "") +
        (b.numero_antigo ? " ed-numero" : "");
      e.dataset.id = b.id;
      e.style.cssText = "left:" + b.x + "px;top:" + b.y + "px;width:" + b.w + "px;height:" + b.h + "px;--cor:" + b.cor;
      var h = '<div class="ed-conteudo"' + (b.tipo === "texto" ? ' style="' + esc(b.css) + '"' : "") + ">";
      if (b.tipo === "texto") h += b.html || '<span class="ed-vazio">(vazio)</span>';
      else h += '<span class="ed-rotulo-obj"><i class="bi bi-' + (b.tipo === "grafico" ? "bar-chart" : b.tipo === "imagem" ? "image" : "table") + '"></i> ' + esc(b.tipo_nome) + (b.titulo ? ": " + esc(b.titulo) : "") + "</span>";
      h += "</div>";
      if (b.siglas || b.travado_por) h += '<span class="ed-chip">' + (b.travado_por ? '<i class="bi bi-pencil-fill"></i> ' + esc(b.travado_por) + " · " : "") + esc(b.siglas) + "</span>";
      if (b.fora) h += '<span class="ed-fora-sinal" title="Fora da grade e das guias"></span>';
      e.innerHTML = h;
      if (sel.length === 1 && sel[0] === b.id && !LEITURA) {
        ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(function (p) {
          var a = document.createElement("span"); a.className = "ed-al ed-al-" + p; a.dataset.al = p; e.appendChild(a);
        });
      }
      caixas.appendChild(e);
    });
    if (area) {
      var q = document.createElement("div");
      q.className = "ed-area-sel";
      q.style.cssText = "left:" + area.x + "px;top:" + area.y + "px;width:" + area.w + "px;height:" + area.h + "px";
      caixas.appendChild(q);
    }
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
    escala.style.width = Math.round(D.largura * z + 20) + "px";
    escala.style.height = Math.round(D.altura * z + 20) + "px";
    desenharReguas();
  }

  // ---- grade e guias ---------------------------------------------------------------------------------------
  function desenharGuias() {
    var h = "", g = G.grade || {};
    if (g.colunas) {
      h += '<div class="ed-margem" style="left:' + g.margem_esq + "px;top:" + g.margem_sup + "px;width:" +
        (D.largura - g.margem_esq - g.margem_dir) + "px;height:" + (D.altura - g.margem_sup - g.margem_inf) + 'px"></div>';
      (G.linhas.colunas || []).forEach(function (c) {
        h += '<div class="ed-coluna" style="left:' + c[0] + "px;top:" + g.margem_sup + "px;width:" + (c[1] - c[0]) +
          "px;height:" + (D.altura - g.margem_sup - g.margem_inf) + 'px"></div>';
      });
    }
    camadaGrade.innerHTML = h;
    h = "";
    ["v", "h"].forEach(function (eixo) {
      G.pagina[eixo].forEach(function (val) {
        var s = guiaSel && guiaSel.eixo === eixo && guiaSel.valor === val;
        h += '<div class="ed-guia ' + eixo + (s ? " sel" : "") + '" data-eixo="' + eixo + '" data-valor="' + val + '" style="' +
          (eixo === "v" ? "left:" : "top:") + val + 'px" title="Guia ' + (eixo === "v" ? "vertical" : "horizontal") + " em " + val + ' pt · arraste para mover ou para fora da página para apagar"></div>';
      });
    });
    if (arrasto && arrasto.modo === "guia") {
      h += '<div class="ed-guia nova ' + arrasto.eixo + '" style="' + (arrasto.eixo === "v" ? "left:" : "top:") + arrasto.valor + 'px"></div>';
    }
    camadaGuias.innerHTML = h;
  }
  function desenharReguas() {
    var passo = z >= 1 ? 50 : 100, h = "", v = "";
    for (var p = 0; p <= D.largura; p += passo) h += '<span style="left:' + Math.round(p * z) + 'px">' + p + "</span>";
    for (var q = 0; q <= D.altura; q += passo) v += '<span style="top:' + Math.round(q * z) + 'px">' + q + "</span>";
    reguaH.innerHTML = h; reguaV.innerHTML = v;
    var fino = "repeating-linear-gradient(to right, #b6bfcb 0 1px, transparent 1px " + (10 * z) + "px)";
    reguaH.style.width = Math.round(D.largura * z) + "px";
    reguaH.style.background = fino + " bottom left / 100% 5px no-repeat, #f6f8fb";
    reguaV.style.height = Math.round(D.altura * z) + "px";
    reguaV.style.background = fino.replace("to right", "to bottom") + " top right / 5px 100% no-repeat, #f6f8fb";
  }
  function mostrarGuias(v) {
    raiz.classList.toggle("ed-sem-guias", !v);
    if (verGuias) verGuias.checked = v;
  }
  function linhasDo(eixo) {
    var l = (G.linhas[eixo] || []).concat(G.pagina[eixo] || []);
    return l.concat([0, eixo === "v" ? D.largura : D.altura]);
  }
  function maisPerto(val, lista, tol) {
    var melhor = null;
    lista.forEach(function (l) { var d = l - val; if (Math.abs(d) <= tol && (melhor === null || Math.abs(d) < Math.abs(melhor))) melhor = d; });
    return melhor;
  }
  function encaixa(e) { return chkEncaixar && chkEncaixar.checked && !raiz.classList.contains("ed-sem-guias") && !(e && e.altKey); }
  function tolerancia() { return 6 / z; }
  // desloca (x, w) ou (y, h) para a borda mais próxima de uma linha; devolve o deslocamento
  function encaixarMover(pos, tam, eixo) {
    var l = linhasDo(eixo), t = tolerancia(), a = maisPerto(pos, l, t), b = maisPerto(pos + tam, l, t);
    if (a === null && b === null) return 0;
    if (a === null) return b;
    if (b === null) return a;
    return Math.abs(a) <= Math.abs(b) ? a : b;
  }
  function encaixarPonto(val, eixo) { var d = maisPerto(val, linhasDo(eixo), tolerancia()); return d === null ? val : val + d; }
  function ajustarAGrade(b) {                     // ação do botão: leva as bordas para a linha mais próxima (até 20 pt)
    var r = { x: b.x, y: b.y, w: b.w, h: b.h }, lv = linhasDo("v"), lh = (G.linhas.h || []).concat(G.pagina.h || []);
    var e = maisPerto(r.x, lv, 20), d = maisPerto(r.x + r.w, lv, 20);
    var x0 = r.x + (e || 0), x1 = r.x + r.w + (d || 0);
    var y0 = r.y, y1 = r.y + r.h;
    if (G.linhas.h && G.linhas.h.length) {
      if (y0 < G.linhas.h[0] && maisPerto(y0, G.pagina.h, 1) === null) y0 = G.linhas.h[0];
      if (y1 > G.linhas.h[1] && maisPerto(y1, G.pagina.h, 1) === null) y1 = G.linhas.h[1];
    }
    var t = maisPerto(y0, lh, 20), f = maisPerto(y1, lh, 20);
    y0 += t || 0; y1 += f || 0;
    return { x: num(x0), y: num(y0), w: num(Math.max(12, x1 - x0)), h: num(Math.max(12, y1 - y0)) };
  }
  function salvarGuias(msg) {
    return enviar("guias", { guias: G.pagina, selecionar: sel.slice(), mensagem: msg });
  }
  function guiaTexto(eixo) { return eixo === "v" ? "vertical" : "horizontal"; }

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
    if (guiaSel && !rascunho && !sel.length) {
      var gs = guiaSel;
      painel.innerHTML = '<h2 class="h6">Guia ' + guiaTexto(gs.eixo) + '</h2><label class="form-label mini mb-0" for="f-guia">Posição (pt, a partir ' + (gs.eixo === "v" ? "da esquerda" : "de cima") + ')</label>' +
        '<input class="form-control form-control-sm mb-2" id="f-guia" type="number" step="0.5" min="0" max="' + (gs.eixo === "v" ? D.largura : D.altura) + '" value="' + gs.valor + '">' +
        '<div class="d-flex gap-2"><button class="btn btn-sm btn-primary" id="b-guia-ok"><i class="bi bi-check-lg"></i> Salvar</button><button class="btn btn-sm btn-outline-danger ms-auto" id="b-guia-apagar"><i class="bi bi-trash"></i> Apagar</button></div>' +
        '<p class="mini text-secondary mt-3 mb-0">Também dá para arrastar a guia na página. Arrastar para fora da página apaga.</p>';
      var ok = function () {
        var v = parseFloat($("#f-guia").value);
        if (isNaN(v)) return;
        v = num(v);
        var l = G.pagina[gs.eixo].filter(function (x) { return x !== gs.valor; });
        l.push(v); G.pagina[gs.eixo] = l; guiaSel = { eixo: gs.eixo, valor: v };
        salvarGuias("Guia movida.");
      };
      $("#b-guia-ok").onclick = ok;
      $("#f-guia").onkeydown = function (e) { if (e.key === "Enter") ok(); };
      $("#b-guia-apagar").onclick = function () {
        G.pagina[gs.eixo] = G.pagina[gs.eixo].filter(function (x) { return x !== gs.valor; });
        guiaSel = null; salvarGuias("Guia apagada.");
      };
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
      if (b.tipo === "texto" && b.fixo) h += '<div class="alert alert-secondary mini py-2 mt-3 mb-0"><strong>Texto fixo do modelo</strong>' + (b.numero_antigo ? ' <span class="text-warning-emphasis">com número do ano anterior</span>' : "") + ': só o Editor-chefe altera.<br><button class="btn btn-sm btn-outline-primary mt-2" id="b-liberar"><i class="bi bi-unlock"></i> Liberar para o setor</button></div>';
      else if (b.tipo === "texto" && b.referencia && !b.editado) h += '<p class="mini mt-3 mb-0"><button class="btn btn-sm btn-link p-0" id="b-fixar"><i class="bi bi-lock"></i> Voltar ao texto fixo do PDF</button></p>';
      if (b.fora) h += '<div class="alert alert-warning mini py-2 mt-3 mb-0"><strong>Fora da grade.</strong> As bordas do bloco não estão nas colunas da grade nem nas guias desta página.<br><button class="btn btn-sm btn-outline-dark mt-2" id="b-ajustar"><i class="bi bi-magnet"></i> Ajustar à grade</button></div>';
      if (b.previa) h += '<p class="mini text-secondary mt-3 mb-0">' + esc(b.previa) + (b.caracteres > 120 ? "…" : "") + "</p>";
      painel.innerHTML = h;
      if ($("#b-liberar")) $("#b-liberar").onclick = function () { enviar("fixo", { id: b.id, fixo: false }); };
      if ($("#b-fixar")) $("#b-fixar").onclick = function () { enviar("fixo", { id: b.id, fixo: true }); };
      $("#b-salvar").onclick = function () { var d = lerCampos(); d.id = b.id; enviar("salvar", d); };
      if ($("#b-ajustar")) $("#b-ajustar").onclick = function () {
        var r = ajustarAGrade(b); r.id = b.id; enviar("salvar", r);
      };
      $("#b-apagar").onclick = function () { enviar("apagar", { id: b.id }); };
    } else if (sel.length > 1) {
      h = '<h2 class="h6">' + sel.length + " blocos selecionados</h2><ul class=\"mini ps-3\">";
      sel.forEach(function (id) { var b = achar(id); h += "<li>" + esc(b.tipo_nome) + (b.previa ? ": " + esc(b.previa.slice(0, 50)) : "") + "</li>"; });
      var fixos = sel.filter(function (id) { return achar(id).fixo; }).length;
      h += '</ul><p class="mini text-secondary">Juntar cria um só bloco que cobre todos, com o texto na ordem de leitura. A fonte do bloco é a do primeiro. Para trocar um gráfico do PDF por um gráfico do sistema, apague os rótulos dele e desenhe o bloco de gráfico no lugar.</p>' +
        '<div class="d-flex flex-wrap gap-2"><button class="btn btn-sm btn-primary" id="b-juntar"><i class="bi bi-union"></i> Juntar em um bloco</button>' +
        (fixos ? '<button class="btn btn-sm btn-outline-primary" id="b-liberar-v"><i class="bi bi-unlock"></i> Liberar ' + fixos + ' para o setor</button>' : "") +
        '<button class="btn btn-sm btn-outline-danger" id="b-apagar-v"><i class="bi bi-trash"></i> Apagar os ' + sel.length + "</button></div>";
      painel.innerHTML = h;
      $("#b-juntar").onclick = function () { enviar("juntar", { ids: sel.slice() }); };
      $("#b-apagar-v").onclick = function () {
        if (window.confirm("Apagar os " + sel.length + " blocos selecionados?")) enviar("apagar", { ids: sel.slice() });
      };
      if ($("#b-liberar-v")) $("#b-liberar-v").onclick = function () {
        enviar("fixo", { ids: sel.filter(function (id) { return achar(id).fixo; }), fixo: false });
      };
    } else {
      painel.innerHTML = '<h2 class="h6">Blocos da página ' + D.pagina + "</h2><p class=\"mini text-secondary\">" + blocos.length + ' bloco(s). Clique em um bloco para ver e mudar os atributos, ou arraste no fundo da página para desenhar um bloco novo. <strong>Shift + arrastar</strong> seleciona todos os blocos de uma área (por exemplo, os rótulos de um gráfico).</p>' +
        '<ul class="mini ed-legenda ps-0"><li><span class="ed-leg" style="--cor:#6c757d"></span> a cor do contorno é a do setor do bloco</li>' +
        '<li><span class="ed-leg ed-leg-fixo"></span> texto fixo do modelo (só o Editor-chefe altera)</li>' +
        '<li><span class="ed-leg ed-leg-numero"></span> texto fixo com número do ano anterior: confira</li>' +
        '<li><span class="ed-leg ed-leg-grade"></span> margens e colunas da grade do relatório</li>' +
        '<li><span class="ed-leg ed-leg-guia"></span> guia desta página</li>' +
        '<li><span class="ed-leg ed-leg-fora"></span> bloco fora da grade e das guias</li></ul>';
      var fora = blocos.filter(function (b) { return b.fora; });
      if (fora.length) h = '<div class="alert alert-warning mini py-2">' + fora.length + " bloco(s) fora da grade. " +
        '<button class="btn btn-sm btn-link p-0 align-baseline" id="b-sel-fora">Selecionar</button></div>';
      else h = "";
      var nv = G.pagina.v.length, nh = G.pagina.h.length;
      h += '<h2 class="h6 mt-3">Guias desta página</h2>';
      if (!(G.grade && G.grade.colunas)) h += '<p class="mini text-secondary mb-2">O relatório ainda não tem grade (margens e colunas).</p>';
      h += '<p class="mini text-secondary mb-2">' + (nv || nh ? nv + " vertical(is) e " + nh + " horizontal(is). Clique numa guia para mudar a posição." : "Nenhuma. Arraste a partir da régua de cima (horizontal) ou da esquerda (vertical) para criar uma.") + "</p>";
      if (nv || nh) {
        h += '<label class="form-label mini mb-0" for="f-copiar">Copiar estas guias para as páginas</label>' +
          '<div class="input-group input-group-sm mb-1"><input class="form-control" id="f-copiar" placeholder="ex.: 3, 5-8 ou todas"><button class="btn btn-outline-primary" id="b-copiar">Copiar</button></div>' +
          '<div class="form-check mini mb-2"><input class="form-check-input" type="checkbox" id="f-substituir"><label class="form-check-label" for="f-substituir">Substituir as guias que já estão lá</label></div>' +
          '<button class="btn btn-sm btn-link text-danger p-0" id="b-limpar-guias"><i class="bi bi-x-lg"></i> Apagar as guias desta página</button>';
      }
      painel.innerHTML += h;
      if ($("#b-sel-fora")) $("#b-sel-fora").onclick = function () { sel = fora.map(function (b) { return b.id; }); desenhar(); montarPainel(); };
      if ($("#b-copiar")) $("#b-copiar").onclick = function () {
        var t = $("#f-copiar").value.trim();
        if (!t) { dizer("Indique as páginas.", true); return; }
        enviar("copiar_guias", { paginas: t, substituir: $("#f-substituir").checked });
      };
      if ($("#b-limpar-guias")) $("#b-limpar-guias").onclick = function () {
        if (!window.confirm("Apagar as guias desta página? A grade do relatório continua.")) return;
        G.pagina = { v: [], h: [] }; guiaSel = null; salvarGuias("Guias da página apagadas.");
      };
    }
  }

  // ---- mouse -----------------------------------------------------------------------------------------------
  function ponto(e) {
    var r = pg.getBoundingClientRect();
    return { x: (e.clientX - r.left) / z, y: (e.clientY - r.top) / z };
  }
  pg.addEventListener("pointerdown", function (e) {
    if (LEITURA || e.button !== 0) return;
    var p = ponto(e), al = e.target.closest(".ed-al"), alvo = e.target.closest(".ed-bloco"), gu = e.target.closest(".ed-guia");
    if (gu && gu.dataset.eixo) {
      var eixo = gu.dataset.eixo, val = parseFloat(gu.dataset.valor);
      sel = []; rascunho = null; guiaSel = { eixo: eixo, valor: val };
      G.pagina[eixo] = G.pagina[eixo].filter(function (x) { return x !== val; });
      arrasto = { modo: "guia", eixo: eixo, valor: val, orig: val, mexeu: false };
      desenhar(); desenharGuias(); montarPainel();
      pg.setPointerCapture(e.pointerId); e.preventDefault();
      return;
    }
    guiaSel = null;
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
    } else if (e.shiftKey) {
      rascunho = null;
      arrasto = { modo: "area", ini: p, mexeu: false };
    } else {
      sel = []; rascunho = null;
      arrasto = { modo: "novo", ini: p, mexeu: false };
      desenhar(); montarPainel();
    }
    if (arrasto) { pg.setPointerCapture(e.pointerId); e.preventDefault(); }
  });
  pg.addEventListener("pointermove", function (e) {
    if (!arrasto) return;
    if (arrasto.modo === "guia") { moverGuia(e); return; }
    var p = ponto(e), dx = p.x - arrasto.ini.x, dy = p.y - arrasto.ini.y;
    if (!arrasto.mexeu && Math.abs(dx) + Math.abs(dy) < 3) return;
    arrasto.mexeu = true;
    if (arrasto.modo === "area") {
      area = { x: num(Math.min(p.x, arrasto.ini.x)), y: num(Math.min(p.y, arrasto.ini.y)), w: num(Math.abs(dx)), h: num(Math.abs(dy)) };
    } else if (arrasto.modo === "novo") {
      var a0 = arrasto.ini, a1 = p;
      if (encaixa(e)) {
        a0 = { x: encaixarPonto(a0.x, "v"), y: encaixarPonto(a0.y, "h") };
        a1 = { x: encaixarPonto(a1.x, "v"), y: encaixarPonto(a1.y, "h") };
      }
      rascunho = { x: num(Math.min(a0.x, a1.x)), y: num(Math.min(a0.y, a1.y)), w: num(Math.abs(a1.x - a0.x)), h: num(Math.abs(a1.y - a0.y)) };
    } else {
      var b = achar(arrasto.id), o = arrasto.orig;
      if (arrasto.modo === "mover") {
        var nx = o.x + dx, ny = o.y + dy;
        if (encaixa(e)) { nx += encaixarMover(nx, o.w, "v"); ny += encaixarMover(ny, o.h, "h"); }
        b.x = num(nx); b.y = num(ny);
      } else {
        var a = arrasto.al, x = o.x, y = o.y, w = o.w, h = o.h;
        if (a.indexOf("e") >= 0) w = o.w + dx;
        if (a.indexOf("s") >= 0) h = o.h + dy;
        if (a.indexOf("w") >= 0) { x = o.x + dx; w = o.w - dx; }
        if (a.indexOf("n") >= 0) { y = o.y + dy; h = o.h - dy; }
        if (encaixa(e)) {
          if (a.indexOf("e") >= 0) w = encaixarPonto(x + w, "v") - x;
          if (a.indexOf("s") >= 0) h = encaixarPonto(y + h, "h") - y;
          if (a.indexOf("w") >= 0) { var nx0 = encaixarPonto(x, "v"); w += x - nx0; x = nx0; }
          if (a.indexOf("n") >= 0) { var ny0 = encaixarPonto(y, "h"); h += y - ny0; y = ny0; }
        }
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
    if (a.modo === "guia") { soltarGuia(a); return; }
    if (a.modo === "area") {
      if (area) {
        var dentro = blocos.filter(function (b) {     // blocos que tocam a área
          return b.x < area.x + area.w && b.x + b.w > area.x && b.y < area.y + area.h && b.y + b.h > area.y;
        }).map(function (b) { return b.id; });
        dentro.forEach(function (id) { if (sel.indexOf(id) < 0) sel.push(id); });
        area = null;
        if (dentro.length) dizer(dentro.length + " bloco(s) na área.");
      }
      desenhar(); montarPainel();
    } else if (a.modo === "novo") {
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

  // ---- guias: arrastar da régua, mover, apagar ----------------------------------------------------------------
  function moverGuia(e) {
    var p = ponto(e), v = arrasto.eixo === "v" ? p.x : p.y;
    if (!arrasto.mexeu && Math.abs(v - arrasto.orig) < 1.5) return;
    arrasto.mexeu = true;
    if (encaixa(e)) {                                  // a guia encaixa nas linhas da grade e nas outras guias
      var d = maisPerto(v, (G.linhas[arrasto.eixo] || []).concat(G.pagina[arrasto.eixo]), tolerancia());
      if (d !== null) v += d;
    }
    arrasto.valor = num(v);
    var dentro = arrasto.valor >= 0 && arrasto.valor <= (arrasto.eixo === "v" ? D.largura : D.altura);
    dizer(dentro ? "Guia " + guiaTexto(arrasto.eixo) + " em " + arrasto.valor + " pt" : "Solte fora da página para apagar a guia");
    desenharGuias();
  }
  function soltarGuia(a) {
    var lim = a.eixo === "v" ? D.largura : D.altura;
    if (a.nova && !a.mexeu) { desenharGuias(); return; }
    if (!a.mexeu) {                                    // clique: a guia fica selecionada para mudar a posição
      G.pagina[a.eixo].push(a.orig); G.pagina[a.eixo].sort(function (x, y) { return x - y; });
      desenharGuias(); montarPainel();
      return;
    }
    if (a.valor < 0 || a.valor > lim) {
      guiaSel = null;
      if (a.nova) { desenharGuias(); dizer(""); return; }
      salvarGuias("Guia apagada.");
      return;
    }
    if (G.pagina[a.eixo].indexOf(a.valor) < 0) G.pagina[a.eixo].push(a.valor);
    guiaSel = { eixo: a.eixo, valor: a.valor };
    salvarGuias(a.nova ? "Guia criada." : "Guia movida.");
  }
  function iniciarNaRegua(eixo) {
    return function (e) {
      if (LEITURA || e.button !== 0) return;
      mostrarGuias(true); lembrar("sirg-ed-guias", true);
      sel = []; rascunho = null; guiaSel = null;
      arrasto = { modo: "guia", eixo: eixo, valor: -1, orig: -1, mexeu: false, nova: true };
      this.setPointerCapture(e.pointerId); e.preventDefault();
      desenhar(); montarPainel();
    };
  }
  [[reguaH, "h"], [reguaV, "v"]].forEach(function (r) {
    if (!r[0]) return;
    r[0].addEventListener("pointerdown", iniciarNaRegua(r[1]));
    r[0].addEventListener("pointermove", function (e) { if (arrasto && arrasto.modo === "guia") moverGuia(e); });
    r[0].addEventListener("pointerup", soltar);
    r[0].addEventListener("pointercancel", soltar);
  });
  camadaGuias.addEventListener("dblclick", function (e) {
    var gu = e.target.closest(".ed-guia");
    if (gu && $("#f-guia")) { $("#f-guia").focus(); $("#f-guia").select(); }
  });

  // ---- teclado ---------------------------------------------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    if (LEITURA || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
    if (e.key === "Escape") { sel = []; rascunho = null; guiaSel = null; desenhar(); desenharGuias(); montarPainel(); return; }
    if ((e.key === "g" || e.key === "G") && !e.ctrlKey && !e.metaKey && !e.altKey) { mostrarGuias(!verGuias.checked); lembrar("sirg-ed-guias", verGuias.checked); return; }
    if (guiaSel && !sel.length && e.key === "Delete") {
      var gs = guiaSel; guiaSel = null;
      G.pagina[gs.eixo] = G.pagina[gs.eixo].filter(function (x) { return x !== gs.valor; });
      salvarGuias("Guia apagada."); e.preventDefault(); return;
    }
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
  if (LEITURA) raiz.classList.add("ed-leitura");
  mostrarGuias(lembrado("sirg-ed-guias"));
  if (chkEncaixar) chkEncaixar.checked = lembrado("sirg-ed-encaixar");
  if (verGuias) verGuias.onchange = function () { mostrarGuias(this.checked); lembrar("sirg-ed-guias", this.checked); };
  if (chkEncaixar) chkEncaixar.onchange = function () { lembrar("sirg-ed-encaixar", this.checked); };
  desenhar(); desenharGuias(); montarPainel();
})();
