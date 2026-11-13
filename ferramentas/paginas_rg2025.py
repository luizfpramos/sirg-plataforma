"""Gera, a partir do PDF do RG 2025, as páginas do relatório no formato da plataforma (não roda no servidor).

Para cada página:
  - static/rg2025/pNNN.jpg: o fundo da página (formas, cores, fotos), sem nenhum texto;
  - em relatorio/dados_iniciais/paginas_rg2025.json: cada caixa de texto, na mesma posição, com a mesma fonte,
    tamanho e cor, como HTML (que a plataforma deixa editar), e as áreas dos gráficos e tabelas.

Uso (precisa de pdfminer.six, pypdf e pdftoppm, do poppler):
    python3 ferramentas/paginas_rg2025.py static/referencia/RG2025.pdf
"""
import json
import re
import statistics as st
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTAnno, LTChar, LTCurve, LTFigure, LTImage, LTLine, LTRect, LTTextBox, LTTextLine
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream

BASE = Path(__file__).resolve().parent.parent
FAMILIAS = {
    "c": "Calibri,Carlito,sans-serif",
    "a": "Arial,'Liberation Sans',sans-serif",
    "n": "'Trade Gothic LT Std','Arial Narrow',Carlito,sans-serif",
    "s": "'Minion Pro',Georgia,serif",
    "m": "'Myriad Pro',Calibri,Carlito,sans-serif",
    "y": "Symbol,serif",
}
# quanto o alto da caixa de texto do CSS fica acima do alto da letra medido no PDF (em tamanhos de fonte)
AJUSTE_TOPO = {"c": 0.0, "a": 0.117, "n": 0.05, "s": 0.05, "m": 0.0, "y": 0.0}


# --- fundo sem texto ---------------------------------------------------------------------------------------
def _sem_bt(cs):
    """Tira só os operadores que desenham texto (Tj, TJ, ', "). O resto fica, inclusive cores definidas dentro de
    um bloco de texto, que continuam valendo para as formas desenhadas depois."""
    cs.operations = [(o, op) for o, op in cs.operations if op not in (b"Tj", b"TJ", b"'", b'"')]
    return cs


def pdf_sem_texto(origem, destino):
    r = PdfReader(origem)
    w = PdfWriter()
    vistos = set()

    def formas(res):
        if not res:
            return
        xo = res.get_object().get("/XObject")
        if not xo:
            return
        for _, ref in xo.get_object().items():
            o = ref.get_object()
            if o.get("/Subtype") != "/Form":
                continue
            k = getattr(ref, "idnum", id(o))
            if k in vistos:
                continue
            vistos.add(k)
            o.set_data(_sem_bt(ContentStream(o, r)).get_data())
            formas(o.get("/Resources"))

    for p in r.pages:
        if p.get_contents() is not None:
            p.replace_contents(_sem_bt(ContentStream(p.get_contents(), r)))
        formas(p.get("/Resources"))
        w.add_page(p)
    w.write(destino)


# --- texto ---------------------------------------------------------------------------------------------------
def cor(c):
    if c is None:
        return "#000000"
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        c = tuple(float(x) for x in c)
    except (TypeError, ValueError):
        return "#000000"
    if len(c) == 1:
        r = g = b = c[0]
    elif len(c) == 3:
        r, g, b = c
    elif len(c) == 4:
        C, M, Y, K = c
        r, g, b = (1 - C) * (1 - K), (1 - M) * (1 - K), (1 - Y) * (1 - K)
    else:
        r = g = b = 0
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))


def fonte(nome):
    n = nome.split("+")[-1]
    peso = 700 if re.search(r"Bold|Black|Bd", n) else (300 if "Light" in n else 400)
    it = bool(re.search(r"Italic|Obl", n))
    if "Calibri" in n:
        fam = "c"
    elif "Arial" in n:
        fam = "a"
    elif "TradeGothic" in n:
        fam = "n"
    elif "Minion" in n:
        fam = "s"
    elif "Symbol" in n:
        fam = "y"
    else:
        fam = "m"
    return fam, peso, it


def _linhas(obj, saida):
    if isinstance(obj, LTTextLine):
        saida.append(obj)
    elif hasattr(obj, "__iter__") and not isinstance(obj, LTChar):
        for x in obj:
            _linhas(x, saida)


