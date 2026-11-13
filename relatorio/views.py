import json
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from contas import permissoes as P
from contas.models import Setor

from . import apresentacao as A
from . import consistencia, revisao
from . import fluxo as F
from . import formato
from . import permissoes as RP
from . import servicos as S
from .calculo import TOTAL, Calculadora
from .forms import (CicloForm, CicloNovoForm, ColunasFormSet, LinhasFormSet, QuadroForm, RegrasFormSet, SecaoForm,
                    gerar_chave)
from .models import Bloco, Ciclo, Coluna, Linha, Quadro, Secao, Valor


def _estruturar(request):
    if not RP.pode_estruturar(request.user):
        raise PermissionDenied("Só os administradores da plataforma alteram a estrutura do relatório.")


def ciclo_atual():
    """O relatório em trabalho: o ciclo mais recente (a plataforma é focada num relatório por vez)."""
    return Ciclo.objects.order_by("-ano").first()


# --- Ciclos ------------------------------------------------------------------
@login_required
def ciclos(request):
    return render(request, "relatorio/ciclos.html", {"ciclos": Ciclo.objects.all(),
                                                     "pode_estruturar": RP.pode_estruturar(request.user)})


@login_required
def ciclo_novo(request):
    _estruturar(request)
    ultimo = Ciclo.objects.order_by("-ano").first()
    form = CicloNovoForm(request.POST or None, initial={
        "ano": (ultimo.ano + 1) if ultimo else 2026, "origem": ultimo, "anos_serie": ultimo.anos_serie if ultimo else 5})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        titulo = d["titulo"] or f"Relatório de Gestão {d['ano']}"
        if d["origem"]:
            try:
                c = S.copiar_ciclo(d["origem"], d["ano"], titulo, d["anos_serie"])
            except S.Recusado as ex:
                form.add_error(None, str(ex))
                return render(request, "relatorio/ciclo_novo.html", {"form": form})
            messages.success(request, f"{titulo} criado a partir de {d['origem'].titulo}. Os anos anteriores "
                                      f"vieram preenchidos e travados. Revise a estrutura e abra a coleta.")
        else:
            c = Ciclo.objects.create(ano=d["ano"], titulo=titulo, anos_serie=d["anos_serie"])
            messages.success(request, f"{titulo} criado em branco. Comece criando os capítulos e as seções.")
        if d.get("prazo"):
            c.prazo = d["prazo"]
            c.save(update_fields=["prazo"])
        return redirect("ciclo", ano=c.ano)
    return render(request, "relatorio/ciclo_novo.html", {"form": form})


@login_required
def ciclo_editar(request, ano):
    _estruturar(request)
    c = get_object_or_404(Ciclo, ano=ano)
    form = CicloForm(request.POST or None, instance=c)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Ciclo atualizado.")
        return redirect("ciclo", ano=c.ano)
    return render(request, "relatorio/ciclo_editar.html", {"form": form, "ciclo": c})


