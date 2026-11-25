"""Reimportação de um PDF revisado: o ciclo já tem páginas e os setores já escreveram; a diagramação mudou.

Troca o fundo das páginas e reposiciona os blocos que vieram do PDF, SEM mexer no que está escrito neles:
- cada caixa de texto do PDF novo é pareada com um bloco da mesma página (posição parecida ou texto parecido);
- bloco pareado: só muda a posição, o tamanho e a fonte da caixa; o conteúdo, o setor e os atributos ficam;
- caixa nova do PDF, sem bloco: vira bloco novo (com o texto do PDF);
- bloco sem caixa no PDF novo: fica onde estava e é marcado, para o administrador decidir no editor de blocos;
- página que só existe no ciclo: fica como está; blocos feitos no editor (gráficos, tabelas, textos desenhados) não se movem.
As páginas são pareadas pelo número. Antes de aplicar, `gravar_copia` guarda a posição antiga em JSON.
"""
import json
import re
from difflib import SequenceMatcher

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import importador as I
from .models import Bloco, Ciclo, ImportacaoPDF, Pagina

LIMITE_POSICAO = 0.25        # sobreposição mínima das caixas (interseção / união)
LIMITE_TEXTO = 0.7           # semelhança mínima do texto quando a posição não bate
DISTANCIA_MAXIMA = 70        # pt entre os centros, na segunda passada (texto reescrito pelo setor que andou um pouco)


def _texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _sobreposicao(a, b):
    ix = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    inter = ix * iy
    uniao = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / uniao if uniao > 0 else 0


def _semelhanca(a, b):
    a, b = _texto(a)[:400].lower(), _texto(b)[:400].lower()
    return SequenceMatcher(None, a, b).ratio() if a and b else 0


def e_do_pdf(b):
    """Bloco de texto que veio de um PDF importado (os feitos no editor ou de outros tipos não se movem)."""
    return b.tipo == Bloco.TEXTO and "caixa" in (b.config or {}) and "importacao" in b.config


def parear(blocos, caixas):
    """Pareia blocos e caixas (guloso, do melhor par para o pior). Devolve ({id_do_bloco: caixa}, [blocos sem par],
    [caixas sem par])."""
    pares = []
    for b in blocos:
        for i, c in enumerate(caixas):
            sob = _sobreposicao(b.config["caixa"], c)
            sem = _semelhanca(b.conteudo or (b.config or {}).get("referencia_pdf", ""), c["texto"])
            if sob >= LIMITE_POSICAO or sem >= LIMITE_TEXTO:
                pares.append((sob + sem, b.pk, i))
    pares.sort(reverse=True)
    usados_b, usados_c, feito = set(), set(), {}
    for _, bid, i in pares:
        if bid in usados_b or i in usados_c:
            continue
        usados_b.add(bid)
        usados_c.add(i)
        feito[bid] = caixas[i]
    # segunda passada: o setor reescreveu o texto e a caixa andou, então nem posição nem texto bateram
    centro = lambda c: (c["x"] + c["w"] / 2, c["y"] + c["h"] / 2)      # noqa: E731
    perto = []
    for b in blocos:
        if b.pk in usados_b:
            continue
        (bx, by) = centro(b.config["caixa"])
        for i, c in enumerate(caixas):
            if i not in usados_c:
                d = ((bx - centro(c)[0]) ** 2 + (by - centro(c)[1]) ** 2) ** 0.5
                if d <= DISTANCIA_MAXIMA:
                    perto.append((d, b.pk, i))
    perto.sort()
    for _, bid, i in perto:
        if bid in usados_b or i in usados_c:
            continue
        usados_b.add(bid)
        usados_c.add(i)
        feito[bid] = caixas[i]
    return (feito, [b for b in blocos if b.pk not in usados_b],
            [c for i, c in enumerate(caixas) if i not in usados_c])