def _runs(ln, H):
    runs = []
    for ch in ln:
        if isinstance(ch, LTAnno):
            t = ch.get_text()
            if t != "\n" and runs:
                runs[-1]["t"] += t
            continue
        if not isinstance(ch, LTChar):
            continue
        fam, peso, it = fonte(ch.fontname)
        s = (fam, peso, it, round(ch.size * 2) / 2, cor(ch.graphicstate.ncolor))
        topo = H - ch.y1
        base = H - ch.y0
        visivel = bool(ch.get_text().strip())
        if runs and runs[-1]["s"] == s and abs(runs[-1]["base"] - base) < 1.2:
            r = runs[-1]
            r["t"] += ch.get_text()
            if visivel:
                r["x1"] = ch.x1
                r["x0"] = ch.x0 if r["x0"] is None else r["x0"]
                r["topo"] = min(r["topo"], topo)
        else:
            runs.append({"s": s, "t": ch.get_text(), "x0": ch.x0 if visivel else None,
                         "x1": ch.x1 if visivel else None, "topo": topo if visivel else 9e9, "base": base})
    return runs


def caixas_da_pagina(lt, H):
    caixas = []
    for el in lt:
        if not isinstance(el, (LTTextBox, LTFigure)):
            continue
        ls = []
        _linhas(el, ls)
        linhas = []
        for ln in ls:
            runs = _runs(ln, H)
            texto = "".join(r["t"] for r in runs)
            if not texto.strip():
                continue
            xs0 = [r["x0"] for r in runs if r["x0"] is not None]
            xs1 = [r["x1"] for r in runs if r["x1"] is not None]
            linhas.append({"x0": min(xs0), "x1": max(xs1), "topo": H - ln.y1, "fim": H - ln.y0, "runs": runs})
        if linhas:
            linhas.sort(key=lambda l: (round(l["topo"]), l["x0"]))
            caixas.append(linhas)
    return caixas


def _estilo_principal(linhas):
    conta = {}
    for l in linhas:
        for r in l["runs"]:
            conta[r["s"]] = conta.get(r["s"], 0) + len(r["t"].strip())
    return max(conta, key=conta.get)


def _css(s, base=None):
    fam, peso, it, tam, c = s
    partes = []
    if base is None or fam != base[0]:
        partes.append(f"font-family:{FAMILIAS[fam]}")
    if base is None or tam != base[3]:
        partes.append(f"font-size:{tam:g}px")
    if base is None or peso != base[1]:
        partes.append(f"font-weight:{peso}")
    if base is None or it != base[2]:
        partes.append(f"font-style:{'italic' if it else 'normal'}")
    if base is None or c != base[4]:
        partes.append(f"color:{c}")
    return ";".join(partes)


def _html_runs(l, base, sup_lim):
    out = []
    linha_base = max((r["base"] for r in l["runs"] if r["s"][3] >= base[3] * 0.85), default=None)
    for r in l["runs"]:
        t = escape(r["t"], quote=False)
        if not t:
            continue
        sup = r["s"][3] < sup_lim and linha_base is not None and linha_base - r["base"] > base[3] * 0.15
        if sup and t.strip() in ("o", "a", "º", "ª", "°"):
            out.append("º" if t.strip() in ("o", "º", "°") else "ª")     # nº, 1ª: o "o" pequeno do PDF
            continue
        if sup:
            out.append(f"<sup>{t.strip()}</sup>")
            continue
        if r["s"] == base:
            out.append(t)
            continue
        d = [x for x in range(5) if r["s"][x] != base[x]]
        if d == [1] and r["s"][1] >= 600 and base[1] < 600:
            out.append(f"<strong>{t}</strong>")
        elif d == [2] and r["s"][2]:
            out.append(f"<em>{t}</em>")
        else:
            out.append(f'<span style="{_css(r["s"], base)}">{t}</span>')
    # junta trechos vizinhos com o mesmo estilo
    h = "".join(out)
    h = re.sub(r"</strong><strong>", "", h)
    h = re.sub(r"</em><em>", "", h)
    return h


# --- larguras (Carlito e Liberation Sans têm as mesmas larguras de Calibri e Arial) ---------------------------
_FONTES = {}
ARQ_FONTES = {
    ("c", False, False): "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    ("c", True, False): "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
    ("c", False, True): "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf",
    ("c", True, True): "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf",
    ("a", False, False): "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ("a", True, False): "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ("a", False, True): "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
    ("a", True, True): "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
}