@login_required
def ciclo(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    calc = Calculadora(c)
    pend = [p for p in consistencia.verificar(c, calc) if not A.so_texto(p.quadro)]   # só números aqui
    meus = set(P.setores_ativos(request.user).values_list("pk", flat=True))
    so_minhas = request.GET.get("minhas", "1" if meus and not P.e_master(request.user) else "0") == "1"
    # um quadro é "meu" quando o meu setor o preenche (o setor do quadro ou, se não tiver, o da seção)
    resp = {q.pk: {x.pk for x in q.setores_responsaveis()} for q in calc.quadros.values()}
    if so_minhas:
        pend = [p for p in pend if resp.get(p.quadro.pk, set()) & meus]
    # quadros que saem também em outra seção (tabela ou gráfico de lá): contam nas duas
    tambem_em = {}
    for sid, qid in Bloco.objects.filter(secao__ciclo=c, quadro__isnull=False).exclude(tipo=Bloco.TEXTO).values_list(
            "secao_id", "quadro_id"):
        q = calc.quadro_por_id.get(qid)
        if q is not None and q.secao_id != sid:
            tambem_em.setdefault(qid, set()).add(sid)
    pend_por_secao = {}
    for p in pend:
        for sid in {p.quadro.secao_id} | tambem_em.get(p.quadro.pk, set()):
            d = pend_por_secao.setdefault(sid, {"erros": 0, "avisos": 0, "faltam": 0})
            d[{"erro": "erros", "aviso": "avisos", "falta": "faltam"}[p.severidade]] += 1
    secoes = list(c.secoes.select_related("pai").prefetch_related("setores"))
    n_quadros = {}
    for q in calc.quadros.values():
        if not A.so_texto(q) and (not so_minhas or resp[q.pk] & meus):
            for sid in {q.secao_id} | tambem_em.get(q.pk, set()):
                n_quadros[sid] = n_quadros.get(sid, 0) + 1
    arvore = OrderedDict()
    for s in secoes:
        if s.pai_id is None:
            arvore.setdefault(s.pk, {"cap": s, "secoes": []})
    total_f = total_t = 0
    for s in secoes:
        qs_sec = [q for q in calc.quadros.values() if q.secao_id == s.pk and not A.so_texto(q)]
        meus_q = [q for q in qs_sec if resp[q.pk] & meus]
        minha = bool(meus_q) or (not qs_sec and bool(meus & {x.pk for x in s.setores.all()}))
        if so_minhas and meus_q:
            f = t = 0
            for q in meus_q:
                a, b = A.progresso_quadro(calc, q)
                f, t = f + a, t + b
        else:
            f, t = A.progresso_secao(calc, s, numeros=True)
        if not t and s.pai_id is not None:
            continue          # seção só de texto: fica em Escrever o relatório
        if not so_minhas or minha:
            total_f, total_t = total_f + f, total_t + t      # o total geral conta cada quadro uma vez só
        for qid, sids in tambem_em.items():                 # na linha da seção, entram os que saem nela também
            q = calc.quadro_por_id[qid]
            if s.pk in sids and not A.so_texto(q) and (not so_minhas or resp[q.pk] & meus):
                a, b = A.progresso_quadro(calc, q)
                f, t = f + a, t + b
                minha = minha or bool(resp[q.pk] & meus)
        item = {"s": s, "minha": minha, "pct": A.percentual(f, t), "tem_dados": t > 0, "n_quadros": n_quadros.get(s.pk, 0),
                "pend": pend_por_secao.get(s.pk, {"erros": 0, "avisos": 0, "faltam": 0})}
        if s.pai_id is None:
            arvore[s.pk]["item"] = item
        elif not so_minhas or minha:
            arvore.setdefault(s.pai_id, {"cap": s.pai, "secoes": []})["secoes"].append(item)
    for v in arvore.values():       # capítulo com números próprios (ex.: gráficos da abertura): vira a 1ª linha
        it = v.get("item")
        if it and it["tem_dados"] and (not so_minhas or it["minha"]):
            v["secoes"].insert(0, dict(it, abertura=True))
    if so_minhas:
        arvore = OrderedDict((k, v) for k, v in arvore.items() if v["secoes"] or v.get("item", {}).get("minha"))
    return render(request, "relatorio/ciclo.html", {
        "ciclo": c, "arvore": arvore.values(), "resumo": consistencia.resumo(pend), "so_minhas": so_minhas,
        "tem_setor": bool(meus), "pct_geral": A.percentual(total_f, total_t),
        "pode_estruturar": RP.pode_estruturar(request.user)})


# --- Seções e quadros --------------------------------------------------------------
@login_required
def secao(request, ano, chave):
    c = get_object_or_404(Ciclo, ano=ano)
    s = get_object_or_404(Secao.objects.select_related("pai"), ciclo=c, chave=chave)
    calc = Calculadora(c)
    todos_quadros = [q for q in calc.quadros.values() if q.secao_id == s.pk and not A.so_texto(q)]
    todos_quadros.sort(key=lambda q: (q.ordem, q.pk))
    # quadros de outra seção que alimentam uma tabela ou um gráfico DESTA seção (ex.: a Tabela 1 de Execução
    # orçamentária vem do quadro da abertura do capítulo): aparecem aqui também, para preencher sem procurar
    ids_aqui = {q.pk for q in todos_quadros}
    emprestados = []
    for qid in Bloco.objects.filter(secao=s, quadro__isnull=False).exclude(tipo=Bloco.TEXTO).values_list("quadro_id", flat=True):
        q = calc.quadro_por_id.get(qid)
        if q is not None and qid not in ids_aqui and not A.so_texto(q):
            ids_aqui.add(qid)
            emprestados.append(q)
    todos_quadros += emprestados
    # Cada setor vê, por padrão, só os quadros que ele preenche; os de outros setores ficam a um clique.
    meus = set(P.setores_ativos(request.user).values_list("pk", flat=True))
    de_quem = {q.pk: {x.pk for x in q.setores_responsaveis()} for q in todos_quadros}
    meus_quadros = [q for q in todos_quadros if de_quem[q.pk] & meus]
    ver_todos = request.GET.get("todos") == "1" or P.e_master(request.user) or not meus_quadros
    quadros = todos_quadros if ver_todos else meus_quadros
    outros = [q for q in todos_quadros if q not in meus_quadros]
    pend = consistencia.verificar(c, calc, quadros)
    corrigir = request.GET.get("corrigir", "")
    blocos = [A.montar_quadro(calc, q, request.user, [p for p in pend if p.quadro.pk == q.pk],
                              corrigir=(corrigir == q.chave)) for q in quadros]
    from .views_doc import graficos_do_quadro
    usos = A.usos_dos_quadros(c, calc)
    for b in blocos:
        b["graficos"] = graficos_do_quadro(calc, b["q"])
        b["usos"] = usos.get(b["q"].chave)
        b["meu"] = b["q"] in meus_quadros
        b["emprestado"] = b["q"].secao if b["q"] in emprestados else None
    resumo_meus = consistencia.resumo([p for p in pend if p.quadro in meus_quadros]) if meus_quadros else None
    primeiro_falta = next((b["q"].chave for b in blocos if b["meu"] and (b["faltam"] or b["erros"])), "")
    irmas = list(Secao.objects.filter(ciclo=c, pai=s.pai_id).order_by("ordem", "id")) if s.pai_id else []
    idx = next((i for i, x in enumerate(irmas) if x.pk == s.pk), None)
    from .views_texto import contexto_texto
    ctx_texto = contexto_texto(request, calc, s)
    aba = request.GET.get("aba") or ("dados" if blocos else "texto")
    from .fluxo import pendencias_da_secao
    r_envio = consistencia.resumo(pendencias_da_secao(s))
    envio_falta = (f"Faltam {r_envio['faltam']} número(s)" if r_envio["faltam"] else "") + \
        (" e " if r_envio["faltam"] and r_envio["erros"] else "") + \
        (f"{r_envio['erros']} correção(ões)" if r_envio["erros"] else "")
    n_fora = len(F.alteracoes_de_fora(s)) if "enviar" in F.acoes_possiveis(request.user, s) else 0
    if n_fora:
        envio_falta = (envio_falta + " e " if envio_falta else "") + \
            f"{n_fora} alteraç{'ões' if n_fora > 1 else 'ão'} sugerida{'s' if n_fora > 1 else ''} no texto para aceitar ou recusar"
    return render(request, "relatorio/secao.html", {
        "envio_falta": envio_falta,
        **ctx_texto, "aba": aba, "editar_bloco": request.GET.get("editar", ""),
        "ciclo": c, "secao": s, "blocos": blocos, "resumo": consistencia.resumo(pend),
        "outros": outros, "ver_todos": ver_todos, "tem_meus": bool(meus_quadros), "resumo_meus": resumo_meus,
        "primeiro_falta": primeiro_falta,
        "setores_outros": sorted({x.sigla for q in outros for x in q.setores_responsaveis()}),
        "tem_texto": s.blocos.filter(tipo="texto").exists(),
        "filhas": s.filhas.all() if s.e_capitulo else [],
        "anterior": irmas[idx - 1] if idx else None,
        "proxima": irmas[idx + 1] if idx is not None and idx + 1 < len(irmas) else None,
        "pode_estruturar": RP.pode_estruturar(request.user), "e_master": P.e_master(request.user)})


@login_required
def secao_form(request, ano, chave=None):
    _estruturar(request)
    c = get_object_or_404(Ciclo, ano=ano)
    s = get_object_or_404(Secao, ciclo=c, chave=chave) if chave else None
    inicial = {}
    if s is None and request.GET.get("pai"):
        inicial["pai"] = Secao.objects.filter(ciclo=c, chave=request.GET["pai"]).first()
        inicial["ordem"] = (Secao.objects.filter(ciclo=c, pai=inicial["pai"]).count() + 1) * 10
    elif s is None:
        inicial["ordem"] = (Secao.objects.filter(ciclo=c, pai__isnull=True).count() + 1) * 10
    form = SecaoForm(request.POST or None, instance=s, ciclo=c, initial=inicial)
    if request.method == "POST":
        if "excluir" in request.POST and s is not None:
            if s.quadros.exists() or s.filhas.exists():
                messages.error(request, "Só é possível excluir seções sem quadros e sem seções dentro.")
                return redirect("secao_editar", ano=ano, chave=s.chave)
            s.delete()
            messages.success(request, "Seção excluída.")
            return redirect("ciclo", ano=ano)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.ciclo = c
            obj.save()
            form.save_m2m()
            messages.success(request, "Seção salva.")
            return redirect("secao", ano=ano, chave=obj.chave)
    return render(request, "relatorio/secao_form.html", {"form": form, "ciclo": c, "secao": s})


@login_required
def quadro_form(request, ano, chave=None):
    _estruturar(request)
    c = get_object_or_404(Ciclo, ano=ano)
    q = get_object_or_404(Quadro, ciclo=c, chave=chave) if chave else None
    inicial = {}
    if q is None:
        sec = Secao.objects.filter(ciclo=c, chave=request.GET.get("secao")).first()
        inicial = {"secao": sec, "ordem": (sec.quadros.count() + 1) if sec else 1, "anos_exibidos": c.anos_serie}
    form = QuadroForm(request.POST or None, instance=q, ciclo=c, initial=inicial)
    instancia = q or Quadro(ciclo=c)
    linhas = LinhasFormSet(request.POST or None, instance=instancia, prefix="linhas")
    colunas = ColunasFormSet(request.POST or None, instance=instancia, prefix="colunas")
    regras = RegrasFormSet(request.POST or None, instance=instancia, prefix="regras")
    if request.method == "POST":
        if "excluir" in request.POST and q is not None:
            n = Valor.objects.filter(linha__quadro=q).count()
            q.delete()
            messages.success(request, f"Quadro excluído ({n} valor{'es' if n != 1 else ''} removido{'s' if n != 1 else ''};"
                                      f" ficam no histórico).")
            return redirect("ciclo", ano=ano)
        validos = form.is_valid() and linhas.is_valid() and regras.is_valid()
        modo = (q.modo_colunas if q else form.cleaned_data.get("modo_colunas") if form.is_valid() else None)
        if modo == Quadro.CATEGORIAS or (q and q.modo_colunas == Quadro.ANOS):
            validos = validos and colunas.is_valid()
        if validos:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.ciclo = c
                obj.save()
                linhas.instance = obj
                linhas.save()
                if obj.modo_colunas == Quadro.ANOS:
                    S.sincronizar_colunas_de_anos(obj)
                    if q is not None:      # só a marcação de travada vem do formulário
                        for f in colunas.forms:
                            if f.instance.pk and f.has_changed() and "travada" in f.changed_data:
                                Coluna.objects.filter(pk=f.instance.pk, quadro=obj).update(
                                    travada=f.cleaned_data.get("travada", False))
                else:
                    colunas.instance = obj
                    colunas.save()
                regras.instance = obj
                for f in regras.forms:
                    f.instance.ciclo = c
                regras.save()
            calc = Calculadora(c)
            obj = calc.quadros[obj.chave]
            erros = sorted({calc.celula(obj, li.chave, col).erro for li in calc.linhas_de(obj)
                            for col in calc.colunas_de(obj)} - {""})
            for e in erros:
                messages.warning(request, f"Atenção na fórmula: {e}")
            messages.success(request, f"Quadro “{obj.titulo}” salvo.")
            if "continuar" in request.POST:
                return redirect("quadro_editar", ano=ano, chave=obj.chave)
            return redirect(reverse("secao", args=[ano, obj.secao.chave]) + f"?aba=dados#quadro-{obj.chave}")
    outros = Quadro.objects.filter(ciclo=c).exclude(pk=getattr(q, "pk", None)).prefetch_related("linhas")
    return render(request, "relatorio/quadro_form.html", {
        "form": form, "linhas": linhas, "colunas": colunas, "regras": regras, "ciclo": c, "quadro": q,
        "outros": outros})


# --- Gravação de células (AJAX) ----------------------------------------------------
def _resposta_quadro(request, q):
    calc = Calculadora(q.ciclo)
    q = calc.quadros[q.chave]
    pend = consistencia.verificar(q.ciclo, calc, [q])
    bloco = A.montar_quadro(calc, q, request.user, pend, corrigir=True)
    celulas = {}
    for li in bloco["linhas"]:
        for cel in li["celulas"]:
            celulas[cel["id"]] = {"exibido": cel["exibido"], "severidade": cel.get("severidade", ""),
                                  "mensagens": cel.get("mensagens", []), "erro_formula": cel.get("erro_formula", ""),
                                  "pede_justificativa": cel.get("pede_justificativa", False),
                                  "auto": cel.get("auto"), "digitado": cel.get("digitado", False),
                                  "divergente": cel.get("divergente", False)}
    return {"celulas": celulas, "pendencias": [_pend_json(p) for p in pend],
            "erros": bloco["erros"], "avisos": bloco["avisos"], "faltam": bloco["faltam"],
            "preenchidas": bloco["preenchidas"], "aguardando": bloco.get("aguardando", 0),
            "total_celulas": bloco["total_celulas"]}


def _pend_json(p):
    d = {"severidade": p.severidade, "mensagem": p.mensagem, "detalhe": p.detalhe, "ancora": p.ancora}
    if p.acao:
        d["acao"] = dict(p.acao, linha=p.linha.pk, coluna=p.coluna.pk)
    return d


def _corpo(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


@login_required
@require_POST
def celula_salvar(request, ano):
    d = _corpo(request)
    try:
        linha = Linha.objects.select_related("quadro__ciclo", "quadro__secao", "quadro__setor").get(
            pk=int(d.get("linha")), quadro__ciclo__ano=ano)
        coluna = Coluna.objects.get(pk=int(d.get("coluna")), quadro=linha.quadro)
    except (Linha.DoesNotExist, Coluna.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "erro": "Célula não encontrada."}, status=404)
    try:
        v = S.salvar_valor(request.user, linha, coluna, d.get("valor", ""), d.get("anterior"),
                           d.get("justificativa", ""))
    except S.Conflito as ex:
        return JsonResponse({"ok": False, "conflito": True, "atual": ex.atual, "erro": str(ex)}, status=409)
    except S.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    q = linha.quadro
    edicao = formato.para_edicao(linha.tipo, v.numero if v else None, v.texto if v else "", q.casas_decimais)
    return JsonResponse({"ok": True, "edicao": edicao, **_resposta_quadro(request, q)})


@login_required
@require_POST
def celula_justificar(request, ano):
    d = _corpo(request)
    try:
        linha = Linha.objects.select_related("quadro__ciclo").get(pk=int(d.get("linha")), quadro__ciclo__ano=ano)
        coluna = Coluna.objects.get(pk=int(d.get("coluna")), quadro=linha.quadro)
        S.salvar_justificativa(request.user, linha, coluna, d.get("justificativa", ""))
    except (Linha.DoesNotExist, Coluna.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "erro": "Célula não encontrada."}, status=404)
    except S.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    return JsonResponse({"ok": True, **_resposta_quadro(request, linha.quadro)})


