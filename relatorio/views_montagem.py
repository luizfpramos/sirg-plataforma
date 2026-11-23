"""Telas da montagem do relatório do ano (2.18): passos, seções, ciclo de trabalho e exclusão na homologação."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
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
        try:
            caps, secs, avisos = M.adicionar_em_lote(c, request.POST.get("lista", ""))
        except M.Recusado as e:
            messages.error(request, str(e))
        else:
            if caps or secs:
                messages.success(request, f"{caps} capítulo(s) e {secs} seção(ões) criados.")
            for a in avisos:
                messages.warning(request, a)
            if not (caps or secs or avisos):
                messages.error(request, "A lista está vazia.")
        return redirect("secoes_lista", ano=ano)
    return render(request, "relatorio/secoes.html", {"ciclo": c, "arvore": M.arvore(c)})


@login_required
@require_POST
def secao_mover(request, ano, chave, direcao):
    _exigir_admin(request.user)
    s = get_object_or_404(Secao, ciclo__ano=ano, chave=chave)
    if direcao not in ("subir", "descer"):
        raise PermissionDenied
    M.mover_secao(s, direcao)
    return redirect("secoes_lista", ano=ano)
