from django import template

register = template.Library()

ICONES = {
    "login": "bi-box-arrow-in-right acao-login", "logout": "bi-box-arrow-right",
    "login_falha": "bi-x-octagon acao-falha", "bloqueio": "bi-lock-fill acao-falha", "desbloqueio": "bi-unlock",
    "senha_trocada": "bi-shield-lock", "senha_redefinida": "bi-key acao-admin",
    "usuario_criado": "bi-person-plus acao-admin", "usuario_alterado": "bi-person-gear acao-admin",
    "usuario_desativado": "bi-person-x acao-falha", "usuario_reativado": "bi-person-check acao-login",
    "setor_vinculado": "bi-diagram-2 acao-admin", "setor_desvinculado": "bi-diagram-2",
    "setor_criado": "bi-plus-square acao-admin", "setor_alterado": "bi-pencil-square acao-admin",
    "instituicao_alterada": "bi-building acao-admin", "acesso_negado": "bi-slash-circle acao-falha",
}


@register.filter
def icone_acao(acao):
    return ICONES.get(acao, "bi-dot")
