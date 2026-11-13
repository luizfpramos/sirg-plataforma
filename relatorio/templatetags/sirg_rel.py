from django import template

register = template.Library()


@register.filter
def rotulo_coluna(indice, colunas):
    try:
        return colunas[indice]["rotulo"]
    except (IndexError, KeyError, TypeError):
        return ""


@register.filter
def situacao_cor(situacao):
    return {"preparacao": "secondary", "coleta": "primary", "revisao": "warning", "encerrado": "dark",
            "nao_iniciada": "light", "preenchimento": "info", "enviada": "primary", "aprovada": "success"}.get(
        situacao, "secondary")
