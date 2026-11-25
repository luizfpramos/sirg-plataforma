"""Telas da montagem do relatório do ano (2.18): passos, seções, ciclo de trabalho e exclusão na homologação."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import montagem as M
from . import permissoes as RP
from .models import Ciclo, Secao


def _exigir_admin(user):
    if not RP.pode_estruturar(user):
        raise PermissionDenied("Só o administrador monta o relatório.")


@login_required
def montagem_inicio(request):
    """Atalho do menu: a montagem do ciclo de trabalho (ou a criação do primeiro)."""
    from .views import ciclo_atual
    _exigir_admin(request.user)
    c = ciclo_atual()
    return redirect("montagem", ano=c.ano) if c else redirect("ciclo_novo")


@login_required
def montagem(request, ano):
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    from .views import ciclo_atual
    return render(request, "relatorio/montagem.html", {
        "ciclo": c, "passos": M.passos(c), "ciclos": Ciclo.objects.order_by("-ano"),
        "de_trabalho": ciclo_atual(), "pode_excluir": M.pode_excluir_ciclo()})


@login_required
@require_POST
def ciclo_de_trabalho(request, ano):
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    M.tornar_de_trabalho(c)
    messages.success(request, f"{c.titulo} passou a ser o relatório de trabalho: é o que o menu abre para todos.")
    return redirect("montagem", ano=ano)


@login_required
def ciclo_excluir(request, ano):
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    if not M.pode_excluir_ciclo():
        raise PermissionDenied("Excluir um relatório só é permitido no ambiente de homologação.")
    if request.method == "POST":
        try:
            r = M.excluir_ciclo(c, request.POST.get("confirmacao"), request.user, request)
        except M.Recusado as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Relatório excluído: {r['secoes']} seções, {r['paginas']} páginas e "
                                      f"{r['blocos']} blocos. Usuários e setores continuam como estavam.")
            return redirect("ciclos")
    return render(request, "relatorio/ciclo_excluir.html", {"ciclo": c, "resumo": M.resumo_do_ciclo(c)})


@login_required
def secoes_lista(request, ano):
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    previa, lista = None, ""
    if request.method == "POST":
        lista = request.POST.get("lista", "")
        if request.POST.get("acao") == "conferir":            # 2.23: mostra o que vai acontecer, sem gravar
            previa = M.ler_lista(c, lista)
            if not any(it["acao"] for it in previa):
                messages.error(request, "A lista está vazia.")
                previa = None
        else:
            faltando = {}
            try:
                r = M.adicionar_em_lote(c, lista)
            except M.Recusado as e:
                messages.error(request, f"Nada foi gravado: {e}")
                previa = M.ler_lista(c, lista)
            else:
                faltando = r["faltando"]
                partes = []
                if r["capitulos"]:
                    partes.append(f"{r['capitulos']} {'capítulo criado' if r['capitulos'] == 1 else 'capítulos criados'}")
                if r["secoes"]:
                    partes.append(f"{r['secoes']} {'seção criada' if r['secoes'] == 1 else 'seções criadas'}")
                if r["atualizadas"]:
                    partes.append(f"{r['atualizadas']} {'item atualizado' if r['atualizadas'] == 1 else 'itens atualizados'}")
                if partes:
                    messages.success(request, ", ".join(partes) + ".")
                if r["paginas"] and r["paginas"]["paginas"]:
                    f = r["paginas"]
                    messages.info(request, f"{f['paginas']} {'página mudou' if f['paginas'] == 1 else 'páginas mudaram'} "
                                           f"de seção, conforme a lista.")
                for a in r["avisos"]:
                    messages.warning(request, a)
                if not (partes or r["avisos"]):
                    messages.info(request, "Nada mudou: os itens da lista já estavam assim.")
                if faltando:      # ao criar o setor pelo botão, ele já entra nas seções que o pediram (contas.views.setor_novo)
                    pend = request.session.get("setores_pedidos", {})
                    for sg, pks in faltando.items():
                        pend[sg] = sorted(set(pend.get(sg, [])) | set(pks))
                    request.session["setores_pedidos"] = pend
                url = reverse("secoes_lista", args=[ano])
                return redirect(url + ("?faltam=" + ",".join(faltando) if faltando else ""))
    from contas.models import Setor
    pedidas = [x for x in (request.GET.get("faltam") or "").split(",") if x][:20]
    existentes = {x.upper() for x in Setor.objects.values_list("sigla", flat=True)}
    tem_paginas = c.paginas.exists()
    inicios = M.inicios_das_secoes(c) if tem_paginas else [(s, s.pagina_inicio) for s in M._em_ordem(c)]
    if previa and tem_paginas:          # mostra de que página para qual a seção muda ao gravar
        atuais = {x.pk: n for x, n in inicios}
        for it in previa:
            if it["existente"] is not None and it["pagina"] and atuais.get(it["existente"].pk) != it["pagina"]:
                it["pagina_atual"] = atuais.get(it["existente"].pk)
                it["muda_pagina"] = True
    return render(request, "relatorio/secoes.html", {
        "ciclo": c, "arvore": M.arvore(c), "faltam": [x for x in pedidas if x.upper() not in existentes],
        "voltar": request.get_full_path(), "inicios": inicios, "tem_paginas": tem_paginas,
        "previa": previa, "lista": lista,
        "previa_n": {k: sum(1 for it in (previa or []) if it["acao"] == k) for k in ("criar", "atualizar", "igual")}})


def _gravar_previstas(ciclo, novos):
    for s in ciclo.secoes.filter(pk__in=list(novos)):
        if s.pagina_inicio != novos[s.pk]:
            s.pagina_inicio = novos[s.pk]
            s.save(update_fields=["pagina_inicio"])


@login_required
@require_POST
def secoes_paginas(request, ano):
    """Corrige a página em que cada seção começa, depois de aplicar o PDF (2.21)."""
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    novos = {}
    for s in c.secoes.all():
        campo = f"inicio_{s.pk}"
        if campo not in request.POST:
            continue
        v = request.POST.get(campo, "").strip()
        if not v:
            novos[s.pk] = None
        elif v.isdigit():
            novos[s.pk] = int(v)
        else:
            messages.error(request, f"Página inválida em “{s.titulo}”: {v}.")
            return redirect(reverse("secoes_lista", args=[ano]) + "#paginas")
    if not c.paginas.exists():           # 2.23: antes do PDF, é a página prevista (a importação usa na conferência)
        _gravar_previstas(c, novos)
        messages.success(request, "Páginas previstas salvas. A importação do PDF vai usá-las na conferência.")
        return redirect(reverse("secoes_lista", args=[ano]) + "#paginas")
    try:
        f = M.mudar_inicios(c, novos)
    except M.Recusado as e:
        messages.error(request, str(e))
    else:
        _gravar_previstas(c, novos)          # a página prevista acompanha a correção
        if f["paginas"]:
            messages.success(request, f"{f['paginas']} {'página mudou' if f['paginas'] == 1 else 'páginas mudaram'} de seção, com {f['blocos']} {'bloco' if f['blocos'] == 1 else 'blocos'}.")
        else:
            messages.info(request, "Nenhuma página mudou de seção.")
    return redirect(reverse("secoes_lista", args=[ano]) + "#paginas")


@login_required
@require_POST
def secao_mover(request, ano, chave, direcao):
    _exigir_admin(request.user)
    s = get_object_or_404(Secao, ciclo__ano=ano, chave=chave)
    if direcao not in ("subir", "descer"):
        raise PermissionDenied
    M.mover_secao(s, direcao)
    return redirect("secoes_lista", ano=ano)


@login_required
def quadros_lista(request, ano):
    from contas.models import Setor

    from .models import Quadro
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    if request.method == "POST":
        p = request.POST
        secao = Secao.objects.filter(ciclo=c, pk=p.get("secao") or 0).first()
        setor = Setor.objects.filter(pk=p.get("setor") or 0).first()
        try:
            q = M.criar_quadro_simples(c, titulo=p.get("titulo"), secao=secao, linhas=p.get("linhas"), setor=setor,
                                       tipo=p.get("tipo"), modo=p.get("modo"), anos=p.get("anos") or None,
                                       colunas=p.get("colunas"), total=bool(p.get("total")),
                                       descricao=p.get("descricao", "").strip())
        except (M.Recusado, ValueError) as e:
            messages.error(request, str(e) or "Dados inválidos.")
            return render(request, "relatorio/quadros.html", _ctx_quadros(c, p), status=400)
        messages.success(request, f"Quadro “{q.titulo}” criado. Já pode ser escolhido num bloco de gráfico ou tabela."
                         + (" Os anos anteriores estão travados para os setores: a DGDI preenche o histórico em “números” › "
                            "Corrigir anos publicados (o primeiro preenchimento não pede justificativa)."
                            if q.modo_colunas == Quadro.ANOS and q.anos_exibidos > 1 else ""))
        return redirect("quadros_lista", ano=ano)
    return render(request, "relatorio/quadros.html", _ctx_quadros(c))


def _ctx_quadros(c, dados=None):
    from contas.models import Setor

    from .models import Quadro
    grupos = []
    for cap, filhas in M.arvore(c):
        for s in [cap] + filhas:
            qs = list(s.quadros.select_related("setor").prefetch_related("linhas", "colunas", "blocos"))
            if qs:
                grupos.append((s, qs))
    return {"ciclo": c, "grupos": grupos, "arvore": M.arvore(c), "setores": Setor.objects.filter(ativo=True),
            "tipos": Quadro.TIPOS, "dados": dados or {}}


@login_required
def pdf_anterior(request, ano):
    """O PDF do relatório anterior enviado pela tela (quem está logado consulta)."""
    c = get_object_or_404(Ciclo, ano=ano)
    arq = M.caminho_pdf_anterior(c)
    if not arq.is_file():
        raise Http404("O PDF do relatório anterior não foi enviado.")
    r = FileResponse(open(arq, "rb"), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="relatorio-anterior-{c.ano}.pdf"'
    return r


@login_required
def pdf_anterior_enviar(request, ano):
    _exigir_admin(request.user)
    c = get_object_or_404(Ciclo, ano=ano)
    if request.method == "POST":
        try:
            M.receber_pdf_anterior(c, request.FILES.get("pdf"))
        except M.Recusado as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "PDF do relatório anterior enviado. Os setores abrem pelo botão no alto do "
                                      "relatório.")
            return redirect("montagem", ano=ano)
    return render(request, "relatorio/pdf_anterior.html", {"ciclo": c, "url": M.url_pdf_anterior(c),
                                                           "enviado": M.caminho_pdf_anterior(c).is_file()})
