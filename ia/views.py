import json
import urllib.error
import urllib.request

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contas import permissoes as P
from relatorio.calculo import Calculadora
from relatorio.models import Bloco, Secao
from relatorio.texto import renderizar
from relatorio.views_texto import diff_palavras

from . import assistente as AS
from . import config, uso
from .models import UsoIA


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _pode_usar(user, secao):
    from relatorio import fluxo as F
    return F.pode_editar_texto(user, secao) or F.pode_sugerir(user, secao)


@login_required
@require_POST
def texto(request, ano):
    d = _json(request)
    secao = get_object_or_404(Secao.objects.select_related("ciclo", "pai"), ciclo__ano=ano, pk=d.get("secao") or 0)
    if not _pode_usar(request.user, secao):
        return JsonResponse({"ok": False, "erro": "Você não pode editar o texto desta seção."}, status=403)
    bloco = Bloco.objects.filter(secao=secao, pk=d.get("bloco") or 0).first()
    calc = Calculadora(secao.ciclo)
    html = d.get("html", "")
    acao = d.get("acao", "")
    if acao == "ligar":
        novo, ligados = AS.ligar_numeros(html, calc, d.get("escolhas") or {})
        restantes = [a for a in AS.numeros_digitados(novo, calc)]
        renderizado, _ = renderizar(novo, calc)
        return JsonResponse({"ok": True, "html": renderizado, "ligados": ligados,
                             "restantes": restantes, "diff": diff_palavras(html, novo, calc)})
    try:
        r = AS.executar(request.user, acao, html, calc, secao, d.get("instrucao", ""), bloco)
    except AS.ErroAssistente as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    if r.get("identidade"):
        return JsonResponse({"ok": True, "mensagem": r["mensagem"], "html": "", "problemas": []})
    if "problemas" in r:
        return JsonResponse({"ok": True, "problemas": r["problemas"], "uso": r["uso"],
                             "digitados": [a for a in AS.numeros_digitados(html, calc)]})
    novo = r["html"]
    if acao == "analisar":
        base = html if AS.texto_puro(html).strip() else ""
        novo_total = (base + novo) if base else novo
    else:
        novo_total = novo
    renderizado, problemas = renderizar(novo_total, calc)
    return JsonResponse({"ok": True, "html": renderizado, "diff": diff_palavras(html, novo_total, calc),
                         "avisos": r["avisos"], "uso": r["uso"], "tokens": r["tokens"],
                         "situacao": uso.situacao(request.user)})


@login_required
@require_POST
def aplicado(request, pk):
    UsoIA.objects.filter(pk=pk, usuario=request.user).update(aplicado=True)
    return JsonResponse({"ok": True})


@login_required
def meu_uso(request):
    return JsonResponse(uso.situacao(request.user))


@login_required
def painel_uso(request):
    if not config.pode_ver_uso(request.user):
        raise PermissionDenied("Só administradores veem o uso do Assistente.")
    hoje = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    mes = hoje.replace(day=1)
    por_usuario = (UsoIA.objects.filter(criado_em__gte=mes).values("usuario__username", "usuario__first_name",
                                                                   "usuario__last_name")
                   .annotate(chamadas=Count("id"), entrada=Sum("tokens_entrada"), saida=Sum("tokens_saida"),
                             aplicadas=Count("id", filter=Q(aplicado=True)), falhas=Count("id", filter=Q(sucesso=False)))
                   .order_by("-entrada"))
    por_acao = UsoIA.objects.filter(criado_em__gte=mes).values("acao").annotate(n=Count("id")).order_by("-n")
    resumo = config.resumo_publico().get("assistente", {})
    teste = None
    if request.method == "POST" and request.POST.get("testar"):
        teste = testar_conexao()
    return render(request, "ia/uso.html", {
        "por_usuario": por_usuario, "por_acao": [(AS.ACOES.get(a["acao"], (a["acao"],))[0], a["n"]) for a in por_acao],
        "hoje": UsoIA.objects.filter(criado_em__gte=hoje).count(), "resumo": resumo, "teste": teste,
        "ultimos": UsoIA.objects.select_related("usuario")[:30], "acoes": AS.ACOES})


def testar_conexao():
    """Lista os modelos disponíveis para a chave configurada (sem gastar tokens)."""
    try:
        p = config.perfil("assistente")
    except config.ErroConfigIA as ex:
        return {"ok": False, "erro": str(ex)}
    if p.provedor == "simulado":
        return {"ok": True, "modelos": [], "mensagem": "Provedor simulado: nenhuma IA real é chamada."}
    if not p.chave:
        return {"ok": False, "erro": "A chave da API não está no arquivo .env (GEMINI_API_KEY=...)."}
    req = urllib.request.Request(f"{p.base_url}/models", headers={"Authorization": f"Bearer {p.chave}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        return {"ok": False, "erro": f"O serviço recusou a conexão (HTTP {ex.code}). Confira a chave."}
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        return {"ok": False, "erro": f"Sem conexão com o serviço de IA ({ex}). Confira a internet/proxy."}
    modelos = sorted(m.get("id", "").replace("models/", "") for m in dados.get("data", []))
    return {"ok": True, "modelos": modelos, "configurado": p.modelo,
            "encontrado": p.modelo in modelos or f"models/{p.modelo}" in modelos}
