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
    if request.method == "POST":
        faltando = {}
        try:
            caps, secs, avisos, faltando = M.adicionar_em_lote(c, request.POST.get("lista", ""))
        except M.Recusado as e:
            messages.error(request, str(e))
        else:
            if caps or secs:
                messages.success(request, f"{caps} capítulo(s) e {secs} seção(ões) criados.")
            for a in avisos:
                messages.warning(request, a)
            if not (caps or secs or avisos):
                messages.error(request, "A lista está vazia.")
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
    return render(request, "relatorio/secoes.html", {
        "ciclo": c, "arvore": M.arvore(c), "faltam": [x for x in pedidas if x.upper() not in existentes],
        "voltar": request.get_full_path()})


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
