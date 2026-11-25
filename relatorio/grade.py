"""Grade de diagramação das páginas: a grade geral do ciclo (margens, colunas e medianiz) e as guias de cada página.

Tudo em pontos, a mesma medida das caixas dos blocos. A grade e as guias só orientam o editor de páginas: o bloco
encaixa nelas ao ser desenhado, movido ou redimensionado, e a tela aponta os blocos que estão fora delas. Nada aqui
move um bloco que já existe.
"""
import re

TOLERANCIA = 1.0        # pontos: borda a até 1 pt de uma linha conta como alinhada
MAX_COLUNAS = 12
MAX_GUIAS = 40          # por direção, em cada página
CAMPOS = ("margem_sup", "margem_inf", "margem_esq", "margem_dir", "colunas", "medianiz")


class Invalido(ValueError):
    pass


def _pt(v, nome, maximo):
    try:
        n = round(float(str(v).replace(",", ".")), 1)
    except (TypeError, ValueError):
        raise Invalido(f"Valor inválido para {nome}.")
    if n < 0 or n > maximo:
        raise Invalido(f"{nome.capitalize()} precisa ficar entre 0 e {maximo:g} pt.")
    return n


def normalizar_grade(d, largura=935.4, altura=566.9):
    """Grade conferida, ou {} se `d` vier vazio. Recusa margens que não deixam espaço para as colunas."""
    if not d or not any(str(d.get(k, "")).strip() for k in CAMPOS):
        return {}
    g = {
        "margem_sup": _pt(d.get("margem_sup") or 0, "margem superior", altura / 2),
        "margem_inf": _pt(d.get("margem_inf") or 0, "margem inferior", altura / 2),
        "margem_esq": _pt(d.get("margem_esq") or 0, "margem esquerda", largura / 2),
        "margem_dir": _pt(d.get("margem_dir") or 0, "margem direita", largura / 2),
        "medianiz": _pt(d.get("medianiz") or 0, "medianiz", 200),
    }
    try:
        bruto = str(d.get("colunas", "")).strip()
        g["colunas"] = int(bruto) if bruto else 1
    except (TypeError, ValueError):
        raise Invalido("O número de colunas precisa ser inteiro.")
    if not 1 <= g["colunas"] <= MAX_COLUNAS:
        raise Invalido(f"Use de 1 a {MAX_COLUNAS} colunas.")
    util = largura - g["margem_esq"] - g["margem_dir"] - g["medianiz"] * (g["colunas"] - 1)
    if util < g["colunas"] * 12:
        raise Invalido("As margens e a medianiz não deixam espaço para as colunas.")
    if altura - g["margem_sup"] - g["margem_inf"] < 12:
        raise Invalido("As margens de cima e de baixo não deixam espaço na página.")
    return g


def linhas_da_grade(grade, largura, altura):
    """Posições das linhas da grade numa página: {"v": [...], "h": [...], "colunas": [(x0, x1), ...]}."""
    if not grade:
        return {"v": [], "h": [], "colunas": []}
    e, d = grade["margem_esq"], largura - grade["margem_dir"]
    n, m = grade["colunas"], grade["medianiz"]
    larg = (d - e - m * (n - 1)) / n
    colunas = [(round(e + i * (larg + m), 1), round(e + i * (larg + m) + larg, 1)) for i in range(n)]
    v = sorted({x for c in colunas for x in c})
    h = [round(grade["margem_sup"], 1), round(altura - grade["margem_inf"], 1)]
    return {"v": v, "h": h, "colunas": colunas}


def normalizar_guias(d, largura, altura):
    """Guias da página conferidas: números dentro da página, sem repetição, em ordem."""
    d = d or {}
    out = {}
    for eixo, limite in (("v", largura), ("h", altura)):
        vals = set()
        for v in d.get(eixo) or []:
            try:
                n = round(float(v), 1)
            except (TypeError, ValueError):
                raise Invalido("Posição de guia inválida.")
            if 0 <= n <= limite:
                vals.add(n)
        if len(vals) > MAX_GUIAS:
            raise Invalido(f"No máximo {MAX_GUIAS} guias em cada direção por página.")
        out[eixo] = sorted(vals)
    return out


def guias(pagina):
    """Grade do ciclo e guias da página, prontas para a tela do editor."""
    g = pagina.ciclo.grade or {}
    return {"grade": g, "linhas": linhas_da_grade(g, pagina.largura, pagina.altura),
            "pagina": normalizar_guias(pagina.guias, pagina.largura, pagina.altura)}


def _perto(valor, lista):
    return any(abs(valor - x) <= TOLERANCIA for x in lista)


def fora_da_grade(caixa, dados):
    """True se o bloco não segue a grade nem as guias da página. Sem grade nem guias, nada fica fora.

    Na horizontal, as duas bordas (esquerda e direita) precisam estar numa linha da grade ou numa guia da página.
    Na vertical, o bloco precisa ficar dentro das margens, ou a borda que sai delas precisa estar numa guia da página.
    """
    linhas, pg = dados["linhas"], dados["pagina"]
    if not (linhas["v"] or pg["v"] or pg["h"]):
        return False
    x, y, w, h = (float(caixa.get(k, 0)) for k in ("x", "y", "w", "h"))
    verticais = linhas["v"] + pg["v"]
    if verticais and not (_perto(x, verticais) and _perto(x + w, verticais)):
        return True
    if linhas["h"]:
        topo, base = linhas["h"]
        if y < topo - TOLERANCIA and not _perto(y, pg["h"]):
            return True
        if y + h > base + TOLERANCIA and not _perto(y + h, pg["h"]):
            return True
    return False


def paginas_da_lista(texto, numeros):
    """Números de página a partir de "3, 5-8" ou "todas", só entre os que existem."""
    texto = (texto or "").strip().lower()
    existentes = set(numeros)
    if texto in ("todas", "todas as páginas", "*"):
        return sorted(existentes)
    escolhidas = set()
    for parte in re.split(r"[,;\s]+", texto):
        if not parte:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", parte)
        if not m:
            raise Invalido(f"Não entendi “{parte}”. Use números e intervalos, como 3, 5-8.")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > b:
            a, b = b, a
        escolhidas.update(n for n in range(a, b + 1) if n in existentes)
    return sorted(escolhidas)