@login_required
@require_POST
def celula_divergencia(request, ano):
    """Fonte única: corrigir (vale o automático) ou ignorar (vale o digitado) uma divergência."""
    d = _corpo(request)
    try:
        linha = Linha.objects.select_related("quadro__ciclo", "quadro__secao", "quadro__setor").get(
            pk=int(d.get("linha")), quadro__ciclo__ano=ano)
        coluna = Coluna.objects.get(pk=int(d.get("coluna")), quadro=linha.quadro)
        S.resolver_divergencia(request.user, linha, coluna, d.get("acao"), Calculadora(linha.quadro.ciclo))
    except (Linha.DoesNotExist, Coluna.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "erro": "Célula não encontrada."}, status=404)
    except S.Recusado as ex:
        return JsonResponse({"ok": False, "erro": str(ex)}, status=400)
    v = Valor.objects.filter(linha=linha, coluna=coluna).first()
    edicao = formato.para_edicao(linha.tipo, v.numero if v else None, "", linha.quadro.casas_decimais)
    return JsonResponse({"ok": True, "edicao": edicao, "celula": f"{linha.pk}-{coluna.pk}",
                         **_resposta_quadro(request, linha.quadro)})


@login_required
def celula_historico(request, ano, linha, coluna):
    li = get_object_or_404(Linha.objects.select_related("quadro__ciclo"), pk=linha, quadro__ciclo__ano=ano)
    col = get_object_or_404(Coluna, pk=coluna, quadro=li.quadro)
    hist = Valor.history.filter(linha_id=li.pk, coluna_id=col.pk).select_related("history_user").order_by(
        "-history_date")[:50]
    itens = [{"quando": timezone.localtime(h.history_date).strftime("%d/%m/%Y %H:%M"),
              "quem": (h.history_user.get_full_name() or h.history_user.username) if h.history_user else "carga inicial",
              "valor": "(apagado)" if h.history_type == "-" else formato.exibir(li.tipo, h.numero, h.texto,
                                                                                li.quadro.casas_decimais),
              "motivo": h.history_change_reason or "", "justificativa": h.justificativa or ""} for h in hist]
    return JsonResponse({"titulo": f"{li.rotulo} — {col.rotulo}", "itens": itens})


