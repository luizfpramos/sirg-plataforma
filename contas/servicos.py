"""Operações sobre usuários e setores, sempre com registro na trilha de auditoria."""
import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import EventoAuditoria, Perfil, Setor, VinculoSetor

log = logging.getLogger("sirg")
User = get_user_model()

# Sem letras/dígitos que se confundem (0/O, 1/l/I)
_ALFABETO = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def ip_de(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def registrar(acao, ator=None, alvo=None, setor=None, descricao="", dados=None, request=None):
    ev = EventoAuditoria.objects.create(
        acao=acao, ator=ator if getattr(ator, "is_authenticated", False) else None,
        usuario_alvo=alvo, setor=setor, descricao=descricao[:500], dados=dados or {}, ip=ip_de(request))
    log.info("auditoria %s ator=%s alvo=%s %s", acao, ator, alvo, descricao)
    return ev


def gerar_senha_provisoria():
    """Ex.: 'k7Qm-x3Rt-9pWz' — fácil de ditar e forte o bastante para o primeiro acesso."""
    blocos = ["".join(secrets.choice(_ALFABETO) for _ in range(4)) for _ in range(3)]
    senha = "-".join(blocos)
    # garante ao menos um dígito (validador "somente números" e boa prática)
    if not any(c.isdigit() for c in senha):
        senha = senha[:-1] + secrets.choice("23456789")
    return senha


def obter_perfil(usuario):
    """Perfil do usuário (usa o objeto já carregado em usuario.perfil_sirg, para não ficar desatualizado)."""
    try:
        return usuario.perfil_sirg
    except Perfil.DoesNotExist:
        return Perfil.objects.create(usuario=usuario)


@transaction.atomic
def criar_usuario(*, login, nome, email="", e_admin=False, e_master=False, setores=(), ator=None, request=None,
                  senha=None, e_diagramacao=False):
    """Cria o usuário com senha provisória (troca obrigatória no 1º acesso). Devolve (usuario, senha)."""
    senha = senha or gerar_senha_provisoria()
    partes = (nome or "").strip().split(" ", 1)
    u = User.objects.create_user(username=login.strip(), email=(email or "").strip(), password=senha,
                                 first_name=partes[0][:150], last_name=(partes[1] if len(partes) > 1 else "")[:150])
    p = obter_perfil(u)
    p.e_admin, p.e_master, p.troca_senha = bool(e_admin), bool(e_master), True
    p.e_diagramacao = bool(e_diagramacao)
    p.save()
    registrar("usuario_criado", ator, u, descricao=f"{u.get_full_name()} ({u.username})",
              dados={"admin": p.e_admin, "master": p.e_master}, request=request)
    definir_setores(u, setores, ator=ator, request=request)
    return u, senha


@transaction.atomic
def atualizar_usuario(u, *, nome, email, e_admin, e_master, observacao="", ator=None, request=None, e_diagramacao=None):
    p = obter_perfil(u)
    if e_diagramacao is None:
        e_diagramacao = p.e_diagramacao
    antes = {"nome": u.get_full_name(), "email": u.email, "admin": p.e_admin, "master": p.e_master,
             "diagramacao": p.e_diagramacao}
    partes = (nome or "").strip().split(" ", 1)
    u.first_name = partes[0][:150]
    u.last_name = (partes[1] if len(partes) > 1 else "")[:150]
    u.email = (email or "").strip()
    u.save()
    p.e_admin, p.e_master, p.observacao = bool(e_admin), bool(e_master), observacao or ""
    p.e_diagramacao = bool(e_diagramacao)
    p.save()
    depois = {"nome": u.get_full_name(), "email": u.email, "admin": p.e_admin, "master": p.e_master,
              "diagramacao": p.e_diagramacao}
    mudou = {k: [antes[k], depois[k]] for k in antes if antes[k] != depois[k]}
    if mudou:
        registrar("usuario_alterado", ator, u, descricao=", ".join(_rotulo_campo(k) for k in mudou),
                  dados=mudou, request=request)
    return mudou


def _rotulo_campo(k):
    return {"nome": "nome", "email": "e-mail", "admin": "perfil Administrador", "master": "perfil Master",
            "diagramacao": "perfil Diagramação"}.get(k, k)


@transaction.atomic
def definir_setores(u, setores, ator=None, request=None):
    """Deixa o usuário vinculado exatamente aos setores informados.

    Vínculos que saem são ENCERRADOS (não apagados); os novos começam agora.
    Devolve (incluidos, encerrados) como listas de setores.
    """
    desejados = {s.pk: s for s in setores}
    agora = timezone.now()
    ativos = {v.setor_id: v for v in VinculoSetor.objects.select_related("setor").filter(usuario=u, fim__isnull=True)}
    encerrados, incluidos = [], []
    for sid, v in ativos.items():
        if sid not in desejados:
            v.fim, v.encerrado_por = agora, (ator if getattr(ator, "is_authenticated", False) else None)
            v.save(update_fields=["fim", "encerrado_por"])
            encerrados.append(v.setor)
            registrar("setor_desvinculado", ator, u, setor=v.setor, descricao=f"Saiu de {v.setor.sigla}",
                      request=request)
    for sid, s in desejados.items():
        if sid not in ativos:
            VinculoSetor.objects.create(usuario=u, setor=s, inicio=agora,
                                        incluido_por=ator if getattr(ator, "is_authenticated", False) else None)
            incluidos.append(s)
            registrar("setor_vinculado", ator, u, setor=s, descricao=f"Entrou em {s.sigla}", request=request)
    return incluidos, encerrados


def redefinir_senha(u, ator=None, request=None):
    senha = gerar_senha_provisoria()
    u.set_password(senha)
    u.save(update_fields=["password"])
    p = obter_perfil(u)
    p.troca_senha, p.tentativas_falhas, p.bloqueado_ate = True, 0, None
    p.save(update_fields=["troca_senha", "tentativas_falhas", "bloqueado_ate", "atualizado_em"])
    registrar("senha_redefinida", ator, u, request=request)
    return senha


def desbloquear(u, ator=None, request=None):
    p = obter_perfil(u)
    p.tentativas_falhas, p.bloqueado_ate = 0, None
    p.save(update_fields=["tentativas_falhas", "bloqueado_ate", "atualizado_em"])
    registrar("desbloqueio", ator, u, request=request)


def admins_ativos():
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(perfil_sirg__e_admin=True)).distinct()


