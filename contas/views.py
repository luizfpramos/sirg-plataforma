import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from . import permissoes as P
from . import servicos as S
from .forms import InstituicaoForm, LoginForm, SetorForm, UsuarioForm
from .models import EventoAuditoria, Instituicao, Perfil, Setor, VinculoSetor

User = get_user_model()


# --- Acesso -----------------------------------------------------------------
class Entrar(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        resp = super().form_valid(form)
        S.sucesso_de_login(form.get_user(), request=self.request)
        return resp


class TrocarSenha(auth_views.PasswordChangeView):
    template_name = "registration/password_change_form.html"

    def get_success_url(self):
        return reverse("painel")

    def get_form_class(self):
        # no primeiro acesso a pessoa acabou de entrar com a senha provisória: não pede de novo
        if P.perfil(self.request.user).troca_senha:
            from django.contrib.auth.forms import SetPasswordForm
            return SetPasswordForm
        return super().get_form_class()

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["obrigatoria"] = P.perfil(self.request.user).troca_senha
        return ctx

    def form_valid(self, form):
        resp = super().form_valid(form)
        p = P.perfil(self.request.user)
        p.troca_senha = False
        p.save(update_fields=["troca_senha", "atualizado_em"])
        S.registrar("senha_trocada", self.request.user, self.request.user, request=self.request)
        messages.success(self.request, "Senha alterada com sucesso.")
        return resp


def identidade(request, qual):
    """Logotipo e assinatura da unidade (públicos: aparecem também na tela de login)."""
    inst = Instituicao.atual()
    arq = {"logo": inst.logo, "faixa": inst.faixa_unidade}.get(qual)
    if arq is None:
        raise Http404
    if arq:
        try:
            tipo = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
            r = FileResponse(arq.open("rb"), content_type=tipo)
            r["Cache-Control"] = "max-age=300"
            r["X-Content-Type-Options"] = "nosniff"
            return r
        except FileNotFoundError:
            pass
    padrao = {"logo": "ufcimg-marca.png", "faixa": "dgdi.png"}[qual]
    return FileResponse(open(settings.BASE_DIR / "static" / "img" / padrao, "rb"), content_type="image/png")


def erro_403(request, exception=None):
    if getattr(request, "user", None) and request.user.is_authenticated:
        S.registrar("acesso_negado", request.user, descricao=request.path[:200], request=request)
    return render(request, "403.html", {"mensagem": str(exception) if exception else ""}, status=403)


def erro_404(request, exception=None):
    return render(request, "404.html", status=404)


def _tem_vinculo_ativo():
    return Exists(VinculoSetor.objects.filter(usuario=OuterRef("pk"), fim__isnull=True))


# --- Painel e conta ----------------------------------------------------------
@login_required
def painel(request):
    ctx = {"papeis": P.papeis(request.user)}
    ctx.update(_resumo_relatorio(request.user))
    if P.e_admin(request.user):
        ctx["n_usuarios"] = User.objects.filter(is_active=True).count()
        ctx["n_setores"] = Setor.objects.filter(ativo=True).count()
        ctx["n_sem_setor"] = User.objects.filter(is_active=True).filter(~_tem_vinculo_ativo()).count()
        ctx["n_pendentes"] = Perfil.objects.filter(usuario__is_active=True, troca_senha=True).count()
        ctx["eventos"] = EventoAuditoria.objects.select_related("ator", "usuario_alvo", "setor")[:8]
    return render(request, "contas/painel.html", ctx)


def _resumo_relatorio(user):
    """Relatório atual e o trabalho do usuário nele (para a tela inicial)."""
    from relatorio import apresentacao as A
    from relatorio import consistencia
    from relatorio import fluxo as F
    from relatorio.calculo import Calculadora
    from relatorio.html_seguro import texto_puro
    from relatorio.models import Bloco, Secao
    from relatorio.views import ciclo_atual
    c = ciclo_atual()
    if c is None:
        return {}
    calc = Calculadora(c)
    pend = consistencia.verificar(c, calc)
    meus = set(P.setores_ativos(user).values_list("pk", flat=True))
    from relatorio.texto import contar_marcas
    escrito, marcas, com_texto, revisado = set(), {}, set(), set()
    for b in Bloco.objects.filter(secao__ciclo=c, tipo=Bloco.TEXTO).only("secao_id", "conteudo", "config",
                                                                         "atualizado_por_id"):
        com_texto.add(b.secao_id)
        marcas[b.secao_id] = marcas.get(b.secao_id, 0) + contar_marcas(b.conteudo)
        if texto_puro(b.conteudo).strip():
            escrito.add(b.secao_id)
            if b.atualizado_por_id:
                revisado.add(b.secao_id)
    # "texto revisado": alguém já trabalhou no texto deste ano e não ficou trecho marcado para atualizar
    a_revisar = {k for k in escrito if k not in revisado}
    escrito = {k for k in escrito if k in revisado and not marcas.get(k)}
    metas = {}
    for q in calc.quadros.values():
        if A.so_texto(q):
            f, t = A.progresso_quadro(calc, q)
            m = metas.setdefault(q.secao_id, [0, 0])
            m[0] += f
            m[1] += t
    minhas, aguardando = [], []
    f_tot = t_tot = 0
    geral = {"f": 0, "t": 0, "secoes": 0, "escritas": 0, "enviadas": 0, "aprovadas": 0}
    por_setor = {}
    secoes = [x for x in c.secoes.prefetch_related("setores").select_related("pai")
              if x.pai_id is not None or x.pk in com_texto]
    secoes.sort(key=lambda x: ((x.pai.ordem if x.pai else x.ordem), 0 if x.pai is None else 1, x.ordem))
    for s in secoes:
        if s.situacao == Secao.ENVIADA:
            aguardando.append(s)
        f, t = A.progresso_secao(calc, s, numeros=True)
        for alvo in [geral] + [por_setor.setdefault(x.sigla, {"setor": x, "f": 0, "t": 0, "secoes": 0, "escritas": 0,
                                                              "enviadas": 0, "aprovadas": 0}) for x in s.setores.all()]:
            alvo["f"] += f
            alvo["t"] += t
            alvo["secoes"] += 1
            alvo["escritas"] += s.pk in escrito
            alvo["com_texto"] = alvo.get("com_texto", 0) + (s.pk in com_texto)
            alvo["marcas"] = alvo.get("marcas", 0) + marcas.get(s.pk, 0)
            alvo["enviadas"] += s.situacao in (Secao.ENVIADA, Secao.APROVADA)
            alvo["aprovadas"] += s.situacao == Secao.APROVADA
        if not (meus & {x.pk for x in s.setores.all()}):
            continue
        f_tot, t_tot = f_tot + f, t_tot + t
        ps = [p for p in pend if p.quadro.secao_id == s.pk]
        minhas.append({"s": s, "pct": A.percentual(f, t), "tem_dados": t > 0, "escrito": s.pk in escrito,
                       "a_revisar": s.pk in a_revisar, "metas": metas.get(s.pk),
                       "marcas": marcas.get(s.pk, 0), "tem_texto": s.pk in com_texto,
                       "pode": F.pode_editar_texto(user, s), "acoes": F.acoes_possiveis(user, s),
                       **consistencia.resumo(ps)})
    entregues = sum(1 for m in minhas if m["s"].situacao in (Secao.ENVIADA, Secao.APROVADA))
    # prazo e seções paradas (para o Master achar o que está atrasado)
    from datetime import date

    from django.db.models import Max

    from relatorio.models import Valor
    hoje = date.today()
    dias = (c.prazo - hoje).days if c.prazo else None
    ultima = {}
    for sid, quando in Bloco.objects.filter(secao__ciclo=c, atualizado_por__isnull=False).values_list(
            "secao_id").annotate(m=Max("atualizado_em")):      # só o que alguém mexeu (não a preparação do sistema)
        ultima[sid] = quando
    for sid, quando in Valor.objects.filter(linha__quadro__ciclo=c, atualizado_por__isnull=False).values_list(
            "linha__quadro__secao_id").annotate(m=Max("atualizado_em")):
        if quando and (sid not in ultima or not ultima[sid] or quando > ultima[sid]):
            ultima[sid] = quando
    paradas = []
    if P.e_master(user) or P.e_admin(user):
        for s in secoes:
            if s.situacao in (Secao.ENVIADA, Secao.APROVADA) or not s.setores.all():
                continue
            paradas.append({"s": s, "ultima": ultima.get(s.pk), "setores": list(s.setores.all()),
                            "atrasada": dias is not None and dias < 0})
        paradas.sort(key=lambda d: (d["ultima"] is not None, d["ultima"] or 0))
    from relatorio import permissoes as RP
    from relatorio.consistencia import _metas_pdi
    for m in minhas:
        m["ultima"] = ultima.get(m["s"].pk)
        # o que falta preencher: números das tabelas, xxxxx do texto e, no apêndice, as metas da unidade
        m["falta"] = m["faltam"] + F.campos_vazios_da_secao(m["s"])
        q = calc.quadros.get("pdi_metas")
        if q is not None and q.secao_id == m["s"].pk:
            abertas = [c for c in calc.colunas_de(q) if not c.travada]
            m["falta"] = sum(1 for p in _metas_pdi(calc, q, abertas)
                             if p.linha is not None and abertas and RP.pode_editar_celula(user, p.linha, abertas[0]))
    for d in [geral] + list(por_setor.values()):
        d["pct"] = A.percentual(d["f"], d["t"])
    acompanha = P.e_master(user) or P.e_admin(user)
    return {"ciclo": c, "minhas_secoes": minhas, "resumo_ciclo": consistencia.resumo(pend),
            "pct_meus": A.percentual(f_tot, t_tot), "n_escritas": sum(1 for m in minhas if m["escrito"]),
            "n_com_texto": sum(1 for m in minhas if m["tem_texto"]),
            "n_marcas": sum(m["marcas"] for m in minhas),
            "n_entregues": entregues, "aguardando": aguardando if P.e_master(user) else [],
            "falta_total": sum(m.get("falta", 0) for m in minhas),
            "primeira_minha": minhas[0]["s"].chave if minhas else "",
            "andamento": geral if acompanha else None,
            "prazo_dias": dias, "paradas": paradas[:12], "n_paradas": len(paradas),
            "n_atrasadas": sum(1 for d in paradas if d["atrasada"]),
            "por_setor": sorted(por_setor.values(), key=lambda d: d["setor"].sigla) if acompanha else []}


@login_required
def conta(request):
    vinculos = VinculoSetor.objects.filter(usuario=request.user).select_related("setor")
    return render(request, "contas/conta.html", {"vinculos": vinculos, "papeis": P.papeis(request.user)})


# --- Usuários ------------------------------------------------------------------
def _situacao(u):
    p = getattr(u, "perfil_sirg", None)
    if not u.is_active:
        return ("inativo", "secondary")
    if p and p.bloqueado:
        return ("bloqueado", "danger")
    if p and p.troca_senha:
        return ("aguardando 1º acesso", "warning")
    return ("ativo", "success")


@login_required
@P.admin_obrigatorio
def usuarios(request):
    q = request.GET.get("q", "").strip()
    setor = request.GET.get("setor", "")
    perfil = request.GET.get("perfil", "")
    situacao = request.GET.get("situacao", "ativos")
    vinc_ativos = Prefetch("vinculos_setor", queryset=VinculoSetor.objects.filter(fim__isnull=True)
                           .select_related("setor"), to_attr="vinculos_ativos")
    qs = User.objects.select_related("perfil_sirg").prefetch_related(vinc_ativos).order_by("first_name", "username")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(email__icontains=q))
    if setor == "sem":
        qs = qs.filter(~_tem_vinculo_ativo())
    elif setor:
        qs = qs.filter(vinculos_setor__setor__sigla=setor, vinculos_setor__fim__isnull=True)
    if perfil == "admin":
        qs = qs.filter(Q(perfil_sirg__e_admin=True) | Q(is_superuser=True))
    elif perfil == "master":
        qs = qs.filter(perfil_sirg__e_master=True)
    if situacao == "ativos":
        qs = qs.filter(is_active=True)
    elif situacao == "inativos":
        qs = qs.filter(is_active=False)
    elif situacao == "pendentes":
        qs = qs.filter(is_active=True, perfil_sirg__troca_senha=True)
    qs = qs.distinct()
    pag = Paginator(qs, 50).get_page(request.GET.get("pagina"))
    linhas = [(u, _situacao(u)) for u in pag]
    params = urlencode({k: v for k, v in request.GET.items() if k != "pagina"})
    return render(request, "contas/usuarios.html", {
        "linhas": linhas, "pag": pag, "q": q, "setor_sel": setor, "perfil_sel": perfil, "situacao_sel": situacao,
        "setores": Setor.objects.all(), "params": params, "total": qs.count()})


