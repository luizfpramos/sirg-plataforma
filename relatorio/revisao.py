"""
Controle de alterações do texto (como no Word).

Com o controle ligado, o que a pessoa digita entra no texto como inserção e o que ela apaga continua
no texto, riscado, como remoção, com o nome de quem fez e quando:

    <ins data-s="k3x9a1" data-u="12" data-a="Mara Lopes" data-d="2026-11-10T09:12:00">texto novo</ins>
    <del data-s="k3x9a1" data-u="12" data-a="Mara Lopes" data-d="2026-11-10T09:12:00">texto antigo</del>

`data-s` identifica a sugestão: uma troca (apagar e escrever no lugar) é uma sugestão só, com as duas partes.
Cada sugestão é aceita ou recusada separadamente, no texto ou no painel de revisão.

O texto oficial (leitura, Word, PDF) é o texto com as sugestões ainda pendentes recusadas:
o que foi sugerido só vale depois de aceito.
"""
import re
from html import escape
from html.parser import HTMLParser

from django.utils import timezone

TAGS = ("ins", "del")
VAZIAS = {"br", "img"}
ID = re.compile(r"^[a-z0-9]{1,24}$")


class _No:
    __slots__ = ("tag", "attrs", "filhos", "pai")

    def __init__(self, tag, attrs=None, pai=None):
        self.tag, self.attrs, self.filhos, self.pai = tag, list(attrs or []), [], pai

    def attr(self, nome, padrao=""):
        for k, v in self.attrs:
            if k == nome:
                return v if v is not None else ""
        return padrao

    def definir(self, nome, valor):
        for i, (k, _) in enumerate(self.attrs):
            if k == nome:
                self.attrs[i] = (k, valor)
                return
        self.attrs.append((nome, valor))


