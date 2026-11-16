"""Padrão de design do texto do relatório: fonte, tamanho e espaçamentos (além das paletas dos gráficos).

Vale para o texto corrido na tela e para os blocos de texto novos feitos no editor de páginas. Os blocos que vieram
do PDF mantêm a fonte e o espaçamento do PDF. Tudo o que entra no CSS vem das listas abaixo (nunca de texto livre).
"""
from decimal import Decimal

FONTES = {
    "": ("Padrão do sistema (Calibri)", 'Calibri, Carlito, "Segoe UI", Arial, sans-serif'),
    "arial": ("Arial", "Arial, Helvetica, sans-serif"),
    "verdana": ("Verdana", "Verdana, Geneva, sans-serif"),
    "georgia": ("Georgia (com serifa)", 'Georgia, "Times New Roman", serif'),
    "times": ("Times New Roman (com serifa)", '"Times New Roman", Times, serif'),
    "segoe": ("Segoe UI", '"Segoe UI", Tahoma, sans-serif'),
}
TAMANHOS = (0, 12, 13, 14, 15, 16, 17, 18, 20)                    # px; 0 = padrão
LINHAS = (Decimal("0"), Decimal("1.25"), Decimal("1.4"), Decimal("1.55"), Decimal("1.75"), Decimal("2"))
PARAGRAFOS = (0, 4, 8, 12, 16, 24)                                # px; 0 = padrão


def familia(chave):
    return FONTES.get(chave or "", FONTES[""])[1]


def css_variaveis(inst):
    """Texto CSS (`:root{...}`) com o padrão escolhido, ou "" se tudo estiver no padrão."""
    if inst is None:
        return ""
    v = []
    if inst.fonte_texto in FONTES and inst.fonte_texto:
        v.append(f"--rg-fonte:{FONTES[inst.fonte_texto][1]}")
    if inst.tamanho_texto in TAMANHOS and inst.tamanho_texto:
        v.append(f"--rg-tamanho:{inst.tamanho_texto}px")
    if inst.espaco_linhas in LINHAS and inst.espaco_linhas:
        v.append(f"--rg-linhas:{inst.espaco_linhas}")
    if inst.espaco_paragrafos in PARAGRAFOS and inst.espaco_paragrafos:
        v.append(f"--rg-paragrafo:{inst.espaco_paragrafos}px")
    return ":root{" + ";".join(v) + "}" if v else ""


def ajustar_css_da_caixa(css, inst):
    """Troca fonte, tamanho e altura de linha de um `css` de caixa (do PDF) pelo padrão, no que estiver definido."""
    import re
    if inst is None:
        return css
    if inst.fonte_texto in FONTES and inst.fonte_texto:
        css = re.sub(r"font-family:[^;]*;?", "", css) + f";font-family:{FONTES[inst.fonte_texto][1].replace(chr(34), chr(39))}"
    tam = inst.tamanho_texto if inst.tamanho_texto in TAMANHOS else 0
    if tam:
        css = re.sub(r"font-size:[^;]*;?", "", css) + f";font-size:{tam}px"
        lin = inst.espaco_linhas if inst.espaco_linhas in LINHAS and inst.espaco_linhas else Decimal("1.25")
        css = re.sub(r"line-height:[^;]*;?", "", css) + f";line-height:{round(tam * lin, 1)}px"
    return css.strip(";")
