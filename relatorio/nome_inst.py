"""
Menções ao nome antigo da instituição nos textos (CEFET-MG → UFCIMG).

O texto do relatório anterior fala do CEFET-MG. Algumas menções são da instituição hoje (passam a UFCIMG),
outras são fatos históricos (ficam como estão). Quem escreve decide: cada menção fica em amarelo,
<mark class="nome-inst" data-antes="do CEFET-MG" data-depois="da UFCIMG">do CEFET-MG</mark>,
e no Escrever um selo pergunta “CEFET-MG ou UFCIMG?”. A escolha troca a marca pelo texto escolhido.

Entram: “CEFET-MG” (e variações: CEFET MG, CEFET/MG, Cefet-MG, CEFET sozinho) e
“Centro Federal de Educação Tecnológica de Minas Gerais” (em maiúsculas ou não), com o artigo que vem
antes (do CEFET-MG → da UFCIMG). Ficam de fora: endereços e e-mails (cefetmg.br), “CEFETs” (a rede),
CEFET de outros estados (CEFET-RJ) e o que está dentro de links, números vivos ou outras marcas.
"""
import re
from html import escape, unescape

NOME_ANTIGO = "Centro Federal de Educação Tecnológica de Minas Gerais"
NOME_NOVO = "Universidade Federal de Ciência e Inovação de Minas Gerais"
SIGLA_NOVA = "UFCIMG"

_ARTIGOS = {"o": "a", "do": "da", "no": "na", "ao": "à", "pelo": "pela", "deste": "desta", "neste": "nesta",
            "desse": "dessa", "nesse": "nessa", "este": "esta", "esse": "essa"}
_ART = r"(?:(?P<art>\b(?:" + "|".join(sorted(_ARTIGOS, key=len, reverse=True)) + r"))(?P<esp>\s+))?"
_NOME = r"(?P<nome>Centro\s+Federal\s+de\s+Educa[çc][ãa]o\s+Tecnol[óo]gica\s+de\s+Minas\s+Gerais)"
_SIGLA = r"(?P<sigla>\bCEFET(?:\s*[-–/]\s*-?\s*MG\b|\s+MG\b|\b(?!\s*[-–/]\s*[A-Za-z])))"
_TRACO = r"(?P<traco>\s*[–—-]\s*)"
MENCAO = re.compile(_ART + r"(?:" + _NOME + r"(?:" + _TRACO + r"(?P<sigla2>CEFET\s*[-–/]?\s*MG\b))?|" + _SIGLA + r")",
                    re.IGNORECASE)
MARCA = re.compile(r'<mark class="nome-inst"')


def _caixa(modelo, texto):
    if modelo.isupper() and len(modelo) > 1:
        return texto.upper()
    if modelo[:1].isupper():
        return texto[:1].upper() + texto[1:]
    return texto


def _depois(m):
    art, esp = m.group("art"), m.group("esp") or ""
    if m.group("nome"):
        novo = NOME_NOVO.upper() if m.group("nome").isupper() else NOME_NOVO
        if m.group("sigla2"):
            novo += m.group("traco") + SIGLA_NOVA
    else:
        novo = SIGLA_NOVA
    if art:
        art = _caixa(art, _ARTIGOS[art.lower()])
    return f"{art or ''}{esp}{novo}"


def _no_texto(seg):
    n = 0

    def troca(m):
        nonlocal n
        n += 1
        antes = m.group(0)
        depois = _depois(m)
        return (f'<mark class="nome-inst" data-antes="{escape(unescape(antes), quote=True)}" '
                f'data-depois="{escape(depois, quote=True)}">{antes}</mark>')
    return MENCAO.sub(troca, seg), n


# trechos que não se mexem: links, números vivos, marcas e qualquer tag
_PROTEGIDO = re.compile(r"<a\b.*?</a>|<mark class=\"nome-inst\".*?</mark>|<span\b[^>]*class=\"sirg-num\".*?</span>|<[^>]+>", re.S)


def marcar(html):
    """(html com as menções marcadas, quantas). Pode rodar de novo: o que já está marcado não muda."""
    saida, pos, total = [], 0, 0
    html = html or ""
    for m in _PROTEGIDO.finditer(html):
        txt, n = _no_texto(html[pos:m.start()])
        saida += [txt, m.group(0)]
        total += n
        pos = m.end()
    txt, n = _no_texto(html[pos:])
    saida.append(txt)
    return "".join(saida), total + n


def contar(html):
    """Menções ao nome antigo ainda sem decisão (CEFET-MG ou UFCIMG)."""
    return len(MARCA.findall(html or ""))
