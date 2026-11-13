"""
Paletas de cores dos gráficos. A paleta vale para todos os gráficos do relatório (tela, Word e
pacote da diagramação) e é escolhida pelo Master ou pelo administrador em "Cores dos gráficos".

A ordem das cores importa: a 1ª é a cor das barras de uma série só; a 2ª, a da linha sobre as
barras (ex.: recursos); as seguintes, as demais séries e fatias. As paletas "acessivel", "ufcimg"
e "sobria" foram conferidas para daltonismo (protanopia, deuteranopia, tritanopia) entre cores
vizinhas; como os gráficos escrevem os valores e têm legenda, a cor nunca é o único código.
"""
from collections import OrderedDict

PADRAO = "ufcimg"

PALETAS = OrderedDict([
    ("rg", {"nome": "Institucional (RG 2025)",
            "descricao": "As cores do Relatório de Gestão publicado: azul-marinho e laranja, com verde, amarelo e rosa.",
            "cores": ["#17375E", "#F5A23C", "#8DBB89", "#F7CE1E", "#EE93BF", "#E4572E", "#4BB4C4", "#9B7BC4"]}),
    ("ufcimg", {"nome": "UFCIMG (azul e verde-água)",
                "descricao": "As cores da marca UFCIMG (azul e verde-água), com laranja, roxo e cores de apoio. Conferida para daltonismo.",
                "cores": ["#285C98", "#2A9C8E", "#E0802A", "#8C6BB8", "#C9A227", "#C2457F", "#5E9E4A", "#A9473B"]}),
    ("acessivel", {"nome": "Acessível (daltonismo)",
                   "descricao": "Cores fortes e bem separadas, fáceis de distinguir também por quem tem daltonismo.",
                   "cores": ["#2971C6", "#E18528", "#2C965D", "#C04688", "#17BAC8", "#A43B38", "#C0AC2E", "#7F5BB6"]}),
    ("sobria", {"nome": "Sóbria (azuis e terrosos)",
                "descricao": "Tons mais discretos, para um relatório de aparência formal.",
                "cores": ["#215D96", "#D18E46", "#0099A0", "#7C61A8", "#57AFE0", "#448C56", "#984649", "#A2933B"]}),
])


def todas():
    """Paletas do banco (editáveis em "Cores dos gráficos"), na ordem da tela. Sem banco: as de fábrica."""
    try:
        from contas.models import Paleta
        lista = list(Paleta.objects.all())
    except Exception:       # banco ainda sem a tabela (antes do migrate)
        lista = []
    if not lista:
        return OrderedDict((k, dict(v, sistema=True)) for k, v in PALETAS.items())
    return OrderedDict((p.chave, {"nome": p.nome, "descricao": p.descricao, "cores": list(p.cores or []),
                                  "sistema": p.sistema, "id": p.pk}) for p in lista if len(p.cores or []) >= 2)


def chave_atual():
    try:
        from contas.models import Instituicao
        ch = Instituicao.atual().paleta_graficos
    except Exception:       # banco ainda sem a coluna (antes do migrate)
        ch = PADRAO
    t = todas()
    return ch if ch in t else (PADRAO if PADRAO in t else next(iter(t)))


def cores(chave=None):
    t = todas()
    ch = chave if chave in t else chave_atual()
    return list(t.get(ch, PALETAS[PADRAO])["cores"])


# --- importar e exportar paletas (diagramação) -------------------------------------------------
import re  # noqa: E402
import struct  # noqa: E402

HEX = re.compile(r"(?<![0-9A-Fa-f])#?([0-9A-Fa-f]{6})(?![0-9A-Fa-f])")


def normalizar(cor):
    m = HEX.fullmatch((cor or "").strip())
    return f"#{m.group(1).upper()}" if m else None


def _rgb_hex(r, g, b):
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in (r, g, b))