def _metricas(fam, negrito, italico):
    k = (fam if fam in ("c", "a") else "c", negrito, italico)
    if k not in _FONTES:
        from fontTools.ttLib import TTFont
        f = TTFont(ARQ_FONTES[k])
        _FONTES[k] = (f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm)
    return _FONTES[k]


def largura(texto, s):
    """Largura do texto (em pt) no estilo s = (família, peso, itálico, tamanho, cor), sem kerning."""
    cmap, hmtx, upm = _metricas(s[0], s[1] >= 600, s[2])
    total = 0
    for ch in texto:
        g = cmap.get(ord(ch)) or cmap.get(0x20)
        total += hmtx[g][0] if g in hmtx else upm / 2
    return total * s[3] / upm


def _pedacos(l, base, sup_lim):
    """[(texto, estilo)] de uma linha, com os sobrescritos no tamanho em que aparecem na tela."""
    out = []
    for r in l["runs"]:
        s = r["s"]
        if s[3] < sup_lim:
            s = (s[0], s[1], s[2], round(base[3] * 0.6, 2), s[4])
        out.append((re.sub(r"\s+", " ", r["t"]), s))
    return out


def _nat(pedacos):
    return sum(largura(t, s) for t, s in pedacos)


def espacamento(p, base, R, sup_lim):
    """Espaço extra entre palavras (word-spacing, em pt, quase sempre negativo) para o navegador quebrar as linhas
    do parágrafo justificado onde o PDF quebrou. None se não der para garantir."""
    esp = largura(" ", base)
    sup, inf = 99.0, -99.0
    for i, l in enumerate(p):
        W = R - l["x0"]
        ped = _pedacos(l, base, sup_lim)
        texto = "".join(t for t, _ in ped).strip()
        hifen = texto.endswith("-") and i < len(p) - 1
        n_esp = texto.count(" ")
        nat = _nat(ped) - (len("".join(t for t, _ in ped)) - len("".join(t for t, _ in ped).lstrip())) * esp \
            - (len("".join(t for t, _ in ped)) - len("".join(t for t, _ in ped).rstrip())) * esp
        if i < len(p) - 1 or n_esp:
            if n_esp:
                sup = min(sup, (W - 0.4 - nat) / n_esp)
            elif nat > W + 0.5:
                return None
        if i < len(p) - 1 and not hifen:
            prox = "".join(t for t, _ in _pedacos(p[i + 1], base, sup_lim)).strip()
            m = re.match(r"[^\s\-–/]+[\-–]?", prox)
            if m:
                w_prox = largura(m.group(0), base)
                inf = max(inf, (W - nat - esp - w_prox) / (n_esp + 1))
    if sup == 99.0:
        return 0.0
    ws = min(sup, 0.0) if inf < min(sup, 0.0) else sup
    if inf >= sup:
        ws = sup
    return round(max(ws, -esp * 0.7), 3)


BALA = re.compile(r"^\s*[•▪■●◦\-–]\s")


