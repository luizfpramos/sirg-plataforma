"""
Limpeza do HTML dos textos do relatório (lista do que é permitido).

Tudo o que chega do editor passa por aqui antes de ser gravado: só ficam as marcações
de texto (parágrafos, negrito, listas, títulos, links) e os "números vivos"
(<span class="sirg-num" data-ref="quadro.linha">), sem estilos colados do Word,
scripts ou atributos de evento.
"""
import re
from html import escape
from html.parser import HTMLParser

PERMITIDAS = {"p", "br", "strong", "b", "em", "i", "u", "s", "h3", "h4", "ul", "ol", "li", "a", "blockquote",
              "sup", "sub", "span", "mark", "table", "thead", "tbody", "tr", "th", "td", "img", "ins", "del"}
# <img src="/ciclos/2026/imagens/12/" alt="...">: só imagens enviadas à própria plataforma
IMAGEM = re.compile(r"^/ciclos/\d{4}/imagens/\d+/$")
# <mark class="atualizar" data-orig="texto do relatório anterior">: trecho destacado para atualizar
# <mark class="nome-inst" data-antes="do CEFET-MG" data-depois="da UFCIMG">: menção ao nome antigo a decidir
NUMERO_PEQUENO = re.compile(r"^[1-9][0-9]?$")
VAZIAS = {"br", "img"}
TROCAR = {"b": "strong", "i": "em", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4", "div": "p"}
DESCARTAR_CONTEUDO = {"script", "style", "head", "title", "meta", "xml", "o:p", "template", "iframe", "object"}
REF = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")
# <ins>/<del> do controle de alterações (relatorio/revisao.py): id da sugestão, autor e data
SUG_ID = re.compile(r"^[a-z0-9]{1,24}$")
SUG_DATA = re.compile(r"^[0-9T:.+\-Z]{10,32}$")
SEM_FORMA = ("a", "span", "mark", "ins", "del")
# estilo das caixas de texto das páginas do RG (fonte, tamanho, cor e espaçamentos copiados do PDF): só estas
# propriedades, com valores simples
_FONTES_OK = {"Calibri,Carlito,sans-serif", "Arial,'Liberation Sans',sans-serif",
              "'Trade Gothic LT Std','Arial Narrow',Carlito,sans-serif", "'Minion Pro',Georgia,serif",
              "'Myriad Pro',Calibri,Carlito,sans-serif", "Symbol,serif"}
_PX = r"-?\d{1,4}(?:\.\d{1,3})?px"
_ESTILO_OK = {
    "font-size": re.compile(rf"^{_PX}$"), "line-height": re.compile(rf"^(?:{_PX}|\d(?:\.\d{{1,2}})?)$"),
    "margin-top": re.compile(rf"^{_PX}$"), "padding-left": re.compile(rf"^{_PX}$"),
    "text-indent": re.compile(rf"^{_PX}$"), "word-spacing": re.compile(rf"^{_PX}$"),
    "letter-spacing": re.compile(rf"^{_PX}$"), "font-weight": re.compile(r"^(?:[1-9]00|bold|normal)$"),
    "font-style": re.compile(r"^(?:italic|normal)$"), "color": re.compile(r"^#[0-9a-fA-F]{6}$"),
    "text-align": re.compile(r"^(?:left|right|center|justify)$"),
}


def estilo_seguro(css):
    """Só as propriedades de _ESTILO_OK (e fontes da lista), na ordem em que vieram."""
    partes = []
    for decl in (css or "").split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "font-family" and v in _FONTES_OK:
            partes.append(f"{k}:{v}")
        elif k in _ESTILO_OK and _ESTILO_OK[k].match(v):
            partes.append(f"{k}:{v}")
    return ";".join(partes)


class _Limpador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.saida = []
        self.pilha = []
        self.descartando = 0
        self.num_aberto = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DESCARTAR_CONTEUDO:
            self.descartando += 1
            return
        if self.descartando:
            return
        tag = TROCAR.get(tag, tag)
        if tag not in PERMITIDAS:
            return
        a = dict((k.lower(), v or "") for k, v in attrs)
        attrs_ok = ""
        if tag == "a":
            href = a.get("href", "").strip()
            if not re.match(r"^(https?://|mailto:)", href, re.I):
                self.pilha.append(None)        # link sem endereço válido: mantém só o texto
                return
            attrs_ok = f' href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer"'
        elif tag == "span":
            classes = a.get("class", "").split()
            ref = a.get("data-ref", "").strip()
            if "sirg-num" in classes and REF.match(ref):
                col = a.get("data-col", "").strip()
                esc_ = a.get("data-escala", "").strip()
                attrs_ok = f' class="sirg-num" data-ref="{ref}"' + (
                    f' data-col="{escape(col, quote=True)}"' if re.match(r"^[a-z][a-z0-9_]*$", col) else "") + (
                    f' data-escala="{esc_}"' if esc_ in ("mi", "mil", "nmi") else "")
                self.num_aberto += 1
                self.pilha.append("span")
                self.saida.append(f"<span{attrs_ok}>")
                return
            if "sirg-campo" in classes and re.match(r"^[a-z0-9]{1,24}$", a.get("data-c", "").strip()):
                # número do texto preenchido no ano (relatorio/campos.py): o valor fica no banco
                orig = re.sub(r"\s+", " ", a.get("data-orig", "")).strip()[:60]
                attrs_ok = (f' class="sirg-campo" data-c="{a.get("data-c").strip()}"'
                            f' data-orig="{escape(orig, quote=True)}"')
                self.num_aberto += 1
                self.pilha.append("span")
                self.saida.append(f"<span{attrs_ok}>")
                return
            estilo = estilo_seguro(a.get("style", ""))
            if estilo:                         # trecho com fonte, tamanho ou cor da página do RG
                self.pilha.append("span")
                self.saida.append(f'<span style="{escape(estilo, quote=True)}">')
                return
            self.pilha.append(None)            # outros spans: só o conteúdo
            return
        elif tag == "mark" and "nome-inst" in a.get("class", "").split():
            # menção ao nome antigo da instituição, à espera da escolha CEFET-MG / UFCIMG (relatorio/nome_inst.py)
            antes = re.sub(r"\s+", " ", a.get("data-antes", ""))[:120]
            depois = re.sub(r"\s+", " ", a.get("data-depois", ""))[:120]
            attrs_ok = (f' class="nome-inst" data-antes="{escape(antes, quote=True)}"'
                        f' data-depois="{escape(depois, quote=True)}"')
        elif tag == "mark":
            if "atualizar" not in a.get("class", "").split():
                self.pilha.append(None)        # marca-texto colado de fora: só o conteúdo
                return
            orig = re.sub(r"\s+", " ", a.get("data-orig", ""))[:400]
            attrs_ok = ' class="atualizar"' + (f' data-orig="{escape(orig, quote=True)}"' if orig else "")
        elif tag in ("ins", "del"):
            sid = a.get("data-s", "").strip()
            if not SUG_ID.match(sid):
                self.pilha.append(None)        # <ins>/<del> sem id (ex.: colado do Word): só o conteúdo
                return
            u = a.get("data-u", "").strip()
            autor = re.sub(r"\s+", " ", a.get("data-a", "")).strip()[:80]
            data = a.get("data-d", "").strip()
            attrs_ok = (f' data-s="{sid}"' + (f' data-u="{u}"' if u.isdigit() and len(u) <= 10 else "") +
                        f' data-a="{escape(autor, quote=True)}"' +
                        (f' data-d="{data}"' if SUG_DATA.match(data) else ""))
        elif tag == "img":
            src = a.get("src", "").strip()
            if not IMAGEM.match(src):
                return
            alt = re.sub(r"\s+", " ", a.get("alt", ""))[:200]
            attrs_ok = f' src="{src}" alt="{escape(alt, quote=True)}"'
        elif tag in ("td", "th"):
            for nome in ("colspan", "rowspan"):
                v = a.get(nome, "").strip()
                if NUMERO_PEQUENO.match(v) and v != "1":
                    attrs_ok += f' {nome}="{v}"'
        if tag == "p":
            estilo = estilo_seguro(a.get("style", ""))
            if estilo:
                attrs_ok = f' style="{escape(estilo, quote=True)}"'
        if tag in VAZIAS:
            self.saida.append(f"<{tag}{attrs_ok}>")
            return
        self.pilha.append(tag)
        self.saida.append(f"<{tag}{attrs_ok}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DESCARTAR_CONTEUDO:
            self.descartando = max(0, self.descartando - 1)
            return
        if self.descartando:
            return
        tag = TROCAR.get(tag, tag)
        if tag not in PERMITIDAS or tag in VAZIAS:
            return
        # fecha até a última tag correspondente
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i] == tag or (self.pilha[i] is None and tag in SEM_FORMA):
                while len(self.pilha) > i:
                    t = self.pilha.pop()
                    if t:
                        if t == "span":
                            self.num_aberto -= 1
                        self.saida.append(f"</{t}>")
                return

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br" and not self.descartando:
            self.saida.append("<br>")
        elif tag.lower() == "img":
            self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not self.descartando:
            self.saida.append(escape(data, quote=False))

    def resultado(self):
        while self.pilha:
            t = self.pilha.pop()
            if t:
                self.saida.append(f"</{t}>")
        return "".join(self.saida)


def limpar(html):
    p = _Limpador()
    p.feed(html or "")
    p.close()
    out = p.resultado()
    out = re.sub(r"<p>(\s|&nbsp;|<br>)*</p>", "", out)            # parágrafos vazios (imagem não conta como vazio)
    out = re.sub(r"(<br>\s*){3,}", "<br><br>", out)
    return out.strip()


def texto_puro(html):
    """Texto sem marcação (para comparar versões, contar palavras e enviar à IA)."""
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"</(p|li|h3|h4|blockquote|tr)>", "\n", t)
    t = re.sub(r"</t[dh]>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    from html import unescape
    return re.sub(r"\n{3,}", "\n\n", unescape(t)).strip()
