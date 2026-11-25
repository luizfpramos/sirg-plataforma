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


@register.inclusion_tag("relatorio/_passo_montagem.html", takes_context=True)
def passo_montagem(context, ciclo, n, compacto=False, senao_url="", senao_texto=""):
    """Barra no alto das telas da montagem: volta à montagem, "Passo N de 8", passo anterior e próximo.
    Quem não monta o relatório (ex.: Editor-chefe nos atributos) vê só o link `senao_url`, se houver."""
    from relatorio import permissoes as RP
    from relatorio.montagem import navegacao
    req = context.get("request")
    if not (req and RP.pode_estruturar(req.user)):
        return {"so_voltar": True, "compacto": compacto, "senao_url": senao_url, "senao_texto": senao_texto}
    return dict(navegacao(ciclo, n), compacto=compacto)
