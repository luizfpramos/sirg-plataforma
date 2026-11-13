from django.conf import settings

from . import permissoes as P
from .models import Instituicao


def global_sirg(request):
    try:
        inst = Instituicao.atual()
    except Exception:  # banco ainda sem tabelas (antes do migrate)
        inst = None
    base = {"NOME_SISTEMA": "SiRG", "NOME_SISTEMA_LONGO": "Sistema do Relatório de Gestão",
            "INST": inst, "DEBUG": settings.DEBUG, "VERSAO": settings.SIRG_VERSAO,
            "CONTATO": getattr(settings, "SIRG_CONTATO", ""),
            "HOMOLOGACAO": getattr(settings, "SIRG_AMBIENTE", "prd") == "hml"}
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return base
    base.update({
        "E_ADMIN": P.e_admin(u),
        "E_MASTER": P.e_master(u),
        "E_DIAGRAMACAO": P.e_diagramacao(u),
        "MEUS_SETORES": list(P.setores_ativos(u)),
        "PAPEIS": P.papeis(u),
        "TROCA_SENHA": bool(P.perfil(u) and P.perfil(u).troca_senha),
    })
    return base