def caixa_html(linhas):
    """Uma caixa de texto do PDF -> posição, estilo e HTML (parágrafos)."""
    base = _estilo_principal(linhas)
    S = base[3]
    X = min(l["x0"] for l in linhas)
    R = max(l["x1"] for l in linhas)
    W = R - X
    topos = [l["topo"] for l in linhas]
    passos = [b["topo"] - a["topo"] for a, b in zip(linhas, linhas[1:]) if 0.6 * S < b["topo"] - a["topo"] < 1.9 * S]
    L = round(st.median(passos), 2) if passos else round(S * 1.22, 2)
    cheias = [l for l in linhas[:-1] if l["x1"] >= R - 2.5]
    esticadas = [l for l in cheias if _nat(_pedacos(l, base, S * 0.8)) < (l["x1"] - l["x0"]) - 2.5]
    justificada = base[0] in ("c", "a") and len(linhas) >= 2 and len(cheias) >= max(1, 0.5 * (len(linhas) - 1)) and \
        (len(linhas) >= 3 or esticadas)
    centros = [(l["x0"] + l["x1"]) / 2 for l in linhas]
    if justificada:
        alinha = "justify"
    elif len(linhas) > 1 and max(centros) - min(centros) < 3 and max(l["x0"] for l in linhas) - X > 3:
        alinha = "center"
    elif len(linhas) > 1 and max(l["x1"] for l in linhas) - min(l["x1"] for l in linhas) < 2 and \
            max(l["x0"] for l in linhas) - X > 3:
        alinha = "right"
    else:
        alinha = "left"
    # parágrafos
    paras, atual = [], [linhas[0]]
    for a, b in zip(linhas, linhas[1:]):
        novo = (b["topo"] - a["topo"] > L * 1.45) or BALA.match("".join(r["t"] for r in b["runs"])) or \
            (justificada and a["x1"] < R - 12)
        if novo:
            paras.append(atual)
            atual = [b]
        else:
            atual.append(b)
    paras.append(atual)
    sup_lim = S * 0.8
    adj = AJUSTE_TOPO.get(base[0], 0)
    if alinha != "justify":
        return _caixa_por_linhas(linhas, base, X, R, alinha, adj)
    html = []
    anterior = None
    for p in paras:
        estilo = []
        if anterior is not None:
            mt = p[0]["topo"] - anterior[-1]["topo"] - L
            if mt > 0.5:
                estilo.append(f"margin-top:{mt:.1f}px")
        x_outras = min((l["x0"] for l in p[1:]), default=p[0]["x0"])
        pad = x_outras - X
        ind = p[0]["x0"] - x_outras
        if pad > 0.8:
            estilo.append(f"padding-left:{pad:.1f}px")
        if abs(ind) > 0.8:
            estilo.append(f"text-indent:{ind:.1f}px")
        if alinha == "justify" and len(p) > 1:
            ws = espacamento(p, base, R, sup_lim)
            if ws:
                estilo.append(f"word-spacing:{ws:g}px")
        partes = []
        for i, l in enumerate(p):
            h = _html_runs(l, base, sup_lim)
            if i < len(p) - 1:
                h = h.rstrip()
                if alinha == "justify":
                    if re.search(r"[a-zà-ú]-$", h) and re.match(r"\s*[a-zà-ú]", "".join(r["t"] for r in p[i + 1]["runs"])):
                        h = h[:-1] + "­"
                    else:
                        h += " "
                else:
                    h += "<br>"
            partes.append(h)
        texto = re.sub(r"[ \t]{2,}", " ", "".join(partes)).strip()
        attr = f' style="{";".join(estilo)}"' if estilo else ""
        html.append(f"<p{attr}>{texto}</p>")
        anterior = p
    # alto da caixa: a primeira linha começa onde começa a letra no PDF
    l0 = linhas[0]
    topo_letra = min((r["topo"] for r in l0["runs"] if r["s"][3] >= S * 0.85), default=l0["topo"])
    y = topo_letra - (L - S) / 2 - AJUSTE_TOPO.get(base[0], 0) * S
    alto = linhas[-1]["fim"] - y
    css = (f"font-family:{FAMILIAS[base[0]]};font-size:{S:g}px;font-weight:{base[1]};"
           f"font-style:{'italic' if base[2] else 'normal'};color:{base[4]};line-height:{L:.2f}px;text-align:{alinha}")
    texto_puro = " ".join("".join(r["t"] for r in l["runs"]).strip() for l in linhas)
    return {"x": round(X, 1), "y": round(y, 1), "w": round(W + (0 if alinha == "justify" else 3), 1),
            "h": round(alto, 1), "css": css, "html": "".join(html), "texto": texto_puro,
            "linhas": len(linhas), "fam": base[0], "tam": S,
            "quebra": alinha != "justify" and len(linhas) > 1}


def _estilo_da_linha(l):
    conta = {}
    for r in l["runs"]:
        conta[r["s"]] = conta.get(r["s"], 0) + len(r["t"].strip())
    return max(conta, key=conta.get)