def motivo_para_nao_reimportar(imp):
    if imp.situacao == ImportacaoPDF.APLICADA:
        return "Este PDF já foi aplicado ao ciclo."
    if imp.situacao != ImportacaoPDF.PRONTA:
        return "O PDF ainda não foi lido."
    if imp.ciclo.situacao == Ciclo.ENCERRADO:
        return "O ciclo está encerrado."
    if not imp.ciclo.paginas.exists():
        return "Este ciclo ainda não tem páginas. Use \"Aplicar ao ciclo\"."
    return ""


def _por_pagina(imp):
    """Para cada página do PDF novo: (página do ciclo ou None, caixas do corpo, caixas fixas, blocos do PDF)."""
    paginas = I.paginas_lidas(imp)
    e_fixo = I.textos_fixos(paginas)
    existentes = {p.numero: p for p in imp.ciclo.paginas.all()}
    blocos = {}
    for b in Bloco.objects.filter(secao__ciclo=imp.ciclo, pagina__in=existentes.values()).select_related("pagina"):
        if e_do_pdf(b):
            blocos.setdefault(b.pagina.numero, []).append(b)
    saida = []
    for p in paginas:
        corpo = [c for c in p["caixas"] if not e_fixo(c, p["h"])]
        fixas = [c for c in p["caixas"] if e_fixo(c, p["h"])]
        saida.append((p, existentes.get(p["n"]), corpo, fixas, sorted(blocos.get(p["n"], []), key=lambda b: b.ordem)))
    return paginas, e_fixo, existentes, saida


def plano(imp):
    """O que a reimportação faria, sem gravar nada. Para o administrador conferir antes de aplicar."""
    paginas, _, existentes, saida = _por_pagina(imp)
    novos = {p["n"] for p in paginas}
    itens, tot = [], {"paginas_novas": 0, "pareados": 0, "novos": 0, "sem_par": 0, "com_texto_sem_par": 0}
    for p, pg, corpo, _, blocos in saida:
        feito, sem_par, novas = parear(blocos, corpo)
        item = {"n": p["n"], "nova": pg is None, "pareados": len(feito), "novos": len(novas), "sem_par": len(sem_par)}
        itens.append(item)
        tot["paginas_novas"] += pg is None
        tot["pareados"] += len(feito)
        tot["novos"] += len(novas)
        tot["sem_par"] += len(sem_par)
        tot["com_texto_sem_par"] += sum(1 for b in sem_par if _texto(b.conteudo))
    tot["so_no_ciclo"] = sorted(n for n in existentes if n not in novos)
    return {"paginas": itens, "total": tot}


def gravar_copia(ciclo):
    """Posição e fundo de cada página e bloco antes da reimportação (para desfazer à mão, se preciso)."""
    dados = {"paginas": [{"numero": p.numero, "fundo": p.fundo, "largura": p.largura, "altura": p.altura}
                         for p in ciclo.paginas.all()],
             "blocos": [{"id": b.pk, "pagina": b.pagina.numero, "caixa": (b.config or {}).get("caixa")}
                        for b in Bloco.objects.filter(secao__ciclo=ciclo, pagina__isnull=False)
                        .select_related("pagina")]}
    destino = (settings.DADOS_DIR / f"posicoes_antes_da_reimportacao_{ciclo.ano}_{timezone.now():%Y%m%d_%H%M%S}.json")
    try:
        destino.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    except OSError:  # pragma: no cover - disco
        pass
    return destino.name


