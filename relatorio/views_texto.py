"""Telas e ações do texto do relatório: blocos, editor, sugestões, comentários e fluxo da seção."""
import difflib
import json
import re
from html import escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from contas import permissoes as P

from . import apresentacao as A
from . import consistencia
from . import fluxo as F
from . import graficos
from .calculo import Calculadora
from .html_seguro import texto_puro
from .models import Bloco, Ciclo, Comentario, Quadro, Secao, Sugestao
from .texto import opcoes_de_numeros, renderizar


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def voltar(request, padrao):
    """Para onde voltar depois de um formulário (aceita só endereços desta plataforma)."""
    from django.utils.http import url_has_allowed_host_and_scheme
    alvo = request.POST.get("voltar") or request.GET.get("voltar") or ""
    if alvo and url_has_allowed_host_and_scheme(alvo, allowed_hosts={request.get_host()},
                                                 require_https=request.is_secure()):
        return redirect(alvo)
    return padrao


def _bloco(ano, pk):
    return get_object_or_404(Bloco.objects.select_related("secao__ciclo", "quadro", "editando_por"),
                             pk=pk, secao__ciclo__ano=ano)


def diff_palavras(antes_html, depois_html, calc=None):
    """Diferença palavra a palavra (HTML com <del> e <ins>) entre dois textos.
    Com `calc`, os números vivos são comparados pelo valor atual (e não pelo que estava gravado)."""
    if calc is not None:
        antes_html = renderizar(antes_html, calc, marcar=False)[0]
        depois_html = renderizar(depois_html, calc, marcar=False)[0]
    a = re.findall(r"\S+|\n", texto_puro(antes_html))
    b = re.findall(r"\S+|\n", texto_puro(depois_html))
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(" ".join(escape(x) for x in a[i1:i2]))
        if op in ("delete", "replace"):
            out.append("<del>" + " ".join(escape(x) for x in a[i1:i2]) + "</del>")
        if op in ("insert", "replace"):
            out.append("<ins>" + " ".join(escape(x) for x in b[j1:j2]) + "</ins>")
    return " ".join(out).replace(" \n ", "<br>").replace("\n", "<br>")


def contexto_texto(request, calc, secao):
    """Blocos montados + permissões, para a aba Texto da seção."""
    user = request.user
    blocos = list(secao.blocos.select_related("quadro", "editando_por", "atualizado_por").order_by("ordem", "id"))
    sugestoes = {}
    for s in Sugestao.objects.filter(bloco__secao=secao, situacao=Sugestao.PENDENTE).select_related("autor"):
        s.diff = diff_palavras(s.original, s.proposto, calc)
        sugestoes.setdefault(s.bloco_id, []).append(s)
    comentarios = {}
    for c in Comentario.objects.filter(secao=secao, resolvido=False, pai__isnull=True).select_related("autor"):
        comentarios.setdefault(c.bloco_id, []).append(c)
    montados = []
    for b in blocos:
        d = A.montar_bloco(calc, b, revisao=True)
        d["sugestoes"] = sugestoes.get(b.pk, [])
        d["comentarios"] = comentarios.get(b.pk, [])
        d["travado_por"] = b.editando_por if (F.trava_ativa(b) and b.editando_por_id != user.pk) else None
        montados.append(d)
    return {
        "blocos_texto": montados, "pode_texto": F.pode_editar_texto(user, secao),
        "pode_sugerir": F.pode_sugerir(user, secao), "pode_responder": F.pode_responder_sugestao(user, secao),
        "motivo_texto": F.motivo_texto_bloqueado(user, secao), "comentarios_secao": comentarios.get(None, []),
        "acoes": F.acoes_possiveis(user, secao), "movimentos": secao.movimentos.select_related("por")[:8],
        "tipos_bloco": Bloco.TIPOS, "quadros_secao": [q for q in calc.quadros.values() if q.secao_id == secao.pk],
    }