# --- Pendências -----------------------------------------------------------------------
@login_required
def pendencias(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    calc = Calculadora(c)
    pend = consistencia.verificar(c, calc)
    setor_sel = request.GET.get("setor", "")
    sev = request.GET.get("severidade", "")
    tipo = request.GET.get("tipo", "")
    meus = set(P.setores_ativos(request.user).values_list("sigla", flat=True))
    padrao = "1" if meus and not P.e_master(request.user) else "0"
    minhas = request.GET.get("minhas", padrao) == "1"
    if minhas:
        pend = [p for p in pend if meus & {s.sigla for s in p.setores}]
    if setor_sel:
        pend = [p for p in pend if setor_sel in {s.sigla for s in p.setores}]
    geral = consistencia.resumo(pend)
    if sev:
        pend = [p for p in pend if p.severidade == sev]
    if tipo:
        pend = [p for p in pend if p.tipo == tipo]
    pend = agrupar_faltas(pend)
    textos = problemas_dos_textos(c, calc, setor_sel, request.user if minhas else None)
    n_atualizar = len(textos)
    geral["faltam"] += sum(t.get("n_campos", 0) for t in textos)          # os xxxxx do texto
    return render(request, "relatorio/pendencias.html", {
        "ciclo": c, "pendencias": pend, "resumo": consistencia.resumo(pend), "setores": Setor.objects.all(),
        "textos": textos, "tem_setor": bool(meus), "geral": geral, "n_atualizar": n_atualizar,
        "setor_sel": setor_sel, "sev_sel": sev, "tipo_sel": tipo, "minhas": minhas})


def agrupar_faltas(pend):
    """Uma linha por quadro para os campos em branco (“10 campos em branco: Limpeza, Restaurantes…”), em vez de
    uma linha por célula; erros e avisos continuam um por um."""
    from dataclasses import replace
    out, grupos = [], {}
    for p in pend:
        if p.severidade != "falta":
            out.append(p)
            continue
        g = grupos.get(p.quadro.pk)
        if g is None:
            grupos[p.quadro.pk] = g = {"primeira": p, "n": 0, "linhas": []}
            out.append(g)
        g["n"] += 1
        rot = getattr(p.linha, "rotulo", "") if p.linha is not None else ""
        if rot and rot not in g["linhas"]:
            g["linhas"].append(rot)
    final = []
    for x in out:
        if isinstance(x, dict):
            p, n = x["primeira"], x["n"]
            if n == 1:
                final.append(p)
                continue
            col = getattr(p.coluna, "rotulo", "") if p.coluna is not None else ""
            nomes = ", ".join(x["linhas"][:4]) + ("…" if len(x["linhas"]) > 4 else "")
            final.append(replace(p, mensagem=f"{n} campos em branco" + (f" na coluna {col}" if col else ""),
                                 detalhe=nomes))
        else:
            final.append(x)
    return final


def problemas_dos_textos(ciclo, calc, setor_sigla="", user=None):
    """Números vivos sem valor/inválidos e números digitados à mão que existem nos quadros."""
    from ia.assistente import numeros_digitados

    from .models import Bloco
    from . import nome_inst
    from .rascunho import contar_avisos
    from .texto import contar_marcas, renderizar
    meus = set(P.setores_ativos(user).values_list("sigla", flat=True)) if user else None
    out = []
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO).select_related("secao__pai").prefetch_related(
            "secao__setores", "campos").order_by("secao__ordem", "ordem"):
        siglas = {s.sigla for s in b.secao.setores.all()}
        if setor_sigla and setor_sigla not in siglas or (meus is not None and not (meus & siglas)):
            continue
        n_alt = len(revisao.itens(b.conteudo))
        if n_alt:
            out.append({"bloco": b, "severidade": "atualizar",
                        "mensagem": f"{n_alt} alteraç{'ões' if n_alt > 1 else 'ão'} sugerida{'s' if n_alt > 1 else ''} no texto "
                                    f"(controle de alterações) esperando alguém aceitar ou recusar."})
        n_marcas = contar_marcas(b.conteudo)
        if n_marcas:
            out.append({"bloco": b, "severidade": "atualizar",
                        "mensagem": f"{n_marcas} trecho{'s' if n_marcas > 1 else ''} marcado{'s' if n_marcas > 1 else ''} "
                                    f"com o marca-texto para atualizar."})
        n_nomes = nome_inst.contar(b.conteudo)
        if n_nomes:
            out.append({"bloco": b, "severidade": "atualizar",
                        "mensagem": f"{n_nomes} menç{'ões' if n_nomes > 1 else 'ão'} ao CEFET-MG em amarelo: clique em "
                                    f"cada uma e escolha se fica CEFET-MG (fato histórico) ou passa a UFCIMG."})
        n_avisos = contar_avisos(b.conteudo)
        if n_avisos:
            out.append({"bloco": b, "severidade": "atualizar",
                        "mensagem": f"{n_avisos} aviso{'s' if n_avisos > 1 else ''} de figura ou tabela do relatório "
                                    f"anterior para substituir e apagar."})
        from . import campos as CT
        valores = CT.valores_do_bloco(b)
        n_campos = sum(1 for ch in CT.chaves(revisao.base(b.conteudo)) if valores.get(ch) is None)
        if n_campos:
            out.append({"bloco": b, "severidade": "falta", "n_campos": n_campos,
                        "mensagem": f"{n_campos} número{'s' if n_campos > 1 else ''} do texto como xxxxx: clique em "
                                    f"cada um para preencher o valor de {ciclo.ano}."})
        _, problemas = renderizar(b.conteudo, calc)
        for pr in problemas:
            out.append({"bloco": b, "severidade": "falta" if "não preenchido" in pr["erro"] else "erro",
                        "mensagem": f"Número no texto: {pr['descricao']} — {pr['erro']}"})
        for d in numeros_digitados(b.conteudo, calc):
            if d["candidatos"]:
                out.append({"bloco": b, "severidade": "aviso",
                            "mensagem": f"“{d['texto']}” foi digitado à mão, mas existe nos dados "
                                        f"({d['candidatos'][0]['descricao']}). Transforme em número vivo para "
                                        f"não divergir se o dado mudar."})
    return out