def pode_remover_admin(u):
    """Impede ficar sem nenhum administrador ativo."""
    return admins_ativos().exclude(pk=u.pk).exists()


@transaction.atomic
def ativar(u, ativo, ator=None, request=None):
    if u.is_active == ativo:
        return
    u.is_active = ativo
    u.save(update_fields=["is_active"])
    if not ativo:
        # encerra os vínculos: um usuário desativado não deve aparecer como membro do setor
        definir_setores(u, [], ator=ator, request=request)
    registrar("usuario_reativado" if ativo else "usuario_desativado", ator, u, request=request)


# --- Login: tentativas e bloqueio ------------------------------------------
def falha_de_login(login, request=None):
    u = User.objects.filter(username__iexact=login).first()
    if not u:
        registrar("login_falha", None, None, descricao=f"Login inexistente: {login[:60]}", request=request)
        return None
    p = obter_perfil(u)
    p.tentativas_falhas += 1
    campos = ["tentativas_falhas", "atualizado_em"]
    bloqueou = False
    if p.tentativas_falhas >= settings.SIRG_MAX_TENTATIVAS:
        p.bloqueado_ate = timezone.now() + timezone.timedelta(minutes=settings.SIRG_BLOQUEIO_MINUTOS)
        p.tentativas_falhas = 0
        campos.append("bloqueado_ate")
        bloqueou = True
    p.save(update_fields=campos)
    registrar("bloqueio" if bloqueou else "login_falha", None, u, request=request)
    return p


def sucesso_de_login(u, request=None):
    p = obter_perfil(u)
    if p.tentativas_falhas or p.bloqueado_ate:
        p.tentativas_falhas, p.bloqueado_ate = 0, None
        p.save(update_fields=["tentativas_falhas", "bloqueado_ate", "atualizado_em"])
    registrar("login", u, u, request=request)


# --- Setores ---------------------------------------------------------------
SETORES_2025 = [
    ("GAB", "Gabinete da Direção-Geral"),
    ("DEPT", "Diretoria de Educação Profissional e Tecnológica"),
    ("DIRGRAD", "Diretoria de Graduação"),
    ("DPPG", "Diretoria de Pesquisa e Pós-Graduação"),
    ("DEDC", "Diretoria de Extensão e Desenvolvimento Comunitário"),
    ("DAE", "Diretoria de Assuntos Estudantis"),
    ("DGDI", "Diretoria de Governança e Desenvolvimento Institucional"),
    ("DPG", "Diretoria de Planejamento e Gestão"),
    ("DTI", "Diretoria de Tecnologia da Informação"),
    ("SECOM", "Secretaria de Comunicação Social"),
    ("SEGEP", "Secretaria de Gestão de Pessoas"),
    ("SRCA", "Secretaria de Registro e Controle Acadêmico"),
    ("SRI", "Secretaria de Relações Internacionais"),
    ("CPA", "Comissão Própria de Avaliação"),
]


def criar_setores_iniciais():
    """Cria os setores da estrutura de 2025 que ainda não existirem. Devolve quantos criou."""
    n = 0
    for i, (sigla, nome) in enumerate(SETORES_2025, start=1):
        _, criado = Setor.objects.get_or_create(sigla=sigla, defaults={"nome": nome, "ordem": i * 10})
        n += int(criado)
    return n