# --- blocos --------------------------------------------------------------------
@login_required
@require_POST
def bloco_novo(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    secao = get_object_or_404(Secao, ciclo=c, pk=request.POST.get("secao"))
    depois = Bloco.objects.filter(secao=secao, pk=request.POST.get("depois") or 0).first()
    quadro = Quadro.objects.filter(ciclo=c, pk=request.POST.get("quadro") or 0).first()
    try:
        b = F.criar_bloco(request.user, secao, request.POST.get("tipo", Bloco.TEXTO), depois, quadro)
    except F.Recusado as ex:
        messages.error(request, str(ex))
        return redirect("secao", ano=ano, chave=secao.chave)
    if b.tipo == Bloco.TEXTO:
        return redirect(reverse("secao", args=[ano, secao.chave]) + f"?editar={b.pk}#bloco-{b.pk}")
    return redirect("bloco_configurar", ano=ano, pk=b.pk)


@login_required
@require_POST
def bloco_travar(request, ano, pk):
    b = _bloco(ano, pk)
    if request.POST.get("liberar") or _json(request).get("liberar"):
        F.destravar(request.user, b)
        return JsonResponse({"ok": True})
    modo = _json(request).get("modo", "editar")
    if modo == "sugerir":
        if not F.pode_sugerir(request.user, b.secao):
            return JsonResponse({"ok": False, "erro": "Só o Master pode sugerir."}, status=403)
        calc = Calculadora(b.secao.ciclo)
        html, _ = renderizar(b.conteudo, calc)
        return JsonResponse({"ok": True, "html": html, "versao": b.atualizado_em.isoformat()})
    if not F.pode_editar_texto(request.user, b.secao):
        return JsonResponse({"ok": False, "erro": F.motivo_texto_bloqueado(request.user, b.secao)}, status=403)
    ok, quem = F.travar(request.user, b)
    if not ok:
        return JsonResponse({"ok": False, "erro": f"{quem.get_full_name() or quem.username} está editando este "
                                                  f"trecho agora. Tente daqui a pouco."}, status=409)
    b.refresh_from_db()
    calc = Calculadora(b.secao.ciclo)
    html, _ = _render_editor(b, calc, request.user)
    return JsonResponse({"ok": True, "html": html, "titulo": b.titulo, "versao": b.atualizado_em.isoformat()})


def _render_editor(b, calc, user):
    """HTML do trecho para o editor: números e campos “xxxxx” com os valores do ano."""
    from . import campos as CT
    return renderizar(b.conteudo, calc, campos=CT.valores_do_bloco(b), user=user,
                      campos_editaveis=F.pode_editar_texto(user, b.secao))


@login_required
@require_POST
def bloco_texto(request, ano, pk):
    b = _bloco(ano, pk)
    d = _json(request)
    try:
        if d.get("sugestao"):
            F.sugerir(request.user, b, d.get("html", ""), d.get("comentario", ""))
            return JsonResponse({"ok": True, "recarregar": True, "mensagem": "Sugestão enviada ao setor."})
        b = F.salvar_texto(request.user, b, d.get("html", ""), d.get("titulo"), d.get("versao"))
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    if d.get("liberar"):
        F.destravar(request.user, b)
    calc = Calculadora(b.secao.ciclo)
    html, problemas = _render_editor(b, calc, request.user)
    return JsonResponse({"ok": True, "html": html, "versao": b.atualizado_em.isoformat(), "problemas": problemas,
                         "palavras": len(texto_puro(b.conteudo).split())})


@login_required
@require_POST
def bloco_mover(request, ano, pk, direcao):
    b = _bloco(ano, pk)
    try:
        if direcao == "excluir":
            F.excluir_bloco(request.user, b)
            messages.success(request, "Bloco excluído (continua no histórico).")
        else:
            F.mover_bloco(request.user, b, direcao)
    except F.Recusado as ex:
        messages.error(request, str(ex))
    return redirect(reverse("secao", args=[ano, b.secao.chave]) + (f"#bloco-{b.pk}" if direcao != "excluir" else ""))


@login_required
def bloco_configurar(request, ano, pk):
    b = _bloco(ano, pk)
    if not F.pode_editar_texto(request.user, b.secao):
        raise PermissionDenied(F.motivo_texto_bloqueado(request.user, b.secao))
    calc = Calculadora(b.secao.ciclo)
    if request.method == "POST":
        quadro = calc.quadro_por_id.get(int(request.POST.get("quadro") or 0))
        config = dict(b.config or {})
        if b.tipo == Bloco.DESTAQUES:
            itens = []
            for i in range(8):
                ref = request.POST.get(f"ref_{i}", "").strip()
                if ref:
                    ref, _, col = ref.partition("|")
                    itens.append({"ref": ref, "col": col, "rotulo": request.POST.get(f"rotulo_{i}", "").strip()[:120],
                                  "legenda": request.POST.get(f"legenda_{i}", "").strip()[:200]})
            config = {"itens": itens}
            quadro = None
        elif quadro is not None and quadro.pk != b.quadro_id:
            config = {"tipo": config.get("tipo", "barras")} if b.tipo == Bloco.GRAFICO else {}
        else:
            config["linhas"] = request.POST.getlist("linhas")
            config["colunas"] = request.POST.getlist("colunas")
            if b.tipo == Bloco.GRAFICO:
                config["tipo"] = request.POST.get("tipo_grafico", "barras")
                config["total"] = bool(request.POST.get("total"))
                config["rotulos"] = bool(request.POST.get("rotulos"))
                config["inverter"] = bool(request.POST.get("inverter"))
                for k in ("linha", "linha_rotulo", "barras_rotulo"):
                    config[k] = request.POST.get(k, "").strip()[:120]
                config["recentes_primeiro"] = bool(request.POST.get("recentes_primeiro"))
            else:
                config["sem_total"] = not request.POST.get("total")
        try:
            F.salvar_config(request.user, b, request.POST.get("titulo", ""), quadro, config)
        except F.Recusado as ex:
            messages.error(request, str(ex))
        if "concluir" in request.POST:
            return redirect(reverse("secao", args=[ano, b.secao.chave]) + f"#bloco-{b.pk}")
        return redirect("bloco_configurar", ano=ano, pk=b.pk)
    b.refresh_from_db()
    q = calc.quadro_por_id.get(b.quadro_id) if b.quadro_id else None
    previa = A.montar_bloco(calc, b)
    quadros = sorted(calc.quadros.values(), key=lambda x: (x.secao_id != b.secao_id, x.secao.ordem, x.ordem))
    return render(request, "relatorio/bloco_configurar.html", {
        "ciclo": b.secao.ciclo, "b": b, "quadro": q, "quadros": quadros, "previa": previa,
        "linhas": calc.linhas_de(q) if q else [], "colunas": calc.colunas_de(q) if q else [],
        "tipos_grafico": graficos.TIPOS, "outras_linhas": _outras_linhas(calc, q) if b.tipo == Bloco.GRAFICO else [], "numeros": opcoes_de_numeros(calc) if b.tipo == Bloco.DESTAQUES else [],
        "itens": (b.config.get("itens", []) + [{}] * 8)[:8] if b.tipo == Bloco.DESTAQUES else []})


def _outras_linhas(calc, q):
    """Linhas numéricas de outros quadros, para a linha sobre as barras."""
    if q is None:
        return []
    minhas = {li.chave for li in calc.linhas_de(q)}
    out = []
    for o in sorted(calc.quadros.values(), key=lambda x: (x.secao_id != q.secao_id, x.secao.ordem, x.ordem)):
        if o.pk == q.pk:
            continue
        linhas = [li for li in calc.linhas_de(o) if li.tipo not in ("texto", "sim_nao")]
        if linhas:
            out.append({"quadro": o, "linhas": linhas, "mesmas": len(minhas & {li.chave for li in linhas}) >= 2})
    return out


@login_required
def bloco_historico(request, ano, pk):
    b = _bloco(ano, pk)
    versoes = list(b.history.select_related("history_user").order_by("-history_date")[:40])
    calc = Calculadora(b.secao.ciclo)
    itens = []
    from . import revisao
    for i, v in enumerate(versoes):
        # compara os textos com as alterações sugeridas aplicadas (o que cada versão propunha)
        anterior = revisao.aplicar(versoes[i + 1].conteudo) if i + 1 < len(versoes) else ""
        itens.append({"id": v.history_id, "quando": timezone.localtime(v.history_date).strftime("%d/%m/%Y %H:%M"),
                      "quem": (v.history_user.get_full_name() or v.history_user.username) if v.history_user else "sistema",
                      "motivo": v.history_change_reason or "", "diff": diff_palavras(anterior, revisao.aplicar(v.conteudo), calc),
                      "palavras": len(texto_puro(v.conteudo).split())})
    return JsonResponse({"itens": itens, "pode_restaurar": F.pode_editar_texto(request.user, b.secao)})


@login_required
@require_POST
def bloco_restaurar(request, ano, pk, hid):
    b = _bloco(ano, pk)
    v = get_object_or_404(b.history.model, history_id=hid, id=b.pk)
    try:
        F.salvar_texto(request.user, b, v.conteudo)
        F.destravar(request.user, b)
    except F.Recusado as ex:
        messages.error(request, str(ex))
    else:
        messages.success(request, f"Versão de {timezone.localtime(v.history_date):%d/%m/%Y %H:%M} restaurada.")
    return voltar(request, redirect(reverse("secao", args=[ano, b.secao.chave]) + f"#bloco-{b.pk}"))


# --- sugestões e comentários ------------------------------------------------------------
@login_required
@require_POST
def sugestao_responder(request, ano, pk, acao):
    s = get_object_or_404(Sugestao.objects.select_related("bloco__secao__ciclo"), pk=pk, bloco__secao__ciclo__ano=ano)
    try:
        if acao == "retirar":
            F.retirar_sugestao(request.user, s)
            messages.success(request, "Sugestão retirada.")
        else:
            F.responder_sugestao(request.user, s, acao == "aceitar", request.POST.get("resposta", ""))
            messages.success(request, "Sugestão aceita: o texto foi atualizado." if acao == "aceitar"
                             else "Sugestão recusada.")
    except F.Recusado as ex:
        messages.error(request, str(ex))
    return voltar(request, redirect(reverse("secao", args=[ano, s.bloco.secao.chave]) + f"#bloco-{s.bloco_id}"))


@login_required
@require_POST
def comentario_novo(request, ano, chave):
    secao = get_object_or_404(Secao, ciclo__ano=ano, chave=chave)
    bloco = Bloco.objects.filter(secao=secao, pk=request.POST.get("bloco") or 0).first()
    try:
        F.comentar(request.user, secao, request.POST.get("texto", ""), bloco)
    except F.Recusado as ex:
        messages.error(request, str(ex))
    return voltar(request, redirect(reverse("secao", args=[ano, chave]) + (f"#bloco-{bloco.pk}" if bloco else "#comentarios")))


@login_required
@require_POST
def comentario_resolver(request, ano, pk):
    c = get_object_or_404(Comentario.objects.select_related("secao__ciclo"), pk=pk, secao__ciclo__ano=ano)
    try:
        F.resolver_comentario(request.user, c)
    except F.Recusado as ex:
        messages.error(request, str(ex))
    return voltar(request, redirect(reverse("secao", args=[ano, c.secao.chave]) + (f"#bloco-{c.bloco_id}" if c.bloco_id else "")))


# --- fluxo da seção ------------------------------------------------------------------------
@login_required
@require_POST
def secao_acao(request, ano, chave):
    secao = get_object_or_404(Secao.objects.select_related("ciclo"), ciclo__ano=ano, chave=chave)
    acao = request.POST.get("acao", "")
    try:
        F.acao_secao(request.user, secao, acao, request.POST.get("comentario", ""))
    except F.Recusado as ex:
        messages.error(request, str(ex))
    else:
        messages.success(request, {"enviar": "Seção enviada ao Master.", "aprovar": "Seção aprovada.",
                                   "devolver": "Seção devolvida ao setor.", "reabrir": "Seção reaberta."}.get(acao, "Ok."))
    return voltar(request, redirect("secao", ano=ano, chave=chave))


# --- números e documento -------------------------------------------------------------------------
@login_required
def numeros(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    return JsonResponse({"grupos": opcoes_de_numeros(Calculadora(c))})


# --- exportação ----------------------------------------------------------------------------
@login_required
def exportar(request, ano):
    from django.http import HttpResponse

    from contas.models import Instituicao

    from . import exportar_docx as X
    c = get_object_or_404(Ciclo, ano=ano)
    formato_saida = request.GET.get("formato")
    inst = Instituicao.atual()
    if formato_saida == "docx":
        dados = X.gerar_docx(c, inst)
        r = HttpResponse(dados, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        r["Content-Disposition"] = f'attachment; filename="Relatorio-de-Gestao-{ano}.docx"'
        return r
    if formato_saida == "pacote":
        dados = X.gerar_pacote(c, inst, request.user)
        r = HttpResponse(dados, content_type="application/zip")
        r["Content-Disposition"] = f'attachment; filename="RG{ano}-pacote-diagramacao.zip"'
        return r
    calc = Calculadora(c)
    pend = consistencia.resumo(consistencia.verificar(c, calc))
    secoes = c.secoes.filter(pai__isnull=False)
    n_aprovadas = secoes.filter(situacao=Secao.APROVADA).count()
    from . import revisao
    n_alt = sum(len(revisao.itens(b.conteudo)) for b in Bloco.objects.filter(secao__ciclo=c, tipo=Bloco.TEXTO,
                                                                             conteudo__regex=r"<(ins|del) "))
    return render(request, "relatorio/exportar.html", {
        "ciclo": c, "resumo": pend, "n_secoes": secoes.count(), "n_aprovadas": n_aprovadas, "n_alt": n_alt,
        "n_graficos": Bloco.objects.filter(secao__ciclo=c, tipo=Bloco.GRAFICO).count(),
        "n_tabelas": Bloco.objects.filter(secao__ciclo=c, tipo=Bloco.TABELA).count()})


# --- Imagens no texto ---------------------------------------------------------------------------
FORMATOS_IMAGEM = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "GIF": ("image/gif", "gif"),
                   "WEBP": ("image/webp", "webp")}
TAMANHO_MAX_IMAGEM = 10 * 1024 * 1024


@login_required
@require_POST
def imagem_enviar(request, ano):
    """Recebe uma imagem para o texto (botão Imagem, colar ou arrastar). Devolve o endereço dela."""
    import os

    from django.core.files.base import ContentFile
    from PIL import Image, UnidentifiedImageError

    from .models import Imagem
    c = get_object_or_404(Ciclo, ano=ano)
    secao = None
    if not P.e_master(request.user):
        return JsonResponse({"ok": False, "erro": "Imagens novas são incluídas pelo Master."}, status=403)
    if request.POST.get("secao"):
        secao = Secao.objects.filter(ciclo=c, pk=request.POST.get("secao")).first()
    if secao is not None:
        if not F.pode_editar_texto(request.user, secao):
            return JsonResponse({"ok": False, "erro": F.motivo_texto_bloqueado(request.user, secao)}, status=403)
    elif not (P.e_master(request.user) or P.setores_ativos(request.user).exists()):
        return JsonResponse({"ok": False, "erro": "Você não pode enviar imagens."}, status=403)
    arq = request.FILES.get("arquivo")
    if arq is None:
        return JsonResponse({"ok": False, "erro": "Nenhuma imagem recebida."}, status=400)
    if arq.size > TAMANHO_MAX_IMAGEM:
        return JsonResponse({"ok": False, "erro": "A imagem tem mais de 10 MB. Diminua o tamanho e tente de novo."},
                            status=400)
    dados = arq.read()
    try:
        import io
        with Image.open(io.BytesIO(dados)) as im:
            im.verify()
        with Image.open(io.BytesIO(dados)) as im:
            formato, (larg, alt) = im.format, im.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return JsonResponse({"ok": False, "erro": "O arquivo não é uma imagem válida (use PNG, JPG, GIF ou WEBP)."},
                            status=400)
    if formato not in FORMATOS_IMAGEM:
        return JsonResponse({"ok": False, "erro": "Use uma imagem PNG, JPG, GIF ou WEBP."}, status=400)
    tipo, ext = FORMATOS_IMAGEM[formato]
    nome = os.path.splitext(os.path.basename(arq.name or ""))[0][:150] or "imagem"
    img = Imagem(ciclo=c, secao=secao, nome=nome, largura=larg, altura=alt, tipo=tipo, enviada_por=request.user)
    img.arquivo.save(f"{c.ano}-{timezone.now():%Y%m%d%H%M%S}.{ext}", ContentFile(dados), save=False)
    img.save()
    return JsonResponse({"ok": True, "url": img.url, "nome": "" if nome.lower() in ("image", "imagem") else nome})


@login_required
def imagem_ver(request, ano, pk):
    from django.http import FileResponse, Http404

    from .models import Imagem
    img = get_object_or_404(Imagem, pk=pk)      # o endereço não muda quando o texto passa para o ano seguinte
    try:
        r = FileResponse(img.arquivo.open("rb"), content_type=img.tipo)
    except FileNotFoundError:
        raise Http404("Imagem não encontrada.")
    r["Cache-Control"] = "private, max-age=86400"
    return r


# --- controle de alterações e comentários por trecho (painel de revisão do editor) -----------------
def _nome(u):
    return (u.get_full_name() or u.username) if u else "—"


def _comentario_json(c, user, respostas=()):
    return {"id": c.pk, "secao": c.secao_id, "secao_chave": c.secao.chave, "secao_titulo": c.secao.titulo,
            "bloco": c.bloco_id, "trecho": c.trecho, "antes": c.antes, "texto": c.texto,
            "autor": _nome(c.autor), "autor_id": c.autor_id, "meu": c.autor_id == user.pk,
            "quando": timezone.localtime(c.criado_em).strftime("%d/%m/%Y %H:%M"), "iso": c.criado_em.isoformat(),
            "resolvido": c.resolvido, "resolvido_por": _nome(c.resolvido_por) if c.resolvido else "",
            "pode_resolver": F.pode_resolver_comentario(user, c),
            "respostas": [{"id": r.pk, "texto": r.texto, "autor": _nome(r.autor), "meu": r.autor_id == user.pk,
                           "quando": timezone.localtime(r.criado_em).strftime("%d/%m/%Y %H:%M")} for r in respostas]}


@login_required
def revisao_comentarios(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    todos = list(Comentario.objects.filter(secao__ciclo=c).select_related("autor", "resolvido_por", "secao")
                 .order_by("criado_em", "id"))
    respostas = {}
    for x in todos:
        if x.pai_id:
            respostas.setdefault(x.pai_id, []).append(x)
    out = [_comentario_json(x, request.user, respostas.get(x.pk, [])) for x in todos if not x.pai_id]
    return JsonResponse({"comentarios": out})


@login_required
@require_POST
def revisao_comentar(request, ano):
    d = _json(request)
    secao = get_object_or_404(Secao.objects.select_related("ciclo"), ciclo__ano=ano, pk=d.get("secao") or 0)
    if not F.pode_comentar(request.user, secao):
        return JsonResponse({"ok": False, "erro": "Você não pode comentar neste relatório."}, status=403)
    bloco = Bloco.objects.filter(secao=secao, pk=d.get("bloco") or 0).first()
    pai = Comentario.objects.filter(secao=secao, pk=d.get("pai") or 0).select_related("pai", "bloco").first()
    try:
        novo = F.comentar(request.user, secao, d.get("texto", ""), bloco, d.get("trecho", ""), d.get("antes", ""), pai)
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    return JsonResponse({"ok": True, "id": novo.pk})


@login_required
@require_POST
def revisao_comentario_acao(request, ano, pk, acao):
    c = get_object_or_404(Comentario.objects.select_related("secao__ciclo", "pai"), pk=pk, secao__ciclo__ano=ano)
    try:
        if acao == "excluir":
            F.excluir_comentario(request.user, c)
        elif acao in ("resolver", "reabrir"):
            F.resolver_comentario(request.user, c, reabrir=acao == "reabrir")
        else:
            return JsonResponse({"ok": False, "erro": "Ação desconhecida."}, status=400)
    except F.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def revisao_resolver(request, ano):
    """Aceita ou recusa sugestões do texto: de um trecho (bloco), escolhidas por id, ou de uma seção inteira."""
    d = _json(request)
    aceitar = bool(d.get("aceitar"))
    ids = d.get("ids")
    ids = [str(x) for x in ids] if isinstance(ids, list) else None
    if d.get("bloco"):
        blocos = [_bloco(ano, d["bloco"])]
    else:
        secao = get_object_or_404(Secao.objects.select_related("ciclo"), ciclo__ano=ano, pk=d.get("secao") or 0)
        blocos = list(secao.blocos.filter(tipo=Bloco.TEXTO).select_related("secao__ciclo").order_by("ordem", "id"))
    calc = None
    out, erros, total = {}, [], 0
    for b in blocos:
        try:
            b, n = F.resolver_alteracoes(request.user, b, ids, aceitar)
        except F.Recusado as ex:
            erros.append(str(ex))
            continue
        if n:
            total += n
            calc = calc or Calculadora(b.secao.ciclo)
            out[b.pk] = {"html": _render_editor(b, calc, request.user)[0], "versao": b.atualizado_em.isoformat()}
    if erros and not total:
        return JsonResponse({"ok": False, "erro": erros[0]}, status=400)
    return JsonResponse({"ok": True, "n": total, "blocos": out, "avisos": erros})


@login_required
def pdi_planilha(request, ano):
    """A planilha de acompanhamento das metas do PDI, no mesmo formato da DGDI, com o que as unidades preencheram."""
    from io import BytesIO
    from pathlib import Path

    import openpyxl
    from django.http import HttpResponse

    from .models import Quadro, Valor
    c = get_object_or_404(Ciclo, ano=ano)
    q = get_object_or_404(Quadro, ciclo=c, chave="pdi_metas")
    modelo = Path(__file__).resolve().parent / "dados_iniciais" / "pdi_metas_2026_modelo.xlsx"
    wb = openpyxl.load_workbook(modelo)
    ws = wb["Dados"]
    ws["A1"] = f"RELATÓRIO DE GESTÃO {c.ano}: ACOMPANHAMENTO DAS METAS"
    valores = {}
    for v in Valor.objects.filter(linha__quadro=q).select_related("linha", "coluna"):
        valores[(v.linha.ordem, v.coluna.chave)] = v.texto
    col = {"situacao": 7, "justificativa": 8, "evidencia": 9}
    for linha in range(3, ws.max_row + 1):
        n = str(ws.cell(linha, 1).value or "").strip()
        if not n.isdigit():
            continue
        for ch, k in col.items():
            ws.cell(linha, k).value = valores.get((int(n), ch)) or None
    buf = BytesIO()
    wb.save(buf)
    r = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = f'attachment; filename="metas-pdi-{c.ano}.xlsx"'
    return r
