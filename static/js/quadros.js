/*
 * Grade de preenchimento dos quadros do SiRG.
 * - Salva cada célula ao sair dela (ou Enter), mostrando "salvando…" / "salvo" / erro.
 * - Atualiza na hora as linhas calculadas, os totais e as pendências do quadro.
 * - Detecta quando outra pessoa alterou a célula ao mesmo tempo (conflito).
 * - Enter/↓ desce, ↑ sobe, colar do Excel preenche várias células.
 * - Ano travado (Master): pede justificativa antes de gravar.
 */
(function () {
  "use strict";
  var CFG = window.SIRG || {};
  var url = function (sufixo) { return "/ciclos/" + CFG.ano + "/celula/" + (sufixo || ""); };
  var toastEl = document.getElementById("toast");
  var toast = toastEl ? bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4000 }) : null;

  function aviso(msg, tipo) {
    if (!toast) { alert(msg); return; }
    toastEl.className = "toast align-items-center border-0 text-bg-" + (tipo || "dark");
    toastEl.querySelector(".toast-body").textContent = msg;
    toast.show();
  }

  function postar(sufixo, dados) {
    return fetch(url(sufixo), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CFG.csrf },
      credentials: "same-origin",
      body: JSON.stringify(dados)
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, erro: "Resposta inesperada do servidor (" + r.status + ")." }; })
        .then(function (j) { j._status = r.status; return j; });
    }).catch(function () { return { ok: false, erro: "Sem conexão com o servidor. O valor não foi salvo." }; });
  }

  function valorDe(el) { return el.tagName === "SELECT" ? el.value : el.value; }

  // ---- atualização do quadro com a resposta do servidor -----------------
  // gráfico ao lado da grade: redesenha depois que os valores mudam
  var esperaGrafico = {};
  function atualizarGrafico(card) {
    var caixa = card.querySelector(".js-grafico");
    if (!caixa) return;
    var id = card.dataset.quadro;
    clearTimeout(esperaGrafico[id]);
    caixa.classList.add("atualizando");
    caixa.querySelector(".js-grafico-status").textContent = "atualizando…";
    esperaGrafico[id] = setTimeout(function () {
      fetch("/ciclos/" + CFG.ano + "/quadros/" + id + "/graficos/", { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var corpo = caixa.querySelector(".js-grafico-corpo");
          var figs = corpo.querySelectorAll("figure .grafico");
          j.graficos.forEach(function (g, i) {
            if (figs[i]) figs[i].innerHTML = g.svg || '<p class="grafico-vazio">O gráfico aparece aqui assim que houver valores.</p>';
          });
          caixa.classList.remove("atualizando");
          caixa.querySelector(".js-grafico-status").textContent = "atualizado às " + new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        })
        .catch(function () { caixa.classList.remove("atualizando"); caixa.querySelector(".js-grafico-status").textContent = "não foi possível atualizar"; });
    }, 500);
  }

  function aplicarQuadro(card, r) {
    atualizarGrafico(card);
    Object.keys(r.celulas || {}).forEach(function (id) {
      var td = document.getElementById("c-" + id);
      if (!td) return;
      var c = r.celulas[id];
      td.classList.remove("erro", "aviso", "falta");
      if (c.severidade) td.classList.add(c.severidade);
      td.title = c.erro_formula || (c.mensagens || []).join(" · ");
      if (!td.classList.contains("ed")) {
        var hist = td.querySelector(".cel-hist");
        td.textContent = c.erro_formula ? "⚠" : c.exibido;
        if (hist) td.appendChild(hist);
      } else {
        if (td.classList.contains("importada")) {      // fonte única: valor automático em cinza no campo
          var ci = td.querySelector(".cel-input");
          if (ci) { ci.placeholder = c.auto || ""; ci.dataset.auto = c.auto || ""; }
          td.classList.toggle("usa-auto", !c.digitado);
          if (!c.mensagens || !c.mensagens.length) td.title = "Automático: " + (c.auto || "ainda sem valor") + ". Você pode digitar outro valor.";
        }
        var bj = td.querySelector(".cel-just");
        if (c.pede_justificativa && !bj) {
          var inp = td.querySelector(".cel-input");
          bj = document.createElement("button");
          bj.type = "button"; bj.className = "cel-just"; bj.tabIndex = -1;
          bj.dataset.l = inp.dataset.l; bj.dataset.c = inp.dataset.c; bj.dataset.texto = "";
          bj.title = "Justificar a variação";
          bj.innerHTML = '<i class="bi bi-chat-left-text"></i>';
          td.appendChild(bj);
        }
      }
    });
    var lista = card.querySelector(".js-pendencias");
    if (lista) {
      lista.innerHTML = "";
      (r.pendencias || []).forEach(function (p) {
        var li = document.createElement("li");
        li.className = p.severidade;
        var a = document.createElement("a");
        a.href = "#" + p.ancora; a.className = "js-ir"; a.textContent = p.mensagem;
        li.appendChild(a);
        if (p.detalhe) { var s = document.createElement("span"); s.className = "text-secondary"; s.textContent = " — " + p.detalhe; li.appendChild(s); }
        if (p.acao && card.querySelector(".cel-input")) {
          var acoes = document.createElement("span");
          acoes.className = "acoes-div text-nowrap";
          [["corrigir", "Corrigir: usar " + p.acao.auto, "btn-outline-primary"], ["ignorar", "Ignorar: manter " + p.acao.digitado, "btn-outline-secondary"]]
            .forEach(function (a) {
              var bt = document.createElement("button");
              bt.type = "button"; bt.className = "btn btn-xs js-div " + a[2]; bt.textContent = a[1];
              bt.dataset.acao = a[0]; bt.dataset.l = p.acao.linha; bt.dataset.c = p.acao.coluna;
              acoes.appendChild(document.createTextNode(" ")); acoes.appendChild(bt);
            });
          li.appendChild(acoes);
        }
        lista.appendChild(li);
      });
    }
    var cont = card.querySelector(".js-contagem");
    if (cont) {
      var h = "";
      if (r.erros) h += '<span class="badge text-bg-danger">' + r.erros + " para corrigir</span> ";
      if (r.avisos) h += '<span class="badge text-bg-warning">' + r.avisos + " para conferir</span> ";
      if (r.faltam) h += '<span class="badge badge-falta">' + r.faltam + " a preencher</span>";
      if (!r.erros && !r.faltam && r.aguardando) h = '<span class="badge badge-aguarda" title="Há cálculos que dependem de outros quadros ainda não preenchidos">aguardando dados</span>';
      else if (!r.erros && !r.avisos && !r.faltam) h = '<span class="badge text-bg-success"><i class="bi bi-check2"></i> ok</span>';
      cont.innerHTML = h;
    }
    var prog = card.querySelector(".js-progresso");
    if (prog && r.total_celulas) prog.textContent = r.preenchidas + " de " + r.total_celulas + " preenchidas";
  }

  // ---- gravação --------------------------------------------------------------
  function salvar(el, justificativa) {
    var td = el.closest("td");
    var card = el.closest(".quadro");
    var novo = valorDe(el);
    var anterior = el.dataset.anterior !== undefined ? el.dataset.anterior : el.defaultValue;
    if (novo === anterior && !justificativa) return Promise.resolve();
    if (el.dataset.travada === "1" && !justificativa) {
      return pedirJustificativa("Este ano já foi publicado. Explique por que o valor está sendo alterado (fica registrado no histórico).", "")
        .then(function (t) {
          if (t === null) { el.value = anterior; return; }
          return salvar(el, t);
        });
    }
    td.classList.remove("salvo", "falhou");
    el.removeAttribute("aria-invalid");
    var msgVelha = td.querySelector(".cel-erro");
    if (msgVelha) msgVelha.remove();
    td.classList.add("salvando");
    return postar("", { linha: el.dataset.l, coluna: el.dataset.c, valor: novo, anterior: anterior, justificativa: justificativa || "" })
      .then(function (r) {
        td.classList.remove("salvando");
        if (r.ok) {
          el.value = r.edicao;
          el.defaultValue = r.edicao;
          el.dataset.anterior = r.edicao;
          td.classList.add("salvo");
          setTimeout(function () { td.classList.remove("salvo"); }, 2500);
          aplicarQuadro(card, r);
          document.dispatchEvent(new CustomEvent("sirg:celula"));
          return;
        }
        td.classList.add("falhou");
        if (r.conflito) {
          if (confirm("Outra pessoa alterou esta célula enquanto você editava.\n\nValor gravado agora: " + (r.atual || "(vazio)") +
                      "\nSeu valor: " + (novo || "(vazio)") + "\n\nOK = manter o SEU valor   ·   Cancelar = ficar com o valor gravado")) {
            el.dataset.anterior = r.atual;
            td.classList.remove("falhou");
            return salvar(el, justificativa);
          }
          el.value = r.atual; el.defaultValue = r.atual; el.dataset.anterior = r.atual;
          td.classList.remove("falhou");
          return;
        }
        td.title = r.erro || "Não foi possível salvar.";
        // o erro fica na própria célula (borda vermelha + mensagem embaixo); Esc volta ao valor anterior
        el.setAttribute("aria-invalid", "true");
        var msg = document.createElement("div");
        msg.className = "cel-erro";
        msg.id = "erro-" + (el.id || (el.dataset.l + "-" + el.dataset.c));
        msg.textContent = (r.erro || "Não foi possível salvar.") + " (Esc desfaz)";
        td.appendChild(msg);
        el.setAttribute("aria-describedby", msg.id);
        aviso(r.erro || "Não foi possível salvar.", "danger");
        document.dispatchEvent(new CustomEvent("sirg:celula"));
      });
  }

  // ---- justificativa (modal) ----------------------------------------------------
  var modalJ = document.getElementById("modal-just");
  var mj = modalJ ? bootstrap.Modal.getOrCreateInstance(modalJ) : null;
  var resolverJust = null;
  function pedirJustificativa(explicacao, texto) {
    return new Promise(function (resolve) {
      if (!mj) { resolve(prompt(explicacao, texto || "")); return; }
      resolverJust = resolve;
      modalJ.querySelector(".js-just-explica").textContent = explicacao;
      var ta = document.getElementById("just-texto");
      ta.value = texto || "";
      mj.show();
      setTimeout(function () { ta.focus(); }, 300);
    });
  }
  if (modalJ) {
    document.getElementById("just-ok").addEventListener("click", function () {
      var t = document.getElementById("just-texto").value.trim();
      if (!t) { document.getElementById("just-texto").focus(); return; }
      var r = resolverJust; resolverJust = null; mj.hide(); if (r) r(t);
    });
    modalJ.addEventListener("hidden.bs.modal", function () { if (resolverJust) { var r = resolverJust; resolverJust = null; r(null); } });
  }

  // ---- histórico (modal) -----------------------------------------------------------
  var modalH = document.getElementById("modal-hist");
  function mostrarHistorico(l, c) {
    fetch(url(l + "/" + c + "/historico/"), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) {
      document.getElementById("modal-hist-titulo").textContent = "Histórico — " + j.titulo;
      var corpo = document.getElementById("hist-corpo");
      corpo.innerHTML = "";
      if (!j.itens.length) corpo.innerHTML = '<tr><td colspan="4" class="text-secondary">Nenhuma alteração registrada.</td></tr>';
      j.itens.forEach(function (it) {
        var tr = document.createElement("tr");
        [it.quando, it.quem, it.valor, [it.motivo, it.justificativa].filter(Boolean).filter(function (v, i, a) { return a.indexOf(v) === i; }).join(" · ")]
          .forEach(function (t) { var td = document.createElement("td"); td.textContent = t; tr.appendChild(td); });
        corpo.appendChild(tr);
      });
      bootstrap.Modal.getOrCreateInstance(modalH).show();
    });
  }

  // ---- navegação e colagem --------------------------------------------------------------
  function grade(el) { return el.closest("table"); }
  function posicao(el) {
    var td = el.closest("td"), tr = td.parentElement;
    return { linha: Array.prototype.indexOf.call(tr.parentElement.children, tr), col: Array.prototype.indexOf.call(tr.children, td), tbody: tr.parentElement };
  }
  function inputEm(tbody, linha, col) {
    var tr = tbody.children[linha];
    if (!tr) return null;
    var td = tr.children[col];
    return td ? td.querySelector(".cel-input") : null;
  }
  function mover(el, dl) {
    var p = posicao(el);
    for (var i = p.linha + dl; i >= 0 && i < p.tbody.children.length; i += dl) {
      var alvo = inputEm(p.tbody, i, p.col);
      if (alvo) { alvo.focus(); if (alvo.select) alvo.select(); return true; }
    }
    return false;
  }

  document.addEventListener("focusin", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("cel-input")) return;
    if (el.dataset.anterior === undefined) el.dataset.anterior = el.defaultValue !== undefined ? el.defaultValue : el.value;
    el.closest("td").classList.add("foco");
  });
  document.addEventListener("focusout", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("cel-input")) return;
    el.closest("td").classList.remove("foco");
    if (el.tagName !== "SELECT") salvar(el);
  });
  document.addEventListener("change", function (e) {
    if (e.target.tagName === "SELECT" && e.target.classList.contains("cel-input")) salvar(e.target);
  });
  document.addEventListener("keydown", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("cel-input") || el.tagName === "SELECT") return;
    if (el.tagName === "TEXTAREA") {          // texto: Enter desce (Shift+Enter quebra a linha); setas andam no texto
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!mover(el, 1)) el.blur(); }
      else if (e.key === "Escape") { el.value = el.dataset.anterior || ""; limparErro(el); el.blur(); }
      return;
    }
    if (e.key === "Enter" || e.key === "ArrowDown") { e.preventDefault(); if (!mover(el, 1)) el.blur(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); mover(el, -1); }
    else if (e.key === "Escape") { el.value = el.dataset.anterior || ""; limparErro(el); el.blur(); }
  });
  function limparErro(el) {
    var td = el.closest("td");
    td.classList.remove("falhou");
    el.removeAttribute("aria-invalid");
    el.removeAttribute("aria-describedby");
    var m = td.querySelector(".cel-erro");
    if (m) m.remove();
    document.dispatchEvent(new CustomEvent("sirg:celula"));
  }
  document.addEventListener("paste", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("cel-input")) return;
    var txt = (e.clipboardData || window.clipboardData).getData("text");
    if (!txt || (txt.indexOf("\t") < 0 && txt.indexOf("\n") < 0)) return;  // colagem simples: comportamento normal
    e.preventDefault();
    var linhas = txt.replace(/\r/g, "").replace(/\n$/, "").split("\n").map(function (l) { return l.split("\t"); });
    var p = posicao(el);
    var fila = [];
    linhas.forEach(function (vals, i) {
      vals.forEach(function (v, j) {
        var alvo = inputEm(p.tbody, p.linha + i, p.col + j);
        if (alvo && alvo.dataset.travada !== "1") {
          if (alvo.dataset.anterior === undefined) alvo.dataset.anterior = alvo.defaultValue;
          alvo.value = v.trim();
          fila.push(alvo);
        }
      });
    });
    fila.reduce(function (pr, alvo) { return pr.then(function () { return salvar(alvo); }); }, Promise.resolve())
      .then(function () { aviso(fila.length + " célula" + (fila.length > 1 ? "s coladas e salvas." : " colada e salva."), "success"); });
  });

  // ---- botões das células ------------------------------------------------------------------
  document.addEventListener("click", function (e) {
    var dv = e.target.closest(".js-div");
    if (dv) {
      e.preventDefault();
      var cardD = dv.closest(".quadro");
      dv.disabled = true;
      postar("divergencia/", { linha: dv.dataset.l, coluna: dv.dataset.c, acao: dv.dataset.acao }).then(function (r) {
        if (!r.ok) { dv.disabled = false; aviso(r.erro || "Não foi possível salvar.", "danger"); return; }
        var td = document.getElementById("c-" + r.celula);
        var inp = td ? td.querySelector(".cel-input") : null;
        if (inp) { inp.value = r.edicao; inp.defaultValue = r.edicao; inp.dataset.anterior = r.edicao; }
        aplicarQuadro(cardD, r);
        aviso(dv.dataset.acao === "corrigir" ? "Corrigido: vale o valor automático." : "Divergência ignorada: fica o valor digitado.", "success");
      });
      return;
    }
    var h = e.target.closest(".cel-hist");
    if (h) { e.preventDefault(); mostrarHistorico(h.dataset.l, h.dataset.c); return; }
    var j = e.target.closest(".cel-just");
    if (j) {
      e.preventDefault();
      var card = j.closest(".quadro");
      pedirJustificativa("Explique a variação em relação ao ano anterior (ela acompanha o dado no relatório e no histórico).", j.dataset.texto)
        .then(function (t) {
          if (t === null) return;
          postar("justificar/", { linha: j.dataset.l, coluna: j.dataset.c, justificativa: t }).then(function (r) {
            if (!r.ok) { aviso(r.erro || "Não foi possível salvar.", "danger"); return; }
            j.dataset.texto = t; j.classList.add("feita"); j.title = "Justificativa: " + t;
            aplicarQuadro(card, r);
            aviso("Justificativa registrada.", "success");
          });
        });
      return;
    }
    var ir = e.target.closest(".js-ir");
    if (ir) {
      var alvo = document.getElementById(ir.getAttribute("href").slice(1));
      if (alvo) {
        e.preventDefault();
        alvo.scrollIntoView({ behavior: "smooth", block: "center" });
        var inp = alvo.querySelector ? alvo.querySelector(".cel-input") : null;
        if (inp) setTimeout(function () { inp.focus(); }, 350);
        alvo.classList.add("piscar"); setTimeout(function () { alvo.classList.remove("piscar"); }, 1600);
      }
    }
  });

  // âncora vinda da tela de inconsistências
  if (location.hash && location.hash.indexOf("#c-") === 0) {
    var alvo = document.getElementById(location.hash.slice(1));
    if (alvo) { alvo.scrollIntoView({ block: "center" }); alvo.classList.add("piscar"); var i = alvo.querySelector(".cel-input"); if (i) i.focus(); }
  }

  window.addEventListener("beforeunload", function (e) {
    if (document.querySelector("td.salvando")) { e.preventDefault(); e.returnValue = ""; }
  });
})();