@login_required
@P.admin_obrigatorio
def usuario_novo(request):
    form = UsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        u, senha = S.criar_usuario(login=d["login"], nome=d["nome"], email=d["email"], e_admin=d["e_admin"],
                                   e_master=d["e_master"], setores=d["setores"], ator=request.user, request=request,
                                   e_diagramacao=d["e_diagramacao"])
        if d.get("observacao"):
            Perfil.objects.filter(usuario=u).update(observacao=d["observacao"])
        return render(request, "contas/senha_provisoria.html", {"alvo": u, "senha": senha, "novo": True})
    return render(request, "contas/usuario_form.html", {"form": form, "novo": True})


@login_required
@P.admin_obrigatorio
def usuario(request, pk):
    u = get_object_or_404(User.objects.select_related("perfil_sirg"), pk=pk)
    p = S.obter_perfil(u)
    inicial = {"nome": u.get_full_name(), "login": u.username, "email": u.email, "e_admin": p.e_admin or u.is_superuser,
               "e_master": p.e_master, "e_diagramacao": p.e_diagramacao, "observacao": p.observacao,
               "setores": Setor.objects.filter(vinculos__usuario=u, vinculos__fim__isnull=True)}
    form = UsuarioForm(request.POST or None, initial=inicial, usuario=u)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        mudou = S.atualizar_usuario(u, nome=d["nome"], email=d["email"], e_admin=d["e_admin"] or u.is_superuser,
                                    e_master=d["e_master"], observacao=d["observacao"], ator=request.user,
                                    request=request, e_diagramacao=d["e_diagramacao"])
        inc, enc = S.definir_setores(u, d["setores"], ator=request.user, request=request)
        partes = []
        if inc:
            partes.append("entrou em " + ", ".join(s.sigla for s in inc))
        if enc:
            partes.append("saiu de " + ", ".join(s.sigla for s in enc))
        if mudou:
            partes.append("dados atualizados")
        messages.success(request, f"{u.get_full_name() or u.username}: " + ("; ".join(partes) if partes
                                                                             else "nada foi alterado") + ".")
        return redirect("usuario", pk=u.pk)
    vinculos = VinculoSetor.objects.filter(usuario=u).select_related("setor", "incluido_por", "encerrado_por")
    eventos = EventoAuditoria.objects.filter(Q(usuario_alvo=u) | Q(ator=u)).select_related(
        "ator", "usuario_alvo", "setor")[:30]
    return render(request, "contas/usuario_form.html", {
        "form": form, "alvo": u, "perfil": p, "vinculos": vinculos, "eventos": eventos,
        "situacao": _situacao(u), "e_voce": u == request.user})


