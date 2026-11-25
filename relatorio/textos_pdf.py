"""Texto do PDF diagramado no editor de páginas (2.21).

Desde a 2.21 quem decide os blocos é a pessoa: a importação cria só as páginas, e o editor mostra por cima do fundo
as caixas de texto que estavam no PDF (lidas na importação, em `paginas.json`). Clicar numa caixa, ou desenhar uma
área sobre várias, cria o bloco do tamanho certo; a pessoa escolhe se o texto fica fixo (como no PDF) ou se o bloco
é do setor (vazio, com o texto do PDF como referência do ano anterior).

  importacao_da_pagina(pg)   — a importação de onde veio o fundo da página
  caixas_da_pagina(pg)       — as caixas de texto do PDF da página (sem cabeçalho, rodapé e número de página)
  juntar_caixas(pg, indices) — o HTML das caixas escolhidas, na ordem de leitura, e a fonte da primeira
"""
from functools import lru_cache

from .html_seguro import limpar
from .models import ImportacaoPDF


def importacao_da_pagina(pagina):
    from .paginas import FUNDO_IMPORTADO
    m = FUNDO_IMPORTADO.match(pagina.fundo or "")
    if not m:
        return None
    return ImportacaoPDF.objects.filter(pk=int(m.group(1)), ciclo_id=pagina.ciclo_id).first()


@lru_cache(maxsize=8)
def _lidas(caminho, mtime):
    from . import importador as I
    import json
    from pathlib import Path
    paginas = json.loads(Path(caminho).read_text(encoding="utf-8"))
    e_fixo = I.textos_fixos(paginas)
    return {p["n"]: (p, e_fixo) for p in paginas}


def _pagina_lida(pagina):
    imp = importacao_da_pagina(pagina)
    if imp is None:
        return None, None
    arq = imp.pasta / "paginas.json"
    if not arq.exists():
        return None, None
    lidas = _lidas(str(arq), arq.stat().st_mtime)
    return lidas.get(pagina.numero, (None, None))


def caixas_da_pagina(pagina):
    """[{i, x, y, w, h, css, html, texto}] — `i` é a posição da caixa na página lida, usada para criar o bloco."""
    p, e_fixo = _pagina_lida(pagina)
    if not p:
        return []
    from .fundo import dentro_de_mantida
    ajustes = pagina.ajustes_fundo or []
    out = []
    for i, c in enumerate(p["caixas"]):
        if e_fixo(c, p["h"]):
            continue                                  # cabeçalho, rodapé e número da página já estão na página
        if dentro_de_mantida(c, ajustes):
            continue                                  # 2.24: o texto desta área ficou no fundo, como imagem
        out.append({"i": i, "x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"], "css": c["css"],
                    "html": limpar(c["html"]), "texto": c["texto"][:200], "quebra": c.get("quebra", False)})
    return out


def juntar_caixas(pagina, indices):
    """(html, css, quebra) das caixas `indices`, na ordem de leitura. Índice que não existe é ignorado."""
    from .paginas import _coluna
    disponiveis = {c["i"]: c for c in caixas_da_pagina(pagina)}
    escolhidas = [disponiveis[i] for i in dict.fromkeys(indices) if i in disponiveis]
    if not escolhidas:
        return "", "", False
    escolhidas.sort(key=lambda c: (_coluna(c, pagina.largura), c["y"], c["x"]))
    return "".join(c["html"] for c in escolhidas), escolhidas[0]["css"], escolhidas[0]["quebra"]


def coberta(caixa, blocos):
    """True se o centro da caixa do PDF cai dentro de algum bloco (serializado) da página."""
    cx, cy = caixa["x"] + caixa["w"] / 2, caixa["y"] + caixa["h"] / 2
    return any(b["x"] <= cx <= b["x"] + b["w"] and b["y"] <= cy <= b["y"] + b["h"] for b in blocos)
