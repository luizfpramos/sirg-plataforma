"""
Regras de permissão da Plataforma SiRG — o único lugar que decide quem pode o quê.

Use sempre estas funções (nas telas, nos serviços e nos testes); nunca teste
flags do perfil diretamente.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from .models import Perfil, Setor


def perfil(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.perfil_sirg
    except Perfil.DoesNotExist:
        return Perfil.objects.create(usuario=user, troca_senha=False,
                                     e_admin=user.is_superuser, e_master=user.is_superuser)


def e_admin(user):
    """Administrador da plataforma: usuários, setores, instituição, ciclos e estrutura."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    p = perfil(user)
    return bool(user.is_superuser or (p and p.e_admin))


def e_master(user):
    """Master: edita qualquer parte do relatório."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    p = perfil(user)
    return bool(p and p.e_master)


def e_diagramacao(user):
    """Diagramação: paletas de cores dos gráficos e arquivos para a diagramação."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    p = perfil(user)
    return bool(p and p.e_diagramacao)


def cuida_das_cores(user):
    return e_master(user) or e_admin(user) or e_diagramacao(user)


def setores_ativos(user):
    """Setores (ativos) aos quais o usuário está vinculado hoje."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return Setor.objects.none()
    return Setor.objects.filter(ativo=True, vinculos__usuario=user, vinculos__fim__isnull=True).distinct()


def e_editor(user):
    return setores_ativos(user).exists()


def pode_editar_setor(user, setor):
    """Pode alterar dados e textos de responsabilidade do setor?"""
    if e_master(user):
        return True
    if setor is None:
        return False
    sid = setor.pk if isinstance(setor, Setor) else setor
    return setores_ativos(user).filter(pk=sid).exists()


def pode_editar_algum(user, setores):
    """Para conteúdos com mais de um setor responsável: basta ser de um deles."""
    if e_master(user):
        return True
    ids = [s.pk if isinstance(s, Setor) else s for s in setores]
    return setores_ativos(user).filter(pk__in=ids).exists()


def papeis(user):
    """Rótulos dos perfis do usuário, para mostrar na tela."""
    out = []
    if e_admin(user):
        out.append("Administrador")
    if e_master(user):
        out.append("Master")
    if e_diagramacao(user):
        out.append("Diagramação")
    if e_editor(user):
        out.append("Editor")
    if not out:
        out.append("Leitor")
    return out


def admin_obrigatorio(view):
    @wraps(view)
    def _view(request, *args, **kwargs):
        if not e_admin(request.user):
            raise PermissionDenied("Esta área é exclusiva dos administradores da plataforma.")
        return view(request, *args, **kwargs)
    return _view