@login_required
@P.admin_obrigatorio
@require_POST
def usuario_acao(request, pk, acao):
    u = get_object_or_404(User, pk=pk)
    nome = u.get_full_name() or u.username
    if acao == "senha":
        senha = S.redefinir_senha(u, ator=request.user, request=request)
        return render(request, "contas/senha_provisoria.html", {"alvo": u, "senha": senha, "novo": False})
    if acao == "desbloquear":
        S.desbloquear(u, ator=request.user, request=request)
        messages.success(request, f"{nome} foi desbloqueado(a).")
    elif acao == "desativar":
        if u == request.user:
            messages.error(request, "Você não pode desativar o seu próprio usuário.")
        elif P.e_admin(u) and not S.pode_remover_admin(u):
            messages.error(request, "Este é o único administrador ativo: a plataforma ficaria sem administrador.")
        else:
            S.ativar(u, False, ator=request.user, request=request)
            messages.success(request, f"{nome} foi desativado(a). Os vínculos com setores foram encerrados; "
                                      f"o histórico continua registrado.")
    elif acao == "reativar":
        S.ativar(u, True, ator=request.user, request=request)
        messages.success(request, f"{nome} foi reativado(a). Vincule-o(a) aos setores, se for o caso.")
    else:
        raise Http404
    return redirect("usuario", pk=u.pk)


