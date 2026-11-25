"""Tela do editor visual de blocos: a página do relatório com os blocos desenhados por cima, para o administrador
criar, mover, redimensionar, juntar e apagar blocos e preencher os atributos de cada um."""
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import editor_blocos as E
from . import grade as G
from . import textos_pdf as TP
from .models import Ciclo, Pagina
from .views_atributos import pode_definir_atributos


def _acesso(request, ano, n):
    c = get_object_or_404(Ciclo, ano=ano)
    if not pode_definir_atributos(request.user):
        raise PermissionDenied("Só o administrador e o Editor-chefe editam os blocos da página.")
    return c, get_object_or_404(Pagina, ciclo=c, numero=n)


def _fundo(pg):
    from . import fundo as FU
    return {"fundo_url": pg.fundo_url, "ajustes": pg.ajustes_fundo or [],
            "pdf_original": FU.pdf_original(pg) is not None}


@login_required
def editor_pagina(request, ano, n):
    c, pg = _acesso(request, ano, n)
    numeros = list(c.paginas.values_list("numero", flat=True))
    i = numeros.index(pg.numero)
    dados = {"pagina": pg.numero, "largura": pg.largura, "altura": pg.altura,
             "blocos": E.blocos_da_pagina(pg), "opcoes": E.opcoes(c), "secao_da_pagina": pg.secao_id,
             "ano": c.ano, "somente_leitura": c.situacao == Ciclo.ENCERRADO, "guias": G.guias(pg),
             "pdf": TP.caixas_da_pagina(pg), **_fundo(pg)}
    from contas import permissoes as P
    from django.urls import reverse
    if P.cuida_das_cores(request.user):
        dados["url_grade"] = reverse("padrao_design") + f"?ciclo={c.ano}#grade"
    return render(request, "relatorio/editor_pagina.html", {
        "ciclo": c, "pode_grade": P.cuida_das_cores(request.user), "pg": pg, "numeros": numeros, "dados": dados,
        "anterior": numeros[i - 1] if i > 0 else None, "proxima": numeros[i + 1] if i + 1 < len(numeros) else None})


@login_required
@require_POST
def editor_acao(request, ano, n, acao):
    c, pg = _acesso(request, ano, n)
    if acao not in E.ACOES:
        return JsonResponse({"ok": False, "erro": "Ação desconhecida."}, status=404)
    try:
        d = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "erro": "Pedido inválido."}, status=400)
    try:
        selecionar, mensagem = E.ACOES[acao](request.user, pg, d)
    except E.Recusado as e:
        texto = str(e)
        if texto.startswith("CONFIRMAR: "):
            return JsonResponse({"ok": False, "confirmar": texto[len("CONFIRMAR: "):]}, status=409)
        return JsonResponse({"ok": False, "erro": texto}, status=400)
    return JsonResponse({"ok": True, "mensagem": mensagem, "selecionar": selecionar,
                         "blocos": E.blocos_da_pagina(pg), "guias": G.guias(pg), "pdf": TP.caixas_da_pagina(pg),
                         **_fundo(pg)})


@login_required
def editor_inicio(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    if not pode_definir_atributos(request.user):
        raise PermissionDenied("Só o administrador e o Editor-chefe editam os blocos da página.")
    primeira = c.paginas.order_by("numero").first()
    if primeira is None:
        from django.contrib import messages
        messages.info(request, "O relatório ainda não tem páginas. Importe o PDF do relatório primeiro.")
        return redirect("importar_pdf", ano=ano)
    return redirect("editor_pagina", ano=ano, n=primeira.numero)
