"""Atributos do bloco de texto: setor responsável, conteúdo esperado, tamanho (mínimo e máximo de caracteres) e cor.

O setor do bloco, quando preenchido, vale no lugar dos setores da seção. A cor sai do setor, sozinha, para que a
pessoa reconheça de quem é cada trecho na página. Os limites de tamanho avisam, mas não impedem o salvamento."""
import re
from html import unescape

from . import revisao

NEUTRA = "#6c757d"          # bloco de vários setores (ou de nenhum): cinza
GRANDE_AREA, GRANDE_ALTURA, GRANDE_LARGURA = 12000, 48, 120   # caixa da página a partir da qual a orientação cabe dentro


def cor_do_setor(setor):
    """Cor estável do setor (o mesmo setor tem sempre a mesma cor, em qualquer ciclo)."""
    return f"hsl({(setor.pk * 137) % 360} 55% 42%)"


def setores_do_bloco(bloco, setores_da_secao=None):
    """Quem responde pelo bloco: o setor do próprio bloco ou, se não houver, os da seção."""
    if bloco.setor_id:
        return [bloco.setor]
    if setores_da_secao is not None:
        return list(setores_da_secao)
    return list(bloco.secao.setores.all())


def contar_caracteres(html):
    """Caracteres do texto como ficará se as alterações pendentes forem aceitas (espaços repetidos contam um)."""
    h = revisao.aplicar(html or "", None, aceitar=True)
    h = re.sub(r"</(p|li|h3|h4|blockquote|tr)>|<br\s*/?>", " ", h)
    t = unescape(re.sub(r"<[^>]+>", "", h))
    return len(re.sub(r"[\s ]+", " ", t).strip())


def situacao_do_tamanho(n, minimo, maximo):
    """("ok" | "pouco" | "muito", frase). Sem limites, sempre "ok"."""
    if minimo and n < minimo:
        return "pouco", f"{n} caracteres — faltam {minimo - n} para o mínimo de {minimo}"
    if maximo and n > maximo:
        return "muito", f"{n} caracteres — {n - maximo} acima do máximo de {maximo}"
    return "ok", f"{n} caracteres"


def frase_dos_limites(minimo, maximo):
    if minimo and maximo:
        return f"Entre {minimo} e {maximo} caracteres"
    if minimo:
        return f"No mínimo {minimo} caracteres"
    if maximo:
        return f"No máximo {maximo} caracteres"
    return ""


def e_grande(caixa):
    """A orientação cabe dentro da caixa vazia? Bloco fora de página (sem caixa) sempre cabe."""
    if not caixa:
        return True
    w, h = caixa.get("w") or 0, caixa.get("h") or 0
    return w >= GRANDE_LARGURA and h >= GRANDE_ALTURA and w * h >= GRANDE_AREA


LOREM = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et "
         "dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
         "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat "
         "nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit "
         "anim id est laborum. ")
_XXX = "xxxx xxx xxxxxx xx xxxxx xxxxxxx xxx xxxx xx xxxxxx xxxxx xxx "


def tamanho_do_enchimento(bloco, caixa=None):
    """Quantos caracteres o texto de enchimento ocupa: o máximo do bloco, o tamanho do texto do PDF ou a área."""
    if bloco.max_caracteres:
        return min(bloco.max_caracteres, 4000)
    ref = (bloco.config or {}).get("referencia_pdf")
    if ref:
        return min(max(contar_caracteres(ref), 12), 4000)
    if caixa and caixa.get("w") and caixa.get("h"):
        return int(min(max(caixa["w"] * caixa["h"] / 70, 12), 4000))
    return 300


def enchimento(modo, n):
    """Texto de enchimento (só na tela, em cinza) com cerca de n caracteres, cortado no fim de uma palavra."""
    base = LOREM if modo == "lorem" else _XXX
    t = (base * (n // len(base) + 1))[:n]
    return (t.rsplit(" ", 1)[0] if " " in t[-12:] else t).strip()


def anotar(bloco, setores_da_secao, caixa=None, modo="orientacao"):
    """Dicionário com tudo o que a tela mostra sobre os atributos do bloco. `modo`: como aparece o bloco vazio
    (Ciclo.exibicao_vazio): nada, a orientação, lorem ipsum ou "xxx" ocupando a área."""
    setores = setores_do_bloco(bloco, setores_da_secao)
    siglas = ", ".join(s.sigla for s in setores)
    limites = frase_dos_limites(bloco.min_caracteres, bloco.max_caracteres)
    dica = " · ".join(x for x in (siglas, bloco.descricao.strip(), limites) if x)
    return {
        "setores": setores, "siglas": siglas, "proprio": bool(bloco.setor_id),
        "cor": cor_do_setor(setores[0]) if len(setores) == 1 else NEUTRA,
        "descricao": bloco.descricao.strip(), "min": bloco.min_caracteres, "max": bloco.max_caracteres,
        "limites": limites, "dica": dica, "grande": e_grande(caixa),
        "guia": bool(bloco.descricao.strip() or limites),
        "modo": modo or "orientacao",
        "enchimento": enchimento(modo, tamanho_do_enchimento(bloco, caixa)) if modo in ("lorem", "xxx") else "",
        "referencia": bool((bloco.config or {}).get("referencia_pdf")),
        "fixo": bool((bloco.config or {}).get("fixo")),
    }