# --- Setores -------------------------------------------------------------------
@login_required
def setores(request):
    """Todos podem consultar os setores e seus membros; só administradores alteram."""
    qs = Setor.objects.annotate(n_membros=Count("vinculos", filter=Q(vinculos__fim__isnull=True,
                                                                     vinculos__usuario__is_active=True)))
    if request.GET.get("inativos") != "1":
        qs = qs.filter(ativo=True)
    return render(request, "contas/setores.html", {"setores": qs, "mostrar_inativos": request.GET.get("inativos") == "1"})


@login_required
def setor(request, pk):
    s = get_object_or_404(Setor, pk=pk)
    form = None
    if P.e_admin(request.user):
        form = SetorForm(request.POST or None, instance=s)
        if request.method == "POST" and form.is_valid():
            mudou = form.changed_data
            form.save()
            if mudou:
                S.registrar("setor_alterado", request.user, setor=s, descricao=", ".join(mudou), request=request)
            messages.success(request, f"Setor {s.sigla} salvo.")
            return redirect("setor", pk=s.pk)
    vinculos = VinculoSetor.objects.filter(setor=s).select_related("usuario", "incluido_por", "encerrado_por")
    return render(request, "contas/setor.html", {"setor": s, "form": form, "vinculos": vinculos,
                                                 "membros": [v for v in vinculos if v.ativo and v.usuario.is_active]})


@login_required
@P.admin_obrigatorio
def setor_novo(request):
    form = SetorForm(request.POST or None, initial={"ativo": True, "ordem": (Setor.objects.count() + 1) * 10})
    if request.method == "POST" and form.is_valid():
        s = form.save()
        S.registrar("setor_criado", request.user, setor=s, descricao=s.rotulo, request=request)
        messages.success(request, f"Setor {s.sigla} criado.")
        return redirect("setor", pk=s.pk)
    return render(request, "contas/setor.html", {"form": form, "novo": True})


# --- Instituição e auditoria ------------------------------------------------------
@login_required
@P.admin_obrigatorio
def instituicao(request):
    inst = Instituicao.atual()
    form = InstituicaoForm(request.POST or None, request.FILES or None, instance=inst)
    if request.method == "POST":
        if request.POST.get("restaurar") in ("logo", "faixa_unidade"):
            campo = request.POST["restaurar"]
            getattr(inst, campo).delete(save=False)
            setattr(inst, campo, "")
            inst.save()
            S.registrar("instituicao_alterada", request.user, descricao=f"{campo} restaurado ao padrão",
                        request=request)
            messages.success(request, "Imagem padrão restaurada.")
            return redirect("instituicao")
        if form.is_valid():
            mudou = form.changed_data
            form.save()
            if mudou:
                S.registrar("instituicao_alterada", request.user, descricao=", ".join(mudou), request=request)
            messages.success(request, "Dados da instituição salvos.")
            return redirect("instituicao")
    return render(request, "contas/instituicao.html", {"form": form, "inst": inst})


@login_required
@P.admin_obrigatorio
def auditoria(request):
    qs = EventoAuditoria.objects.select_related("ator", "usuario_alvo", "setor")
    acao = request.GET.get("acao", "")
    usuario = request.GET.get("usuario", "").strip()
    if acao:
        qs = qs.filter(acao=acao)
    if usuario:
        qs = qs.filter(Q(ator__username__icontains=usuario) | Q(usuario_alvo__username__icontains=usuario)
                       | Q(ator__first_name__icontains=usuario) | Q(usuario_alvo__first_name__icontains=usuario))
    pag = Paginator(qs, 50).get_page(request.GET.get("pagina"))
    params = urlencode({k: v for k, v in request.GET.items() if k != "pagina"})
    return render(request, "contas/auditoria.html", {"pag": pag, "acoes": EventoAuditoria.ACOES, "acao_sel": acao,
                                                     "usuario": usuario, "params": params})


@login_required
def ajuda(request):
    """Manual de uso (docs/MANUAL.md), com sumário lateral."""
    import markdown
    from django.utils.safestring import mark_safe
    arquivo = settings.BASE_DIR / "docs" / "MANUAL.md"
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except OSError:
        raise Http404("O manual não foi encontrado.")
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-2", "permalink": False}})
    html = md.convert(texto)
    titulo = texto.splitlines()[0].lstrip("# ").strip() if texto else "Manual"
    corpo = html.split("</h1>", 1)[-1]
    # o arquivo é parte da plataforma (não vem de usuários); mesmo assim, nada de HTML cru no .md
    return render(request, "contas/ajuda.html", {"titulo": titulo, "conteudo": mark_safe(corpo),
                                                 "sumario": md.toc_tokens})