def reimportar(imp, user):
    """Aplica o PDF revisado ao ciclo que já tem páginas, sem tocar no conteúdo escrito. Devolve o resumo."""
    from .html_seguro import limpar
    from .paginas import _caixa_css, _coluna
    motivo = motivo_para_nao_reimportar(imp)
    if motivo:
        raise I.Recusado(motivo)
    ciclo = imp.ciclo
    paginas, e_fixo, existentes, saida = _por_pagina(imp)
    if not paginas:
        raise I.Recusado("Não há páginas lidas neste PDF.")
    inicios = I.inicios_gravados(ciclo, exceto=imp)
    if inicios:      # as seções que já não existem saem; as novas ficam com a página prevista ou com o que o sistema achar
        inicios = {k: v for k, v in inicios.items() if ciclo.secoes.filter(pk=k).exists()}
        for s in ciclo.secoes.filter(pagina_inicio__isnull=False).exclude(pk__in=list(inicios)):
            inicios[s.pk] = s.pagina_inicio
    try:
        marcos, faltam = I.marcos_com_escolhas(ciclo, paginas, e_fixo, inicios or None)
    except I.Recusado:            # página escolhida antes não existe no PDF novo: volta ao que o sistema achar
        marcos, faltam = I.marcos_com_escolhas(ciclo, paginas, e_fixo, None)
    limite = I.limite_de_titulo(paginas)
    primeira = sorted(ciclo.secoes.select_related("pai"), key=I._ordem_secao)[0]

    def dono(n, col, y):
        atual = None
        for m in marcos:
            if m[:3] <= (n, col, y):
                atual = m[3]
            else:
                break
        return atual or primeira

    copia = gravar_copia(ciclo)
    feito = {"paginas_novas": 0, "pareados": 0, "novos": 0, "sem_par": 0}
    with transaction.atomic():
        for p, pg, corpo, fixas, blocos in saida:
            n, W, H = p["n"], p["w"], p["h"]
            fixos = "".join(f'<div class="pg-fixo" style="{_caixa_css(c)}">{limpar(c["html"])}</div>' for c in fixas)
            if pg is None:
                pg = Pagina.objects.create(ciclo=ciclo, numero=n, largura=W, altura=H, fundo=I.url_fundo(imp, n),
                                           secao=dono(n, 0, 0), fixos=fixos)
                feito["paginas_novas"] += 1
            else:
                pg.largura, pg.altura, pg.fundo, pg.fixos = W, H, I.url_fundo(imp, n), fixos
                pg.save(update_fields=["largura", "altura", "fundo", "fixos"])
            pares, sem_par, novas = parear(blocos, corpo)
            for b in blocos:
                cfg = dict(b.config or {})
                if b.pk in pares:
                    c = pares[b.pk]
                    cfg["caixa"] = dict(cfg["caixa"], x=c["x"], y=c["y"], w=c["w"], h=c["h"], css=c["css"],
                                        quebra=c["quebra"])
                    cfg["importacao"] = imp.pk
                    cfg.pop("sem_par_no_pdf", None)
                    feito["pareados"] += 1
                else:
                    cfg["sem_par_no_pdf"] = imp.pk
                    feito["sem_par"] += 1
                Bloco.objects.filter(pk=b.pk).update(config=cfg)      # só a posição: nem o texto nem a data mudam
            base = n * 1000 + 800
            for i, c in enumerate(sorted(novas, key=lambda c: (_coluna(c, W), c["y"], c["x"]))):
                secao = dono(n, _coluna(c, W), c["y"])
                html, extra, minimo, maximo, _ = I.conteudo_da_caixa(c, secao, limite, ciclo.automatico)
                Bloco.objects.create(
                    secao=secao, pagina=pg, tipo=Bloco.TEXTO, ordem=base + i, conteudo=html,
                    min_caracteres=minimo, max_caracteres=maximo,
                    config={"caixa": {"x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"], "css": c["css"],
                                      "quebra": c["quebra"]}, "importacao": imp.pk, "campos212": True,
                            "novo_na_reimportacao": True, **extra})
                feito["novos"] += 1
        resumo = dict(imp.resumo or {}, reimportado=dict(feito, copia=copia,
                                                         so_no_ciclo=sorted(set(existentes) - {p["n"] for p in paginas})),
                      secoes_achadas=len(marcos), secoes_faltando=[s.titulo for s in faltam])
        ImportacaoPDF.objects.filter(pk=imp.pk).update(
            situacao=ImportacaoPDF.APLICADA, aplicada_em=timezone.now(), aplicada_por=user, resumo=resumo)
    imp.refresh_from_db()
    return feito