class _Arvore(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _No(None)
        self.atual = self.raiz

    def handle_starttag(self, tag, attrs):
        no = _No(tag, attrs, self.atual)
        self.atual.filhos.append(no)
        if tag not in VAZIAS:
            self.atual = no

    def handle_startendtag(self, tag, attrs):
        self.atual.filhos.append(_No(tag, attrs, self.atual))

    def handle_endtag(self, tag):
        n = self.atual
        while n is not None and n.tag != tag:
            n = n.pai
        if n is not None and n.pai is not None:
            self.atual = n.pai

    def handle_data(self, data):
        self.atual.filhos.append(data)


def _arvore(html):
    p = _Arvore()
    p.feed(html or "")
    p.close()
    return p.raiz


def _html(no):
    out = []

    def escrever(n):
        for f in n.filhos:
            if isinstance(f, str):
                out.append(escape(f, quote=False))
                continue
            at = "".join(f' {k}="{escape(v or "", quote=True)}"' for k, v in f.attrs)
            if f.tag in VAZIAS:
                out.append(f"<{f.tag}{at}>")
            else:
                out.append(f"<{f.tag}{at}>")
                escrever(f)
                out.append(f"</{f.tag}>")
    escrever(no)
    return "".join(out)


def _marcas(no):
    """Elementos <ins>/<del> com id, na ordem do texto."""
    for f in list(no.filhos):
        if isinstance(f, str):
            continue
        if f.tag in TAGS and ID.match(f.attr("data-s")):
            yield f
        yield from _marcas(f)


def _texto(no):
    partes = []
    for f in no.filhos:
        if isinstance(f, str):
            partes.append(f)
        elif f.tag == "img":
            partes.append("[imagem]")
        elif f.tag == "br":
            partes.append(" ")
        else:
            partes.append(_texto(f))
    return "".join(partes)


def tem(html):
    return bool(html) and ("<ins" in html or "<del" in html)


def itens(html):
    """Sugestões pendentes do texto: [{id, autor_id, autor, data, inserido, removido}], na ordem do texto."""
    if not tem(html):
        return []
    out = {}
    for el in _marcas(_arvore(html)):
        sid = el.attr("data-s")
        it = out.setdefault(sid, {"id": sid, "autor_id": int(el.attr("data-u") or 0) or None,
                                  "autor": el.attr("data-a") or "?", "data": el.attr("data-d"),
                                  "inserido": "", "removido": ""})
        it["inserido" if el.tag == "ins" else "removido"] += _texto(el)
    for it in out.values():
        it["inserido"] = re.sub(r"\s+", " ", it["inserido"]).strip()
        it["removido"] = re.sub(r"\s+", " ", it["removido"]).strip()
    return list(out.values())


def aplicar(html, ids=None, aceitar=True):
    """Aceita (ou recusa) as sugestões `ids` (todas, se None). Devolve o HTML resultante."""
    if not tem(html):
        return html or ""
    alvo = None if ids is None else set(ids)
    raiz = _arvore(html)
    for el in list(_marcas(raiz)):
        if alvo is not None and el.attr("data-s") not in alvo:
            continue
        pai = el.pai
        if el not in pai.filhos:          # já saiu junto com um elemento de cima
            continue
        i = pai.filhos.index(el)
        sai = (el.tag == "ins") != bool(aceitar)      # recusar inserção / aceitar remoção: o conteúdo sai
        if sai:
            pai.filhos[i:i + 1] = []
        else:
            for f in el.filhos:
                if not isinstance(f, str):
                    f.pai = pai
            pai.filhos[i:i + 1] = el.filhos
    out = _html(raiz)
    out = re.sub(r"<(strong|em|u|s|sup|sub|a|mark)(\s[^>]*)?></\1>", "", out)    # formatação que ficou vazia
    out = re.sub(r"<(p|li|h3|h4|blockquote)>(\s|&nbsp;|\xa0|<br>)*</\1>", "", out)
    return out


def base(html):
    """Texto oficial: o que foi sugerido e ainda não aceito não entra."""
    return aplicar(html, None, aceitar=False)


def carimbar(antes, depois, user):
    """Garante a autoria das sugestões ao gravar: as que já existiam mantêm autor e data; as novas recebem
    o nome de quem está gravando (o navegador não escolhe em nome de quem sugere)."""
    if not tem(depois):
        return depois
    conhecidas = {}
    for el in _marcas(_arvore(antes)) if tem(antes) else []:
        conhecidas.setdefault(el.attr("data-s"), (el.attr("data-u"), el.attr("data-a"), el.attr("data-d")))
    raiz = _arvore(depois)
    agora = timezone.localtime().replace(microsecond=0).isoformat()
    nome = (user.get_full_name() or user.username)[:80]
    novas = {}
    for el in _marcas(raiz):
        sid = el.attr("data-s")
        if sid in conhecidas:
            u, a, d = conhecidas[sid]
        else:
            u, a, d = novas.setdefault(sid, (str(user.pk), nome, agora))
        el.definir("data-u", u)
        el.definir("data-a", a)
        el.definir("data-d", d)
    return _html(raiz)


def autores(html):
    """Ids dos usuários com sugestões pendentes no texto."""
    return {it["autor_id"] for it in itens(html) if it["autor_id"]}


def texto_base(html):
    """Texto do que vale hoje (sugestões pendentes recusadas), sem marcação, para comparar duas versões:
    números e campos contam pela referência (o valor exibido muda sozinho)."""
    h = base(html or "")
    h = re.sub(r'<span class="sirg-num" data-ref="([^"]*)"[^>]*>.*?</span>', r" ⟦\1⟧ ", h, flags=re.S)
    h = re.sub(r'<span class="sirg-campo" data-c="([^"]*)"[^>]*>.*?</span>', r" ⟦\1⟧ ", h, flags=re.S)
    h = re.sub(r"<img\b[^>]*>", " ⟦img⟧ ", h)
    from html import unescape
    t = unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"[\s\u00a0]+", " ", t).strip()