def implantacoes(limite=8):
    """Últimas instalações feitas pelo implantador automático (Git), gravadas em dados/implantacao.json."""
    import json
    arq = settings.DADOS_DIR / "implantacao.json"
    try:
        dados = json.loads(arq.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    lista = dados if isinstance(dados, list) else [dados]
    return [x for x in lista if isinstance(x, dict)][-limite:][::-1]


@login_required
def sobre(request):
    """Informações sobre o sistema: o que é, quem desenvolveu, versão atual e histórico de versões."""
    ver_implantacao = P.e_master(request.user) or P.e_admin(request.user)
    return render(request, "contas/sobre.html", {"versoes": VERSOES,
                                                 "implantacoes": implantacoes() if ver_implantacao else []})


# Histórico de versões mostrado na tela "Sobre" (a mais recente primeiro).
VERSOES = [
    ("2.14.1", "novembro de 2026", [
        "Implantação pelo Git: o código fica num repositório; a homologação se atualiza sozinha quando há código novo aprovado nos testes, e a produção quando sai uma versão marcada (tag), depois de passar pela homologação.",
        "Tela Sobre: para o Master e o administrador, mostra o código instalado (commit) e o resultado das últimas instalações automáticas.",
    ]),
    ("2.14", "novembro de 2026", [
        "Gráficos nas páginas: ao preencher os dados, o gráfico se redesenha no mesmo lugar e do mesmo tamanho (antes, voltava no formato antigo, por cima da página).",
        "Painéis que no PDF eram imagem agora são editáveis no lugar: Ouvidoria (tipos e situação das manifestações, resolutividade, rankings por assunto e subassunto como gráficos), painel da LAI, PGEN, gestão de riscos, integridade, principais despesas de investimento, custos e a matriz SWOT.",
        "Word no formato das páginas do RG: cada página do mesmo tamanho, com o fundo e cada caixa de texto, gráfico e tabela no lugar (caixas de texto editáveis no Word).",
        "Faltam N: leva também aos totais e às tabelas da seção que não aparecem nas páginas; conta só o que a pessoa preenche. Números em milhões (R$ 5,82 milhões) são digitados em milhões.",
        "Correções encontradas preenchendo o relatório inteiro pela tela: tabelas maiores que a área, travamento ao abrir dados de outro setor, campos de texto das metas aparecendo como xxxxx.",
    ]),
    ("2.13", "novembro de 2026", [
        "O relatório agora são as páginas do RG 2025 publicado, com a mesma diagramação (cores, fotos, caixas, fontes e posições). Os números a atualizar aparecem como xxxxx, no lugar exato de cada um.",
        "Os gráficos ficam no mesmo lugar da página e são desenhados com os dados da plataforma, já com 2026: clicar no gráfico abre a tabela ao lado.",
        "Cada caixa de texto da página se altera ali mesmo, com o controle de alterações e os comentários. Os números das tabelas citados no texto vêm ligados aos quadros.",
        "Ver como fica: imprimir gera o PDF com as páginas no tamanho do RG.",
    ]),
    ("2.12", "novembro de 2026", [
        "Uma tela só para preencher, escrever e ler: o relatório aparece como o RG 2025 publicado e os números a atualizar vêm como xxxxx; clicar no xxxxx abre o campo para digitar o valor de 2026.",
        "Gráficos e tabelas: o botão “Dados” abre a tabela ao lado do texto; digitado o número de 2026, o gráfico se atualiza na hora.",
        "Botão “Faltam N” leva de um número em branco ao próximo; cada seção mostra quantos faltam e o link para a página do RG 2025 em PDF.",
        "Sem menu lateral: um único menu no alto da tela. Menos texto de orientação na tela.",
        "Os setores editam só o texto que já está no relatório, sempre com o controle de alterações ligado; o Master aceita ou recusa. Novos trechos e imagens ficam com o Master.",
        "Apêndice trocado pela planilha “Acompanhamento das metas do PDI 2023-2027” (41 metas): cada unidade líder informa situação, justificativa e evidência; o Master baixa a planilha preenchida.",
        "Paletas de cores editáveis pela diagramação: criar, importar (.ase, .gpl ou códigos), reordenar, baixar em .ase e escolher a paleta em uso. Novo perfil “Diagramação”.",
        "Ambiente de homologação (porta 8003, faixa laranja) e os instaladores instalar_hml.bat e subir_prd.bat, que leem o pacote .zip direto, sem extrair.",
    ]),
    ("2.11", "novembro de 2026", [
        "Controle de alterações como no Word, em Escrever o relatório: com o botão “Controlar alterações” ligado, o que se digita fica sublinhado em verde e o que se apaga fica riscado, com o nome de quem fez e a hora.",
        "Cada alteração é aceita ou recusada separadamente: clicando nela no texto ou no novo painel de revisão, que lista as alterações por seção, com “Aceitar as N” e “Recusar” da seção inteira.",
        "Comentários presos a um trecho selecionado (marcado em amarelo), com respostas, resolver e reabrir. Quem não escreve a seção também comenta.",
        "Ler o relatório, o Word e o pacote da diagramação levam só o que foi aceito; as alterações pendentes aparecem em O que falta.",
        "O setor aceita ou recusa as alterações do Master antes de enviar; o Master só aprova a seção sem alterações pendentes.",
        "O modo “Sugerir” do Master (sugestão do trecho inteiro) deu lugar ao controle de alterações, que já começa ligado para o Master.",
        "Números, imagens e texto colado entram marcados; “Limpar formatação” não apaga as marcas.",
    ]),
    ("2.10", "novembro de 2026", [
        "Correções da auditoria independente de dados e lógica (591 valores conferidos com o RG 2025, sem divergência).",
        "Atualizar não desfaz mais o que o Master ajustou: nomes e fórmulas de linhas, regras apagadas e tabelas/gráficos acrescentados ficam como estão.",
        "Total de uma tabela em branco enquanto falta alguma parcela do ano (antes saía uma soma parcial).",
        "Valor digitado diferente do automático passa a impedir o envio até alguém escolher “corrigir” ou “ignorar”.",
        "Regras de mobilidade internacional conferem o ano do relatório (antes olhavam o ano anterior).",
        "Execução orçamentária: Empenhado ≤ dotação, Liquidado ≤ empenhado e Pago ≤ liquidado conferidos em cada grupo de despesa.",
        "Novas conferências: conceitos da CPA × notas da graduação, cursos de pós × Pós-graduação em números, LAI somando 100%, cursos de extensão × natureza das ações.",
        "Números em milhões no texto (ex.: “R$ 570,87 milhões”) passam a vir do quadro e saem na mesma escala.",
        "Percentual digitado fora de 0% a 100% gera aviso; LAI com 2 casas decimais; definição da frota restaurada.",
    ]),
    ("2.9", "novembro de 2026", [
        "Correções do diagnóstico de usabilidade (20 pontos): tabelas e gráficos do RG 2025 colados no texto saem quando o sistema já monta o mesmo objeto.",
        "A tabela que sai numa seção e mora em outra (ex.: Tabela 1 de Execução orçamentária) aparece também na seção onde sai, e conta no “Terminei”.",
        "Início: prazo da coleta com os dias que faltam; para o Master, as seções ainda não enviadas, das paradas há mais tempo, com a última alteração e o selo “atrasada”; setores clicáveis.",
        "Célula com valor inválido fica marcada em vermelho, com a mensagem embaixo, e não conta como preenchida; Esc desfaz.",
        "Aviso de variação acima de 50% em todos os quadros por ano, com alerta de provável erro de unidade.",
        "“Enviar ao Master” fica desativado, com o motivo, enquanto faltam números ou correções.",
        "O que falta junta os campos em branco de cada tabela numa linha só; “Abrir” leva até a célula, sem colar no topo, já pronta para digitar.",
        "Gráficos de barras com muitos nomes compridos passam para a horizontal.",
        "Inserir número não pula a tela e mostra de onde o número vem.",
        "Primeiro acesso: só a nova senha (sem pedir a provisória de novo), com o botão de mostrar a senha.",
        "Celular: o menu fica recolhido no botão “Menu”. Link “Pular para o conteúdo” e textos cinza mais escuros.",
        "A dotação atualizada da LOA vem da Tabela 1 (um número só).",
    ]),
    ("2.8", "novembro de 2026", [
        "O atualizar.bat para o servidor, atualiza e liga de novo sozinho (pede permissão de administrador ao abrir).",
    ]),
    ("2.7", "novembro de 2026", [
        "Nova tela de entrada no padrão dos sistemas da DGDI: marca da UFCIMG à esquerda, em azul-marinho, e o formulário à direita (no celular, um embaixo do outro).",
        "Botão para mostrar ou esconder a senha ao digitar.",
    ]),
    ("2.6", "novembro de 2026", [
        "Mensagem da dirigente máxima começa em branco (a do ano anterior fica só para consulta).",
        "Excel: nomes de abas que o Excel aceita sem reclamar (sem espaço no fim) e validações só onde há células.",
        "“Terminei: o que faço agora?” confere de novo os números já gravados e leva ao painel do fim, com destaque.",
        "A prévia do gráfico aparece já na tela de números, mesmo sem valores, e diz quais colunas o gráfico usa.",
        "Gráficos com acabamento de publicação: rosca com percentuais de duas casas e total no centro; barras empilhadas com valores em R$ milhões, sem repetir a unidade.",
        "Tela de números mais limpa: uma linha de ajuda (o resto em “Mais ajuda”); a orientação do texto fica só no Escrever.",
        "Planilha “Conferir as conexões” (em O que falta): todas as ligações entre números e relatório, para conferir contra o RG publicado.",
        "Números de normas e processos (ex.: Decisão Normativa nº 198/2022) não são mais ligados a quadros por engano.",
    ]),
    ("2.5", "novembro de 2026", [
        "Nova identidade visual da UFCIMG: marca na tela de entrada, no menu e na capa do Word; telas no azul-marinho e verde-água da marca.",
        "Paleta de gráficos “UFCIMG (azul e verde-água)”, conferida para daltonismo, passa a ser a padrão (o Master pode trocar em “Cores dos gráficos”).",
        "“CEFET-MG” passa a “UFCIMG” nos títulos de seções, quadros e gráficos (as metas do PDI mantêm o texto original).",
        "Nos textos, cada menção ao CEFET-MG fica em amarelo e quem escreve escolhe: manter CEFET-MG (fato histórico) ou trocar por UFCIMG.",
        "Word: parágrafos com quebras de linha (dirigentes, obras) ficam alinhados à esquerda, sem espaços esticados.",
    ]),
    ("2.4", "novembro de 2026", [
        "Ajustes do piloto: Preencher os números mostra só as seções do seu setor; “Quem somos” ficou só com a SEGEP.",
        "Pente fino dos números: cerca de 25 quadros novos nos capítulos de orçamento, custos, patrimônio, frota, TI, ouvidoria, sustentabilidade, CPA e governança, com os valores do RG 2025.",
        "Cada quadro diz onde aparece no relatório (e avisa quando é em outra seção); cada gráfico do Escrever diz de qual quadro e setor vêm os números.",
        "Fim da seção claro: painel “Terminei: o que faço agora?”, com o que falta, revisar o texto e Enviar ao Master.",
        "Gráficos de barras empilhadas mais legíveis (valores abreviados e total em cima); tabelas com muitos anos abrem na coluna do ano.",
        "Painel de fotos das obras volta a ser um cartão por obra (lugar da foto, nome, situação e valor).",
    ]),
    ("2.3", "outubro de 2026", [
        "Nome novo da instituição: Universidade Federal de Ciência e Inovação de Minas Gerais – UFCIMG.",
        "Nova seção “UFCIMG em números”, com os 14 objetivos estratégicos, na Apresentação.",
        "Paletas de cores para os gráficos, escolhidas pelo Master em “Cores dos gráficos”.",
        "atualizar.bat para atualizar com dois cliques; servidor.bat mostra o erro em vez de fechar a janela.",
    ]),
    ("2.2", "outubro de 2026", [
        "Interface mais simples: menu sem cabeçalho, botão do usuário no topo do menu, símbolo do SiRG na aba do navegador e esta tela Sobre.",
        "Escrever o relatório: só as suas seções aparecem com ferramentas; cabeçalho da seção em bloco único; campos que você edita com cor de destaque; chave “Só o que eu escrevo” no sumário.",
        "Texto do RG 2025 sem destaques prévios em amarelo (o marca-texto continua disponível).",
        "Metas do PDI preenchidas no próprio texto; Preencher os números só com números.",
        "Imagens no texto, Ctrl+Z / Ctrl+Y, origem de cada número “[a preencher]”.",
        "Gráficos no formato do RG 2025 (barras com linha e segundo eixo).",
        "Tabelas calculadas aceitam também valor digitado, com aviso de divergência (corrigir ou ignorar).",
        "Filtros em Preencher os números e O que falta.",
        "Assistente de IA retirado.",
    ]),
    ("2.1", "outubro de 2026", [
        "Estrutura e texto do RG 2025 como ponto de partida do RG 2026, com o texto publicado para consulta e link para o PDF.",
        "Apêndice com as metas do PDI por área.",
        "Tabelas calculadas mostram “aguardando dados” enquanto a origem não é preenchida.",
    ]),
    ("2.0", "outubro de 2026", [
        "Plataforma focada no RG 2026, tela inicial em 3 passos, gráfico ao lado das tabelas, documento editável e leitura do texto final.",
    ]),
    ("1.0", "outubro de 2026", [
        "Primeira versão: setores, perfis, preenchimento dos quadros, textos, auditoria, backup e exportação para Word.",
    ]),
]


@login_required
def cores_graficos(request):
    """Paletas de cores dos gráficos: escolher a usada, criar, editar, importar e baixar (Master e diagramação)."""
    from django.core.exceptions import PermissionDenied

    from relatorio import graficos, paletas

    from .models import Paleta
    if not P.cuida_das_cores(request.user):
        raise PermissionDenied
    inst = Instituicao.atual()
    if request.method == "POST":
        acao, ch = request.POST.get("acao", "usar"), request.POST.get("paleta", "")
        p = Paleta.objects.filter(chave=ch).first()
        if p is None:
            messages.error(request, "Paleta não encontrada.")
        elif acao == "usar" and ch != inst.paleta_graficos:
            inst.paleta_graficos = ch
            inst.save(update_fields=["paleta_graficos"])
            S.registrar("instituicao_alterada", request.user, descricao=f"cores dos gráficos: {p.nome}", request=request)
            messages.success(request, f"Paleta “{p.nome}” aplicada a todos os gráficos.")
        elif acao == "duplicar":
            nova = Paleta.objects.create(chave=_chave_paleta(f"{p.chave}-copia"), nome=f"{p.nome} (cópia)"[:80],
                                         descricao=p.descricao, cores=list(p.cores), atualizada_por=request.user)
            return redirect("paleta_editar", chave=nova.chave)
        elif acao == "excluir":
            if ch == inst.paleta_graficos:
                messages.error(request, "Esta paleta está em uso. Escolha outra antes de excluir.")
            elif p.sistema:
                messages.error(request, "As paletas que vêm com a plataforma não são excluídas (edite ou restaure).")
            else:
                S.registrar("instituicao_alterada", request.user, descricao=f"paleta excluída: {p.nome}", request=request)
                p.delete()
                messages.success(request, f"Paleta “{p.nome}” excluída.")
        elif acao == "restaurar" and p.sistema and p.chave in paletas.PALETAS:
            orig = paletas.PALETAS[p.chave]
            p.nome, p.descricao, p.cores, p.atualizada_por = orig["nome"], orig["descricao"], list(orig["cores"]), request.user
            p.save()
            messages.success(request, f"Paleta “{p.nome}” voltou às cores originais.")
        return redirect("cores_graficos")
    anos = ["2022", "2023", "2024", "2025", "2026"]
    opcoes = []
    atual = paletas.chave_atual()
    for ch, p in paletas.todas().items():
        opcoes.append({"chave": ch, "nome": p["nome"], "descricao": p["descricao"], "cores": p["cores"],
                       "sistema": p.get("sistema"), "atual": ch == atual, **_amostras(graficos, p["cores"], anos)})
    return render(request, "contas/cores_graficos.html", {"opcoes": opcoes})


def _amostras(graficos, cores, anos):
    barras = graficos.desenhar_com_cores(
        cores, anos, [("Alunos participantes", [168, 145, 148, 145, 152])], "inteiro",
        {"tipo": "barras", "linha": "recursos"}, "", "svg", 4.2,
        ("Recursos utilizados", [472003.38, 620341.2, 666890.0, 671406.99, 690000.0], "moeda", 2), 2)
    pizza = graficos.desenhar_com_cores(
        cores, ["Projeto", "Curso", "Evento", "Programa", "Prestação de serviços", "Outras"],
        [("Ações", [214, 71, 43, 25, 24, 12])], "inteiro", {"tipo": "pizza"}, "", "svg", 4.2, None, 2)
    return {"barras": barras, "pizza": pizza}


def _chave_paleta(base):
    from django.utils.text import slugify

    from .models import Paleta
    raiz = (slugify(base) or "paleta")[:32]
    ch, n = raiz, 2
    while Paleta.objects.filter(chave=ch).exists():
        ch, n = f"{raiz}-{n}", n + 1
    return ch


@login_required
def paleta_editar(request, chave=None):
    """Criar ou editar uma paleta: cores na ordem de uso, importadas de um arquivo (.ase, .gpl, .csv, .json,
    .txt) ou de uma lista colada de códigos #RRGGBB."""
    from django.core.exceptions import PermissionDenied

    from relatorio import graficos, paletas

    from .models import Paleta
    if not P.cuida_das_cores(request.user):
        raise PermissionDenied
    p = get_object_or_404(Paleta, chave=chave) if chave else None
    nome = p.nome if p else ""
    descricao = p.descricao if p else ""
    cores = list(p.cores) if p else ["#285C98", "#2A9C8E", "#E0802A", "#8C6BB8"]
    erros = []
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()[:80]
        descricao = request.POST.get("descricao", "").strip()[:300]
        cores = [c for c in (paletas.normalizar(x) for x in request.POST.getlist("cor")) if c]
        arq = request.FILES.get("arquivo")
        colado = request.POST.get("colar", "").strip()
        importadas = []
        if arq:
            try:
                importadas = paletas.ler_arquivo(arq.name, arq.read(2_000_000))
            except (ValueError, Exception) as ex:   # arquivo corrompido ou de outro tipo
                erros.append(f"Não foi possível ler o arquivo: {ex}")
            if arq and not importadas and not erros:
                erros.append("O arquivo não tem cores que a plataforma reconheça (.ase, .gpl ou códigos #RRGGBB).")
        if colado:
            importadas += paletas.ler_arquivo("colado.txt", colado.encode())
        if importadas:
            cores = importadas
        cores = cores[:12]
        if not nome:
            erros.append("Dê um nome à paleta.")
        if len(cores) < 2:
            erros.append("A paleta precisa de pelo menos 2 cores.")
        if request.POST.get("acao") == "previa" or importadas or erros:
            if importadas and not erros:
                messages.info(request, f"{len(importadas[:12])} cor(es) importada(s). Confira a ordem e clique em Salvar.")
        else:
            if p is None:
                p = Paleta(chave=_chave_paleta(nome))
            p.nome, p.descricao, p.cores, p.atualizada_por = nome, descricao, cores, request.user
            p.save()
            S.registrar("instituicao_alterada", request.user, descricao=f"paleta salva: {p.nome}", request=request)
            messages.success(request, f"Paleta “{p.nome}” salva.")
            return redirect("cores_graficos")
    amostra = _amostras(graficos, cores, ["2022", "2023", "2024", "2025", "2026"]) if len(cores) >= 2 else {}
    return render(request, "contas/paleta_form.html", {"p": p, "nome": nome, "descricao": descricao, "cores": cores,
                                                        "erros": erros, **amostra})


@login_required
def paleta_ase(request, chave):
    """Baixar a paleta como .ase (InDesign/Illustrator: Amostras > Carregar amostras)."""
    from django.core.exceptions import PermissionDenied
    from django.http import HttpResponse

    from relatorio import paletas

    from .models import Paleta
    if not P.cuida_das_cores(request.user):
        raise PermissionDenied
    p = get_object_or_404(Paleta, chave=chave)
    r = HttpResponse(paletas.gerar_ase(p.nome, p.cores), content_type="application/octet-stream")
    r["Content-Disposition"] = f'attachment; filename="paleta-{p.chave}.ase"'
    return r