def _caixa_por_linhas(linhas, base, X, R, alinha, adj):
    """Caixa sem justificação (títulos, rótulos, números de destaque): cada linha do PDF é um parágrafo,
    na altura exata em que está no PDF."""
    html, topo_ant, y0 = [], None, None
    for l in linhas:
        ls = _estilo_da_linha(l)
        maior = max(l["runs"], key=lambda r: r["s"][3] if r["t"].strip() else 0)["s"]
        Si = maior[3]
        Lh = round(Si * 1.2, 2)
        topo_letra = min((r["topo"] for r in l["runs"] if r["s"][3] >= Si * 0.95), default=l["topo"])
        topo = topo_letra - (Lh - Si) / 2 - AJUSTE_TOPO.get(maior[0], 0) * Si
        estilo = []
        dif = _css(ls, base)
        if dif:
            estilo.append(dif)
        estilo.append(f"line-height:{Lh:g}px")
        if y0 is None:
            y0 = topo
        else:
            estilo.append(f"margin-top:{topo - topo_ant:.1f}px")
        if alinha == "left" and l["x0"] - X > 0.8:
            estilo.append(f"padding-left:{l['x0'] - X:.1f}px")
        ped = _pedacos(l, ls, Si * 0.8)
        nat = _nat([(t.strip() if i in (0, len(ped) - 1) else t, st_) for i, (t, st_) in enumerate(ped)])
        real = l["x1"] - l["x0"]
        n = len("".join(t for t, _ in ped).strip())
        um_estilo = len({r["s"] for r in l["runs"] if r["t"].strip()}) == 1
        if um_estilo and ls[0] in ("c", "a") and nat and n > 3 and abs(real - nat) > 1.2 and 0.8 < real / nat < 1.25:
            estilo.append(f"letter-spacing:{(real - nat) / n:.3f}px")
        corpo = _html_runs(l, ls, ls[3] * 0.8)
        corpo = re.sub(r"[ \t]{2,}", " ", corpo).strip()
        html.append(f'<p style="{";".join(estilo)}">{corpo}</p>')
        topo_ant = topo + Lh
    alto = linhas[-1]["fim"] - y0
    css = (f"font-family:{FAMILIAS[base[0]]};font-size:{base[3]:g}px;font-weight:{base[1]};"
           f"font-style:{'italic' if base[2] else 'normal'};color:{base[4]};line-height:1.2;text-align:{alinha}")
    texto_puro = " ".join("".join(r["t"] for r in l["runs"]).strip() for l in linhas)
    return {"x": round(X, 1), "y": round(y0, 1), "w": round(R - X + (0 if alinha == "center" else 3), 1), "h": round(alto, 1), "css": css,
            "html": "".join(html), "texto": texto_puro, "linhas": len(linhas), "fam": base[0], "tam": base[3],
            "quebra": True}


def graficos_da_pagina(lt, H):
    """Formas desenhadas (retângulos, curvas, linhas, imagens), para achar a área de gráficos e tabelas."""
    out = []

    def anda(o):
        for x in o:
            if isinstance(x, (LTRect, LTCurve, LTLine, LTImage)):
                out.append([round(x.x0, 1), round(H - x.y1, 1), round(x.x1, 1), round(H - x.y0, 1),
                            type(x).__name__[2:3]])
            elif isinstance(x, LTFigure):
                anda(x)
    anda(lt)
    return out


def extrair(pdf, so=None):
    lp = LAParams(line_margin=0.55, char_margin=2.5, word_margin=0.12, boxes_flow=None)
    paginas = []
    for n, lt in enumerate(extract_pages(pdf, laparams=lp), start=1):
        if so and n not in so:
            continue
        H = lt.height
        caixas = [caixa_html(c) for c in caixas_da_pagina(lt, H)]
        paginas.append({"n": n, "w": round(lt.width, 2), "h": round(H, 2), "caixas": caixas,
                        "formas": graficos_da_pagina(lt, H)})
        print(f"página {n}: {len(caixas)} caixas", file=sys.stderr)
    return paginas


def fundos(pdf, destino, so=None, dpi=144):
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        sem = Path(tmp) / "sem.pdf"
        pdf_sem_texto(pdf, sem)
        args = ["pdftoppm", "-r", str(dpi), "-jpeg", "-jpegopt", "quality=80,progressive=y"]
        if so:
            for n in so:
                subprocess.run(args + ["-f", str(n), "-l", str(n), str(sem), str(Path(tmp) / "p")], check=True)
        else:
            subprocess.run(args + [str(sem), str(Path(tmp) / "p")], check=True)
        for f in Path(tmp).glob("p-*.jpg"):
            n = int(f.stem.split("-")[1])
            f.replace(destino / f"p{n:03d}.jpg")


if __name__ == "__main__":
    pdf = sys.argv[1]
    so = {int(x) for x in sys.argv[2].split(",")} if len(sys.argv) > 2 else None
    fundos(pdf, BASE / "static" / "rg2025", so)
    dados = extrair(pdf, so)
    saida = BASE / "relatorio" / "dados_iniciais" / ("paginas_rg2025.json" if not so else "paginas_amostra.json")
    saida.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    print(f"{len(dados)} página(s) em {saida}", file=sys.stderr)