def _lab_rgb(L, a, b):
    """CIE L*a*b* (D50, como no ASE) -> sRGB."""
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    def f(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = 0.9642 * f(fx), 1.0 * f(fy), 0.8249 * f(fz)
    # D50 -> sRGB (Bradford já embutido)
    r = 3.1338561 * X - 1.6168667 * Y - 0.4906146 * Z
    g = -0.9787684 * X + 1.9161415 * Y + 0.0334540 * Z
    bb = 0.0719453 * X - 0.2289914 * Y + 1.4052427 * Z
    def gama(c):
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return _rgb_hex(gama(r) * 255, gama(g) * 255, gama(bb) * 255)


def ler_ase(dados):
    """Cores de um arquivo .ase (Adobe Swatch Exchange: InDesign, Illustrator, Photoshop)."""
    if dados[:4] != b"ASEF":
        raise ValueError("o arquivo não é um .ase válido")
    _, _, n = struct.unpack(">HHI", dados[4:12])
    pos, out = 12, []
    for _ in range(n):
        if pos + 6 > len(dados):
            break
        tipo, tam = struct.unpack(">HI", dados[pos:pos + 6])
        corpo = dados[pos + 6:pos + 6 + tam]
        pos += 6 + tam
        if tipo != 0x0001:
            continue
        nchars = struct.unpack(">H", corpo[:2])[0]
        k = 2 + nchars * 2
        modelo = corpo[k:k + 4].decode("ascii", "replace").strip()
        k += 4
        if modelo == "RGB":
            r, g, b = struct.unpack(">fff", corpo[k:k + 12])
            out.append(_rgb_hex(r * 255, g * 255, b * 255))
        elif modelo == "CMYK":
            c, m, y, kk = struct.unpack(">ffff", corpo[k:k + 16])
            out.append(_rgb_hex(255 * (1 - c) * (1 - kk), 255 * (1 - m) * (1 - kk), 255 * (1 - y) * (1 - kk)))
        elif modelo == "LAB":
            L, a, b = struct.unpack(">fff", corpo[k:k + 12])
            out.append(_lab_rgb(L * 100, a, b))
        elif modelo == "Gray":
            v = struct.unpack(">f", corpo[k:k + 4])[0]
            out.append(_rgb_hex(v * 255, v * 255, v * 255))
    return out


def ler_arquivo(nome, dados):
    """Cores de um arquivo enviado: .ase, .gpl (GIMP/Inkscape) ou qualquer texto com códigos #RRGGBB
    (.txt, .csv, .json, .css). Devolve a lista de cores, sem repetir."""
    nome = (nome or "").lower()
    if nome.endswith(".ase") or dados[:4] == b"ASEF":
        cores_ = ler_ase(dados)
    else:
        texto = dados.decode("utf-8", "replace") if isinstance(dados, bytes) else dados
        cores_ = []
        if nome.endswith(".gpl") or texto.startswith("GIMP Palette"):
            for linha in texto.splitlines():
                m = re.match(r"\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\b", linha)
                if m:
                    cores_.append(_rgb_hex(*(int(x) for x in m.groups())))
        if not cores_:
            cores_ = [f"#{m.group(1).upper()}" for m in HEX.finditer(texto)]
    vistas, out = set(), []
    for c in cores_:
        if c not in vistas:
            vistas.add(c)
            out.append(c)
    return out


def gerar_ase(nome, cores_):
    """Arquivo .ase com as cores (para abrir no InDesign/Illustrator: Amostras > Carregar amostras)."""
    def bloco(tipo, corpo):
        return struct.pack(">HI", tipo, len(corpo)) + corpo

    def texto(t):
        u = (t + "\0").encode("utf-16-be")
        return struct.pack(">H", len(u) // 2) + u
    blocos = [bloco(0xC001, texto(nome))]
    for i, c in enumerate(cores_, start=1):
        r, g, b = (int(c[k:k + 2], 16) / 255 for k in (1, 3, 5))
        blocos.append(bloco(0x0001, texto(f"{nome} {i} {c}") + b"RGB " + struct.pack(">fff", r, g, b) + struct.pack(">H", 2)))
    blocos.append(bloco(0xC002, b""))
    return b"ASEF" + struct.pack(">HHI", 1, 0, len(blocos)) + b"".join(blocos)


def escura(cor):
    """A cor é escura o bastante para receber texto branco por cima?"""
    r, g, b = (int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] < 0.22
