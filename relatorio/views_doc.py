"""
O relatório como documento:
  - Escrever (editor de documento): o relatório inteiro numa "folha", e cada pessoa digita
    direto no texto das seções que pode alterar; o resto aparece travado.
  - Ler: o texto final, somente leitura, para todos.
  - Gráficos ao vivo para a tela de dados.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from contas import permissoes as P

from . import apresentacao as A
from . import consistencia
from . import fluxo as F
from .calculo import Calculadora
from .models import Bloco, Ciclo, Comentario, Quadro, Secao, Sugestao
from . import nome_inst
from .texto import contar_marcas
from .views_texto import _json, diff_palavras


def _secoes_do_usuario(user, ciclo):
    meus = set(P.setores_ativos(user).values_list("pk", flat=True))
    return {s.pk for s in ciclo.secoes.prefetch_related("setores") if meus & {x.pk for x in s.setores.all()}}


def estrutura(ciclo, calc, user=None, editor=False):
    """Capítulos e seções com os blocos montados, na ordem do documento.
    No modo editor, cada seção traz também o que o usuário pode fazer nela."""
    secoes = list(ciclo.secoes.select_related("pai").prefetch_related("setores").order_by("ordem", "id"))
    blocos = {}
    for b in Bloco.objects.filter(secao__ciclo=ciclo).select_related("quadro", "editando_por").prefetch_related(
            "campos").order_by("ordem", "id"):
        blocos.setdefault(b.secao_id, []).append(b)
    sugestoes, comentarios = {}, {}
    minhas = set()
    if editor:
        for s in Sugestao.objects.filter(bloco__secao__ciclo=ciclo, situacao=Sugestao.PENDENTE).select_related("autor"):
            s.diff = diff_palavras(s.original, s.proposto, calc)
            sugestoes.setdefault(s.bloco_id, []).append(s)
        for c in Comentario.objects.filter(secao__ciclo=ciclo, resolvido=False, pai__isnull=True).select_related("autor"):
            comentarios.setdefault(c.bloco_id or f"s{c.secao_id}", []).append(c)
        minhas = _secoes_do_usuario(user, ciclo)
    pend = {}
    if editor:
        for p in consistencia.verificar(ciclo, calc):
            if not A.so_texto(p.quadro):           # metas (texto) são preenchidas no próprio documento
                pend.setdefault(p.quadro.secao_id, []).append(p)

    def item(s):
        d = {"s": s, "blocos": [], "minha": s.pk in minhas, "marcas": 0, "n_alt": 0, "campos_vazios": 0}
        pode = F.pode_editar_texto(user, s) if editor else False
        for b in blocos.get(s.pk, []):
            m = A.montar_bloco(calc, b, revisao=editor, user=user if editor else None, pode_campos=pode,
                               **A.tamanho_na_pagina(b))
            A.caixa_na_pagina(b, m)
            d["campos_vazios"] += m.get("campos_vazios", 0)
            d["tem_campos"] = d.get("tem_campos") or "sirg-campo" in (b.conteudo or "")
            if b.tipo == Bloco.TEXTO:
                d["marcas"] += contar_marcas(b.conteudo) + nome_inst.contar(b.conteudo)
                d["n_alt"] += m.get("n_alteracoes", 0)
            if editor and b.tipo == Bloco.TABELA and b.quadro_id and b.quadro.tipo_valor == "texto":
                m["metas"] = A.metas_para_editar(calc, calc.quadro_por_id[b.quadro_id], user)
            if editor:
                m["sugestoes"] = sugestoes.get(b.pk, [])
                m["comentarios"] = comentarios.get(b.pk, [])
                m["travado_por"] = b.editando_por if (F.trava_ativa(b) and b.editando_por_id != user.pk) else None
                m["versao"] = b.atualizado_em.isoformat()
            d["blocos"].append(m)
        if editor:
            d["pode"] = pode
            d["sugerir"] = F.pode_sugerir(user, s)
            d["responder"] = F.pode_responder_sugestao(user, s)
            d["motivo"] = F.motivo_texto_bloqueado(user, s)
            d["acoes"] = F.acoes_possiveis(user, s)
            d["comentarios"] = comentarios.get(f"s{s.pk}", [])
            # números da seção: os quadros dela e os de outra seção que saem numa tabela/gráfico dela
            de_fora = {b.quadro_id for b in blocos.get(s.pk, []) if b.tipo != Bloco.TEXTO and b.quadro_id
                       and b.quadro_id in calc.quadro_por_id and calc.quadro_por_id[b.quadro_id].secao_id != s.pk}
            extra = [p for lst in pend.values() for p in lst if p.quadro.pk in de_fora]
            from . import permissoes as RP
            extra_meu = [p for p in extra if RP.pode_editar_quadro(user, p.quadro)]   # de outro setor: não conta
            d["resumo"] = consistencia.resumo(pend.get(s.pk, []) + extra_meu)
            d["faltam"] = d["resumo"]["faltam"] + d["campos_vazios"]
            d["tem_dados"] = any(q.secao_id == s.pk and not A.so_texto(q) for q in calc.quadros.values())
            proprios = sorted([q for q in calc.quadros.values() if q.secao_id == s.pk and not A.so_texto(q)],
                              key=lambda q: (q.ordem, q.pk))
            proprios += [calc.quadro_por_id[i] for i in de_fora if not A.so_texto(calc.quadro_por_id[i])]
            faltas_q = {}
            for p in pend.get(s.pk, []) + extra:
                if p.severidade == "falta":
                    faltas_q[p.quadro.pk] = faltas_q.get(p.quadro.pk, 0) + 1
            d["quadros"] = [{"q": q, "faltam": faltas_q.get(q.pk, 0)} for q in proprios]
            d["vazia"] = not any(m["b"].tipo != Bloco.TEXTO or m.get("html") for m in d["blocos"])
            # Seções que não interessam a esta pessoa aparecem como texto corrido, sem ferramentas.
            d["interessa"] = bool(d["pode"] or d["minha"] or d["responder"] or d["acoes"] or d["comentarios"] or d["n_alt"])
        return d

    caps = []
    for cap in [s for s in secoes if s.pai_id is None]:
        c = item(cap)
        c["secoes"] = [item(s) for s in secoes if s.pai_id == cap.pk]
        caps.append(c)
    return caps


def em_paginas(ciclo, caps):
    """O documento nas páginas do RG: [{"tipo": "pagina", "p", "caixas", "objetos", "secoes"} | {"tipo": "secao",
    "it", "blocos"}], na ordem. As seções (ou partes) que não estão em página nenhuma (ex.: a planilha de metas
    do apêndice) aparecem no lugar delas, entre as páginas. None se o ciclo não tem páginas."""
    paginas = list(ciclo.paginas.all())
    if not paginas:
        return None
    por_pk = {p.pk: {"tipo": "pagina", "p": p, "caixas": [], "objetos": [], "secoes": []} for p in paginas}
    todas = [x for cap in caps for x in [cap] + cap["secoes"]]
    fora, primeira, ultima = {}, {}, {}
    for it in todas:
        sk = it["s"].pk
        for d in it["blocos"]:
            pg = por_pk.get(d["b"].pagina_id)
            if pg is None:
                fora.setdefault(sk, []).append(d)
                continue
            (pg["caixas"] if d["b"].tipo == Bloco.TEXTO else pg["objetos"]).append({"d": d, "it": it})
            n = pg["p"].numero
            primeira[sk] = min(primeira.get(sk, n), n)
            ultima[sk] = max(ultima.get(sk, 0), n)
    por_numero = {x["p"].numero: x for x in por_pk.values()}
    for it in todas:
        if it["s"].pk in primeira:
            por_numero[primeira[it["s"].pk]]["secoes"].append(it)
    # onde entra o que está fora das páginas: depois da última página da seção (ou da seção anterior)
    depois_de, visto = {}, 0
    for it in todas:
        sk = it["s"].pk
        visto = ultima.get(sk, visto)
        resto = fora.get(sk, [])
        if sk in primeira:
            # seção que está nas páginas: o que ficou de fora é só texto acrescentado depois (gráficos e tabelas que
            # não existem no RG publicado ficam no botão Dados da seção)
            resto = [d for d in resto if d["b"].tipo == Bloco.TEXTO and (d.get("html") or it.get("pode"))]
            resto = [d for d in resto if not (d["b"].config or {}).get("modelo")]
        if resto and any(d["b"].tipo != Bloco.TEXTO or d.get("html") or it.get("pode") for d in resto):
            depois_de.setdefault(ultima.get(sk, visto), []).append({"tipo": "secao", "it": it, "blocos": resto})
    seq = list(depois_de.get(0, []))
    for n in sorted(por_numero):
        seq.append(por_numero[n])
        seq += depois_de.get(n, [])
    return seq


# --- Escrever (editor de documento) ------------------------------------------------------
@login_required
def escrever(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    calc = Calculadora(c)
    caps = estrutura(c, calc, request.user, editor=True)
    seq = em_paginas(c, caps)
    todas = [x for cap in caps for x in [cap] + cap["secoes"]]
    editaveis = [x for x in todas if x["pode"]]
    tem_outras = any(not x["interessa"] for x in todas)
    minhas = [x for x in todas if x["minha"]]
    inicio = request.GET.get("secao") or ""
    if not inicio:
        alvo = next((x for x in minhas if x["pode"]), None) or (minhas[0] if minhas else None)
        inicio = alvo["s"].chave if alvo else ""
    return render(request, "relatorio/escrever.html", {
        "ciclo": c, "caps": caps, "seq": seq, "n_editaveis": len(editaveis), "minhas": minhas, "inicio": inicio,
        "ano_ref": c.ano - 1, "ano_ref_txt": str(c.ano - 1), "tem_referencia": any(x["s"].referencia for x in todas),
        "n_marcas": sum(x["marcas"] for x in todas), "n_marcas_minhas": sum(x["marcas"] for x in minhas),
        "e_master": P.e_master(request.user), "modo_coleta": c.situacao == Ciclo.COLETA,
        "n_alt": sum(x["n_alt"] for x in todas), "n_faltam": sum(x["faltam"] for x in editaveis),
        "pode_comentar": F.pode_comentar(request.user, c.secoes.first())
        if c.secoes.exists() else False,
        "tem_outras": tem_outras and any(x["interessa"] for x in todas)})


@login_required
def escrever_estado(request, ano):
    """Quem está editando o quê e a versão de cada trecho (o editor consulta a cada 20 s)."""
    out = {}
    for b in Bloco.objects.filter(secao__ciclo__ano=ano, tipo=Bloco.TEXTO).select_related("editando_por"):
        por = ""
        if F.trava_ativa(b) and b.editando_por_id != request.user.pk:
            por = b.editando_por.get_full_name() or b.editando_por.username
        out[b.pk] = {"v": b.atualizado_em.isoformat(), "por": por}
    return JsonResponse({"blocos": out})


@login_required
def bloco_html(request, ano, pk):
    b = get_object_or_404(Bloco.objects.select_related("secao__ciclo"), pk=pk, secao__ciclo__ano=ano)
    calc = Calculadora(b.secao.ciclo)
    m = A.montar_bloco(calc, b, revisao=True, user=request.user, pode_campos=F.pode_editar_texto(request.user, b.secao))
    return JsonResponse({"html": m.get("html", ""), "v": b.atualizado_em.isoformat(),
                         "problemas": m.get("problemas", [])})


@login_required
@require_POST
def inserir_texto(request, ano):
    """Novo trecho de texto (no editor de documento), depois de um bloco ou no fim da seção."""
    d = _json(request)
    secao = get_object_or_404(Secao.objects.select_related("ciclo"), ciclo__ano=ano, pk=d.get("secao") or 0)
    depois = Bloco.objects.filter(secao=secao, pk=d.get("depois") or 0).first()
    try:
        b = F.criar_bloco(request.user, secao, Bloco.TEXTO, depois)
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=403)
    calc = Calculadora(secao.ciclo)
    m = A.montar_bloco(calc, b, revisao=True, user=request.user)
    m.update({"sugestoes": [], "comentarios": [], "travado_por": None, "versao": b.atualizado_em.isoformat()})
    html = render_to_string("relatorio/_doc_bloco.html", {
        "d": m, "it": {"s": secao, "pode": True, "sugerir": F.pode_sugerir(request.user, secao)},
        "editor": True, "ciclo": secao.ciclo}, request=request)
    return JsonResponse({"ok": True, "id": b.pk, "html": html})


@login_required
@require_POST
def excluir_texto(request, ano, pk):
    b = get_object_or_404(Bloco.objects.select_related("secao__ciclo"), pk=pk, secao__ciclo__ano=ano)
    if b.tipo != Bloco.TEXTO:
        return JsonResponse({"ok": False, "erro": "Tabelas e gráficos se organizam na tela da seção."}, status=400)
    try:
        F.excluir_bloco(request.user, b)
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=403)
    return JsonResponse({"ok": True})


# --- Ler (somente leitura) -----------------------------------------------------------------
@login_required
def ler(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    calc = Calculadora(c)
    caps = estrutura(c, calc)
    seq = em_paginas(c, caps)
    n_pend = sum(len(d.get("problemas", [])) for cap in caps for x in [cap] + cap["secoes"] for d in x["blocos"])
    n_marcas = sum(x["marcas"] for cap in caps for x in [cap] + cap["secoes"])
    n_alt = sum(x["n_alt"] for cap in caps for x in [cap] + cap["secoes"])
    secoes = c.secoes.filter(pai__isnull=False)
    return render(request, "relatorio/ler.html", {
        "ciclo": c, "caps": caps, "seq": seq, "numeros_pendentes": n_pend, "n_marcas": n_marcas, "n_alt": n_alt,
        "n_secoes": secoes.count(), "n_aprovadas": secoes.filter(situacao=Secao.APROVADA).count(),
        "pode_exportar": P.e_master(request.user) or P.e_admin(request.user)})


# --- Gráficos ao vivo (tela de dados) ----------------------------------------------------------
def graficos_do_quadro(calc, q):
    """Gráficos do relatório feitos com este quadro, para a prévia ao lado da tabela. Entram também os que ainda
    não têm valores (com o aviso de quais colunas eles usam), para que a prévia apareça assim que a pessoa digitar."""
    out = []
    for b in Bloco.objects.filter(quadro=q, tipo=Bloco.GRAFICO).order_by("secao__ordem", "ordem"):
        m = A.montar_bloco(calc, b, largura=4.8)     # mais estreito: fica legível ao lado da tabela
        out.append({"id": b.pk, "titulo": b.titulo or q.titulo, "svg": m.get("grafico") or "",
                    "usa": colunas_do_grafico(calc, q, b), "avisos": m.get("avisos", [])})
    return out


def colunas_do_grafico(calc, q, b):
    """Em palavras, de quais colunas o gráfico tira os números (ex.: “Dotação atualizada”)."""
    cfg = b.config or {}
    cols = calc.colunas_de(q)
    escolhidas = cfg.get("colunas")
    if escolhidas:
        nomes = [c.rotulo for c in cols if c.chave in escolhidas]
    elif q.modo_colunas == Quadro.ANOS:
        nomes = [c.rotulo for c in cols]
        if len(nomes) > 3:
            nomes = [f"{nomes[0]} a {nomes[-1]}"]
    else:
        nomes = [c.rotulo for c in cols]
    if not nomes:
        return ""
    if len(nomes) == 1:
        return f"Este gráfico usa só a coluna “{nomes[0]}”."
    return "Este gráfico usa as colunas " + ", ".join(f"“{n}”" for n in nomes[:-1]) + f" e “{nomes[-1]}”."


@login_required
def quadro_graficos(request, ano, pk):
    q = get_object_or_404(Quadro, pk=pk, ciclo__ano=ano)
    calc = Calculadora(q.ciclo)
    return JsonResponse({"graficos": graficos_do_quadro(calc, calc.quadro_por_id[q.pk])})


# --- 2.12: preencher no próprio documento -----------------------------------------------------------
@login_required
@require_POST
def campo_salvar(request, ano):
    """Valor do ano de um número do texto (campo xxxxx)."""
    from html import unescape

    from . import campos as CT
    d = _json(request)
    b = get_object_or_404(Bloco.objects.select_related("secao__ciclo"), pk=d.get("bloco") or 0, secao__ciclo__ano=ano,
                          tipo=Bloco.TEXTO)
    try:
        c = F.preencher_campo(request.user, b, str(d.get("chave", "")), d.get("valor", ""))
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    orig = next((unescape(m.group(2)) for m in CT.CAMPO.finditer(b.conteudo) if m.group(1) == c.chave), "")
    return JsonResponse({"ok": True, "exibido": CT.exibir(orig, c.numero), "vazio": c.numero is None,
                         "faltam_secao": F.campos_vazios_da_secao(b.secao)})


@login_required
def quadro_gaveta(request, ano, pk):
    """Os dados de uma tabela ou gráfico, para preencher sem sair do documento (gaveta lateral)."""
    from . import consistencia as CS
    q0 = get_object_or_404(Quadro, pk=pk, ciclo__ano=ano)
    calc = Calculadora(q0.ciclo)
    q = calc.quadro_por_id[q0.pk]
    pend = CS.verificar(q.ciclo, calc, [q])
    b = A.montar_quadro(calc, q, request.user, pend)
    b["graficos"] = graficos_do_quadro(calc, q)
    b["meu"] = True
    html = render_to_string("relatorio/_quadro.html", {"b": b, "ciclo": q.ciclo, "gaveta": True,
                                                        "pode_estruturar": False}, request=request)
    return JsonResponse({"html": html, "titulo": q.titulo, "editavel": b.get("editavel", False)})


@login_required
@require_POST
def escrever_atualizar(request, ano):
    """Depois de preencher dados de um quadro: devolve de novo os blocos do documento que usam esse quadro
    (tabelas, gráficos, painéis e os textos que citam os números)."""
    import re as _re
    c = get_object_or_404(Ciclo, ano=ano)
    d = _json(request)
    if d.get("secoes"):
        return JsonResponse(_faltam(request.user, c, [str(x) for x in d["secoes"]]))
    chaves = {str(x) for x in d.get("quadros", []) if _re.fullmatch(r"[a-z0-9_]+", str(x))}
    if not chaves:
        return JsonResponse({"blocos": {}})
    calc = Calculadora(c)
    # quadros calculados a partir destes também mudam (ex.: grad_numeros.matriculados = ga_matriculados.graduacao)
    for q in calc.quadros.values():
        if any(_re.search(rf"\b{ch}\.", li.formula or "") for li in calc.linhas_de(q) for ch in chaves):
            chaves.add(q.chave)
    out = {}
    for b in Bloco.objects.filter(secao__ciclo=c).select_related("quadro", "secao").prefetch_related("campos"):
        if b.tipo == Bloco.TEXTO:
            if not any(f'data-ref="{ch}.' in (b.conteudo or "") for ch in chaves):
                continue
            pode = F.pode_editar_texto(request.user, b.secao)
            m = A.montar_bloco(calc, b, revisao=True, user=request.user, pode_campos=pode)
            out[b.pk] = {"tipo": "texto", "html": m["html"]}
            continue
        refs = {b.quadro.chave} if b.quadro_id else set()
        refs |= {(it.get("ref") or "").split(".")[0] for it in (b.config or {}).get("itens", [])}
        linha = (b.config or {}).get("linha")
        if isinstance(linha, str) and "." in linha:
            refs.add(linha.split(".")[0])
        if not refs & chaves:
            continue
        m = A.montar_bloco(calc, b, revisao=True, user=request.user, **A.tamanho_na_pagina(b))
        if b.tipo == Bloco.TABELA and b.quadro_id and b.quadro.tipo_valor == "texto":
            m["metas"] = A.metas_para_editar(calc, calc.quadro_por_id[b.quadro_id], request.user)
        if b.pagina_id:          # gráfico ou tabela numa página do RG: volta no mesmo lugar e do mesmo tamanho
            A.caixa_na_pagina(b, m)
            it = {"s": b.secao, "pode": F.pode_editar_texto(request.user, b.secao)}
            html = render_to_string("relatorio/_pg_objeto.html", {"d": m, "it": it, "editor": True, "ciclo": c},
                                    request=request)
        else:
            html = render_to_string("relatorio/_doc_bloco.html", {"d": m, "it": {"s": b.secao}, "editor": True,
                                                                  "ciclo": c}, request=request)
        out[b.pk] = {"tipo": b.tipo, "html": html}
    return JsonResponse({"blocos": out})


def _faltam(user, ciclo, secoes):
    """Quanto falta preencher em cada seção pedida e, no total, nas seções que a pessoa escreve."""
    calc = Calculadora(ciclo)
    pend = {}
    for p in consistencia.verificar(ciclo, calc):
        if p.severidade == "falta" and not A.so_texto(p.quadro):     # metas do PDI: contadas na própria tabela
            pend[p.quadro.secao_id] = pend.get(p.quadro.secao_id, 0) + 1
    out, total = {}, 0
    for s in ciclo.secoes.all():
        if not F.pode_editar_texto(user, s) and str(s.pk) not in secoes:
            continue
        n = pend.get(s.pk, 0) + F.campos_vazios_da_secao(s)
        if str(s.pk) in secoes:
            out[str(s.pk)] = n
        if F.pode_editar_texto(user, s):
            total += n
    return {"faltam": out, "total": total}