@login_required
def ir_para_ciclo_atual(request):
    c = ciclo_atual()
    if c is None:
        if RP.pode_estruturar(request.user):
            return redirect("ciclo_novo")
        raise Http404("Nenhum ciclo do relatório foi criado ainda.")
    return redirect("ciclo", ano=c.ano)


@login_required
def atalho(request, destino):
    """Endereços curtos (/preencher/, /escrever/, /ler/) que levam ao relatório atual."""
    c = ciclo_atual()
    if c is None:
        return ir_para_ciclo_atual(request)
    url = reverse(destino, kwargs={"ano": c.ano})
    qs = request.META.get("QUERY_STRING", "")
    return redirect(f"{url}?{qs}" if qs else url)


# --- conferência das conexões ---------------------------------------------------------
@login_required
def conferencia_conexoes(request, ano):
    """Planilha com todas as ligações entre os números e o relatório, para conferir contra o RG publicado."""
    from django.http import HttpResponse

    from . import conferencia
    c = get_object_or_404(Ciclo, ano=ano)
    dados = conferencia.gerar(c, Calculadora(c))
    r = HttpResponse(dados, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = f'attachment; filename="SiRG-{ano}-conferencia-das-conexoes.xlsx"'
    return r


# --- Excel ---------------------------------------------------------------------------
@login_required
def excel_exportar(request, ano):
    from django.http import HttpResponse

    from . import planilhas
    c = get_object_or_404(Ciclo, ano=ano)
    calc = Calculadora(c)
    quadros = sorted(calc.quadros.values(), key=lambda q: ((q.secao.pai.ordem if q.secao.pai else 0),
                                                            q.secao.ordem, q.ordem, q.pk))
    nome = f"SiRG-{ano}"
    if request.GET.get("secao"):
        quadros = [q for q in quadros if q.secao.chave == request.GET["secao"]]
        nome += f"-{request.GET['secao']}"
    elif request.GET.get("quadro"):
        quadros = [q for q in quadros if q.chave == request.GET["quadro"]]
        nome += f"-{request.GET['quadro']}"
    elif request.GET.get("setor"):
        sig = request.GET["setor"]
        quadros = [q for q in quadros if sig in {s.sigla for s in q.setores_responsaveis()}]
        nome += f"-{sig}"
    if not quadros:
        messages.warning(request, "Nenhum quadro para exportar com esse filtro.")
        return redirect("ciclo", ano=ano)
    dados = planilhas.exportar(calc, quadros, request.user)
    r = HttpResponse(dados, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = f'attachment; filename="{nome}.xlsx"'
    return r


@login_required
def excel_importar(request, ano):
    from . import planilhas
    c = get_object_or_404(Ciclo, ano=ano)
    chave_sessao = f"importacao_{ano}"
    if request.method == "POST" and request.POST.get("acao") == "confirmar":
        alteracoes = request.session.pop(chave_sessao, None)
        if not alteracoes:
            messages.error(request, "A prévia expirou. Envie a planilha de novo.")
            return redirect("excel_importar", ano=ano)
        marcadas = set(request.POST.getlist("aplicar"))
        ok, falhas = 0, []
        linhas = {li.pk: li for li in Linha.objects.filter(quadro__ciclo=c).select_related(
            "quadro__ciclo", "quadro__secao", "quadro__setor")}
        colunas = {col.pk: col for col in Coluna.objects.filter(quadro__ciclo=c)}
        for a in alteracoes:
            if a["erro"] or f"{a['linha']}-{a['coluna']}" not in marcadas:
                continue
            try:
                S.salvar_valor(request.user, linhas[a["linha"]], colunas[a["coluna"]], a["entrada"],
                               justificativa="importado de planilha")
                ok += 1
            except (S.Recusado, S.Conflito, KeyError) as ex:
                falhas.append(f"{a['quadro']} › {a['rotulo']} ({a['coluna_rotulo']}): {ex}")
        messages.success(request, f"{ok} valor{'es' if ok != 1 else ''} gravado{'s' if ok != 1 else ''} a partir da planilha.")
        for f in falhas[:10]:
            messages.error(request, f)
        return redirect("ciclo", ano=ano)
    previa = None
    if request.method == "POST" and request.FILES.get("arquivo"):
        arq = request.FILES["arquivo"]
        if not arq.name.lower().endswith(".xlsx"):
            messages.error(request, "Envie um arquivo .xlsx (a planilha baixada da plataforma).")
        else:
            try:
                previa = planilhas.ler_alteracoes(arq, c, request.user)
            except planilhas.ErroPlanilha as ex:
                messages.error(request, str(ex))
            else:
                request.session[chave_sessao] = previa
                if not previa:
                    messages.info(request, "A planilha não tem nenhuma alteração em relação ao que já está gravado.")
    return render(request, "relatorio/importar.html", {
        "ciclo": c, "previa": previa, "validas": [a for a in previa or [] if not a["erro"]],
        "invalidas": [a for a in previa or [] if a["erro"]],
        "meus_setores": P.setores_ativos(request.user)})
