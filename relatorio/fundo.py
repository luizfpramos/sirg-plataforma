"""Ajustes no fundo de uma página (2.24): apagar uma área e manter o texto do PDF no fundo.

O fundo importado é a imagem da página sem nenhum texto. Dois ajustes mexem nele, sempre numa cópia (a imagem
original não muda, e cada ajuste pode ser desfeito):

  apagar  — cobre a área com a cor do fundo em volta dela (traço de grifo, sublinhado de link, logo antigo);
  manter  — põe de volta na área a página original, com o texto (organogramas, cadeias de valor, rótulos de
            figuras): o texto fica no fundo, como imagem, e sai da lista de "texto do PDF" do editor.

Os ajustes ficam em `Pagina.ajustes_fundo`, uma lista de {"tipo", "x", "y", "w", "h"} em pontos, aplicada na ordem.
A imagem pronta fica em MEDIA_ROOT/fundos/<pk da página>-<assinatura>.jpg; a assinatura muda quando o fundo ou os
ajustes mudam, então a imagem antiga nunca fica no cache do navegador.
"""
import hashlib
import json
import re
from pathlib import Path

from django.conf import settings

APAGAR, MANTER = "apagar", "manter"
TIPOS = {APAGAR: "Apagar do fundo", MANTER: "Texto do PDF no fundo"}
MAXIMO = 60           # ajustes por página
MINIMO = 2            # menor lado de uma área, em pontos
NOME = re.compile(r"^(\d+)-([0-9a-f]{12})\.jpg$")


class Invalido(Exception):
    pass


def normalizar(lista, largura, altura):
    """Confere e arredonda a lista de ajustes. Áreas que passam da página são cortadas na borda."""
    if lista in (None, ""):
        return []
    if not isinstance(lista, list):
        raise Invalido("Lista de ajustes do fundo inválida.")
    if len(lista) > MAXIMO:
        raise Invalido(f"No máximo {MAXIMO} ajustes de fundo por página.")
    out = []
    for a in lista:
        if not isinstance(a, dict) or a.get("tipo") not in TIPOS:
            raise Invalido("Tipo de ajuste do fundo inválido.")
        try:
            x, y, w, h = (float(a.get(k)) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError):
            raise Invalido("Posição do ajuste do fundo inválida.")
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(largura), x + w), min(float(altura), y + h)
        if x1 - x0 < MINIMO or y1 - y0 < MINIMO:
            raise Invalido("A área do ajuste do fundo é pequena demais ou fica fora da página.")
        out.append({"tipo": a["tipo"], "x": round(x0, 1), "y": round(y0, 1), "w": round(x1 - x0, 1),
                    "h": round(y1 - y0, 1)})
    return out


def dentro_de_mantida(caixa, ajustes):
    """True se o centro da caixa (x, y, w, h) cai numa área "manter" (o texto dela já está no fundo)."""
    cx, cy = caixa["x"] + caixa["w"] / 2, caixa["y"] + caixa["h"] / 2
    return any(a["tipo"] == MANTER and a["x"] <= cx <= a["x"] + a["w"] and a["y"] <= cy <= a["y"] + a["h"]
               for a in ajustes or [])


# --- o PDF de onde veio o fundo --------------------------------------------------------------------------------
def pdf_original(pagina):
    """(caminho do PDF, número da página no PDF) de onde saiu o fundo, ou None se não houver PDF."""
    from .paginas import FUNDO_IMPORTADO
    fundo = pagina.fundo or ""
    m = FUNDO_IMPORTADO.match(fundo)
    if m:
        arq = Path(settings.MEDIA_ROOT) / "importacoes" / m.group(1) / "original.pdf"
        n = int(re.search(r"\d+", m.group(2)).group(0))
    else:
        m = re.match(r"^rg2025/p(\d{3,4})\.jpg$", fundo)
        if not m:
            return None
        arq = Path(settings.BASE_DIR) / "static" / "referencia" / "RG2025.pdf"
        n = int(m.group(1))
    return (arq, n) if arq.is_file() else None


# --- a imagem pronta --------------------------------------------------------------------------------------------
def assinatura(pagina):
    base = json.dumps([pagina.fundo, pagina.largura, pagina.altura, pagina.ajustes_fundo or []], sort_keys=True)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def pasta():
    return Path(settings.MEDIA_ROOT) / "fundos"


def caminho(pagina):
    return pasta() / f"{pagina.pk}-{assinatura(pagina)}.jpg"


def _cor_em_volta(im, caixa):
    """A cor mais comum logo do lado de fora da área (a cor do papel ou do quadro em que ela está)."""
    x0, y0, x1, y1 = caixa
    W, H = im.size
    pontos = []
    for i in range(0, 21):
        x = x0 + (x1 - x0) * i / 20
        y = y0 + (y1 - y0) * i / 20
        for px, py in ((x, y0 - 2), (x, y1 + 1), (x0 - 2, y), (x1 + 1, y)):
            if 0 <= px < W and 0 <= py < H:
                pontos.append(im.getpixel((int(px), int(py))))
    if not pontos:
        return (255, 255, 255)
    conta = {}
    for p in pontos:
        k = tuple(v // 8 for v in p)          # cores quase iguais contam juntas (o JPEG varia um pouco)
        conta.setdefault(k, []).append(p)
    grupo = max(conta.values(), key=len)
    return tuple(sorted(c[i] for c in grupo)[len(grupo) // 2] for i in range(3))


def _pagina_com_texto(pagina, tamanho):
    """A página original do PDF, com o texto, do mesmo tamanho (em pixels) da imagem de fundo."""
    origem = pdf_original(pagina)
    if origem is None:
        raise Invalido("Não achei o PDF de onde veio esta página; não dá para manter o texto no fundo.")
    import pypdfium2 as pdfium
    arq, n = origem
    doc = pdfium.PdfDocument(str(arq))
    try:
        if not 1 <= n <= len(doc):
            raise Invalido("A página não existe mais no PDF importado.")
        pg = doc[n - 1]
        escala = tamanho[0] / pg.get_width()
        im = pg.render(scale=escala).to_pil().convert("RGB")
        pg.close()
    finally:
        doc.close()
    if im.size != tamanho:
        im = im.resize(tamanho)
    return im


def aplicar(pagina, base):
    """A imagem `base` (PIL, RGB) com os ajustes da página aplicados, na ordem."""
    im = base.copy()
    k = im.size[0] / float(pagina.largura)
    original = None
    for a in pagina.ajustes_fundo or []:
        caixa = (round(a["x"] * k), round(a["y"] * k), round((a["x"] + a["w"]) * k), round((a["y"] + a["h"]) * k))
        if a["tipo"] == APAGAR:
            im.paste(_cor_em_volta(base, caixa), caixa)
        else:
            if original is None:
                original = _pagina_com_texto(pagina, im.size)
            im.paste(original.crop(caixa), caixa[:2])
    return im


def gerar(pagina):
    """Grava a imagem com os ajustes (se ainda não existe) e devolve o caminho. Apaga as versões antigas."""
    from PIL import Image
    from .paginas import caminho_do_fundo
    destino = caminho(pagina)
    if destino.is_file():
        return destino
    base = Image.open(caminho_do_fundo(pagina.fundo)).convert("RGB")
    im = aplicar(pagina, base)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    im.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(destino)
    for velha in destino.parent.glob(f"{pagina.pk}-*.jpg"):
        if velha != destino:
            try:
                velha.unlink()
            except OSError:  # pragma: no cover - arquivo aberto no Windows
                pass
    return destino
