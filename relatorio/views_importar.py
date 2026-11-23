"""Telas do importador de PDF: enviar o PDF diagramado, acompanhar a leitura, conferir as páginas e aplicar."""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import importador as I
from . import permissoes as RP
from . import reimportador as RI
from .html_seguro import limpar
from .models import Ciclo, ImportacaoPDF
from .paginas import _caixa_css, url_do_fundo


def _exigir_admin(user):
    if not RP.pode_estruturar(user):
        raise PermissionDenied("Só o administrador importa o PDF do relatório.")


@login_required
def importar_pdf(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    _exigir_admin(request.user)
    if request.method == "POST":
        try:
            imp = I.receber(c, request.FILES.get("pdf"), request.user)
        except I.Recusado as e:
            messages.error(request, str(e))
            return redirect("importar_pdf", ano=ano)
        I.iniciar(imp)
        return redirect("importacao_ver", ano=ano, pk=imp.pk)
    return render(request, "relatorio/importar_pdf.html", {
        "ciclo": c, "importacoes": c.importacoes.select_related("enviado_por")[:20],
        "tem_paginas": c.paginas.exists(), "maximo_mb": I.TAMANHO_MAXIMO // (1024 * 1024)})


@login_required
def importacao_ver(request, ano, pk):
    imp = get_object_or_404(ImportacaoPDF, pk=pk, ciclo__ano=ano)
    _exigir_admin(request.user)
    reimportar = imp.ciclo.paginas.exists()
    ctx = {"ciclo": imp.ciclo, "imp": imp, "reimportar": reimportar,
           "motivo": RI.motivo_para_nao_reimportar(imp) if reimportar else I.motivo_para_nao_aplicar(imp)}
    if reimportar and not ctx["motivo"]:
        ctx["plano"] = RI.plano(imp)
    if not reimportar and imp.situacao == ImportacaoPDF.PRONTA:
        ctx["conferencia"] = I.conferencia(imp)
        ctx["exibicoes"] = Ciclo.EXIBICOES_VAZIO
    if imp.situacao in (ImportacaoPDF.PRONTA, ImportacaoPDF.APLICADA):
        paginas = I.paginas_lidas(imp)
        numeros = [p["n"] for p in paginas]
        try:
            n = int(request.GET.get("p", numeros[0] if numeros else 1))
        except ValueError:
            n = numeros[0] if numeros else 1
        p = next((x for x in paginas if x["n"] == n), paginas[0] if paginas else None)
        if p:
            e_fixo = I.textos_fixos(paginas)
            ctx.update({
                "pagina": p, "numeros": numeros, "fundo_url": url_do_fundo(I.url_fundo(imp, p["n"])),
                "caixas": [{"css": _caixa_css(c), "html": limpar(c["html"]), "fixo": e_fixo(c, p["h"]),
                            "quebra": c["quebra"]} for c in p["caixas"]],
                "anterior": numeros[numeros.index(p["n"]) - 1] if numeros.index(p["n"]) > 0 else None,
                "proxima": numeros[numeros.index(p["n"]) + 1] if numeros.index(p["n"]) + 1 < len(numeros) else None,
            })
    return render(request, "relatorio/importacao_ver.html", ctx)


@login_required
@require_POST
def importacao_aplicar(request, ano, pk):
    imp = get_object_or_404(ImportacaoPDF, pk=pk, ciclo__ano=ano)
    _exigir_admin(request.user)
    c = imp.ciclo
    inicios, fixas = None, set()
    if "conferido" in request.POST:
        inicios = {}
        for s in c.secoes.all():
            v = (request.POST.get(f"inicio_{s.pk}") or "").strip()
            try:
                inicios[s.pk] = int(v) if v else None
            except ValueError:
                messages.error(request, f"Página inválida na seção “{s.titulo}”: {v}.")
                return redirect("importacao_ver", ano=ano, pk=pk)
            if request.POST.get(f"fixo_{s.pk}"):
                fixas.add(s.pk)
        modo = request.POST.get("exibicao_vazio")
        with transaction.atomic():
            for s in c.secoes.all():
                if s.conteudo_fixo != (s.pk in fixas):
                    s.conteudo_fixo = s.pk in fixas
                    s.save(update_fields=["conteudo_fixo"])
            if modo in dict(Ciclo.EXIBICOES_VAZIO) and modo != c.exibicao_vazio:
                c.exibicao_vazio = modo
                c.save(update_fields=["exibicao_vazio"])
        # guarda as escolhas, para não se perderem se a aplicação for recusada
        ImportacaoPDF.objects.filter(pk=imp.pk).update(
            resumo=dict(imp.resumo or {}, inicios={str(k): v for k, v in inicios.items()}))
        imp.refresh_from_db()
        if "salvar" in request.POST:
            messages.success(request, "Escolhas guardadas. Confira e aplique quando quiser.")
            return redirect("importacao_ver", ano=ano, pk=pk)
    try:
        feito = I.aplicar(imp, request.user, inicios)
    except I.Recusado as e:
        messages.error(request, str(e))
        return redirect("importacao_ver", ano=ano, pk=pk)
    if c.automatico:
        messages.success(request, f"{feito['paginas']} páginas e {feito['caixas']} trechos de texto criados no ciclo.")
    else:
        messages.success(request, f"{feito['paginas']} páginas e {feito['caixas']} blocos criados: {feito['vazios']} "
                                  f"vazios, para os setores escreverem, e {feito['fixos']} com texto fixo (títulos e "
                                  f"seções de conteúdo fixo).")
    return redirect("montagem", ano=ano)


@login_required
@require_POST
def importacao_reimportar(request, ano, pk):
    imp = get_object_or_404(ImportacaoPDF, pk=pk, ciclo__ano=ano)
    _exigir_admin(request.user)
    try:
        f = RI.reimportar(imp, request.user)
    except I.Recusado as e:
        messages.error(request, str(e))
        return redirect("importacao_ver", ano=ano, pk=pk)
    messages.success(request, f"Fundo trocado em todas as páginas do PDF. {f['pareados']} trechos reposicionados, "
                              f"{f['novos']} novos, {f['sem_par']} sem caixa no PDF novo. Nenhum texto foi alterado.")
    return redirect("importacao_ver", ano=ano, pk=pk)


@login_required
@require_POST
def importacao_ler_de_novo(request, ano, pk):
    imp = get_object_or_404(ImportacaoPDF, pk=pk, ciclo__ano=ano)
    _exigir_admin(request.user)
    if imp.situacao == ImportacaoPDF.ERRO or imp.interrompida:
        I.iniciar(imp)
    return redirect("importacao_ver", ano=ano, pk=pk)


NOME_FUNDO = re.compile(r"^p\d{3,4}\.jpg$")


@login_required
def importacao_arquivo(request, pk, nome):
    """Imagem de fundo de uma página importada (quem está logado vê o relatório, então vê o fundo)."""
    if not NOME_FUNDO.match(nome):
        raise Http404()
    imp = get_object_or_404(ImportacaoPDF, pk=pk)
    arq = imp.pasta / nome
    if not arq.is_file():
        raise Http404("Imagem não encontrada.")
    r = FileResponse(open(arq, "rb"), content_type="image/jpeg")
    r["Cache-Control"] = "private, max-age=604800"
    return r
