"""
Gráficos dos quadros, desenhados no servidor (o mesmo desenho vai para a tela e para o Word).

Seguem o formato dos gráficos do Relatório de Gestão publicado: barras azul-marinho com os
valores escritos, linha laranja com os valores em cada ponto, pizza com valor e percentual.

Configuração do bloco de gráfico (Bloco.config):
    tipo:        barras | barras_horizontais | barras_empilhadas | linhas | pizza | rosca
    linhas:      chaves das linhas a mostrar (vazio = todas as do mesmo tipo da primeira)
    total:       incluir a linha de total (padrão: não)
    colunas:     chaves das colunas a mostrar (vazio = todas)
    inverter:    séries nas colunas e categorias nas linhas (automático quando há uma só coluna)
    rotulos:     mostrar os valores sobre as marcas (padrão: sim)
    linha:       série desenhada como LINHA sobre as barras, com eixo próprio à direita
                 (ex.: barras de alunos + linha de recursos, como no RG). Pode ser:
                   "recursos"                 linha do mesmo quadro
                   "pq_bolsistas.bolsistas"   linha de outro quadro (mesmos anos)
                   "gp_capacitacao_servidores.*"  outro quadro com as mesmas linhas (gráfico invertido)
    linha_rotulo: nome da linha na legenda (opcional)
    recentes_primeiro: em barras horizontais por ano, o ano mais recente fica em cima
"""
import hashlib
import io
import json
import logging
import threading
from collections import OrderedDict
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import formato  # noqa: E402
from .calculo import TOTAL  # noqa: E402
from .models import Quadro  # noqa: E402

# Cores: a paleta escolhida em "Cores dos gráficos" (relatorio/paletas.py). PALETA é preenchida
# com ela a cada desenho, sob a trava _desenho (o pyplot não é seguro entre threads).
from . import paletas  # noqa: E402

PALETA = paletas.cores(paletas.PADRAO)
_desenho = threading.Lock()
TINTA, TINTA_2, GRADE = "#1d2735", "#5b6676", "#e3e8ef"
TIPOS = [("barras", "Barras verticais"), ("barras_horizontais", "Barras horizontais"),
         ("barras_empilhadas", "Barras empilhadas"), ("linhas", "Linhas (evolução)"),
         ("pizza", "Pizza (partes de um todo)"), ("rosca", "Rosca (partes de um todo, com o total no meio)")]
BARRAS = ("barras", "barras_horizontais", "barras_empilhadas")
_cache = OrderedDict()
_trava = threading.Lock()

plt.rcParams.update({
    "font.family": ["Calibri", "Carlito", "DejaVu Sans"], "font.size": 9, "svg.fonttype": "none",
    "axes.edgecolor": GRADE, "axes.labelcolor": TINTA_2, "xtick.color": TINTA_2, "ytick.color": TINTA_2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
})


def abreviar(n, tipo):
    """Valor curto para os eixos (R$ 4,46 mi)."""
    if n is None:
        return ""
    v = float(n)
    pref = "R$ " if tipo == Quadro.MOEDA else ""
    suf = "%" if tipo == Quadro.PERCENTUAL else ""
    a = abs(v)
    if a >= 1e9:
        return f"{pref}{formato.numero_br(v / 1e9, 2)} bi"
    if a >= 1e6:
        return f"{pref}{formato.numero_br(v / 1e6, 2)} mi"
    if a >= 1e4 and tipo == Quadro.MOEDA:
        return f"{pref}{formato.numero_br(v / 1e3, 1)} mil"
    casas = 1 if tipo == Quadro.PERCENTUAL or (a < 100 and v != int(v)) else 0
    return f"{pref}{formato.numero_br(v, casas)}{suf}"


def abreviar_curto(n, tipo, prefixo=False):
    """Rótulo curto para dentro de barras estreitas: 77,5 mi · 6,8 mi · 950 mil · 1.234."""
    if n is None:
        return ""
    v, a = float(n), abs(float(n))
    pref = "R$ " if (prefixo and tipo == Quadro.MOEDA) else ""
    if tipo == Quadro.PERCENTUAL:
        return f"{formato.numero_br(v, 1)}%"
    if a >= 1e9:
        return f"{pref}{formato.numero_br(v / 1e9, 1)} bi"
    if a >= 1e6:
        return f"{pref}{formato.numero_br(v / 1e6, 1)} mi"
    if a >= 1e4:
        return f"{pref}{formato.numero_br(v / 1e3, 0)} mil"
    return f"{pref}{formato.numero_br(v, 0)}"


def valor_por_extenso(n, tipo, casas):
    """Valor completo, como escrito nos gráficos do RG (R$ 671.406,99 · 14.755 · 86,0%)."""
    if n is None:
        return ""
    if tipo == Quadro.PERCENTUAL:
        casas = min(int(casas or 0), 2)
    return formato.exibir(tipo, Decimal(str(n)), "", casas)


def _linha_extra_chave(config):
    ref = (config or {}).get("linha") or ""
    return ref if ref and "." not in ref else None


def dados(calc, quadro, config):
    """Séries para o gráfico: (categorias, [(nome, [valores])], tipo, avisos)."""
    config = config or {}
    avisos = []
    cols = calc.colunas_de(quadro)
    if config.get("colunas"):
        cols = [c for c in cols if c.chave in config["colunas"]] or cols
    linhas = calc.linhas_de(quadro)
    escolhidas = config.get("linhas") or []
    if escolhidas:
        linhas = [li for li in linhas if li.chave in escolhidas]
    extra = _linha_extra_chave(config) if config.get("tipo", "barras") in BARRAS else None
    if extra:
        linhas = [li for li in linhas if li.chave != extra]
    if not linhas:
        return [], [], quadro.tipo_valor, ["Escolha ao menos uma linha."]
    tipo = linhas[0].tipo
    mesmo_tipo = [li for li in linhas if li.tipo == tipo]
    if len(mesmo_tipo) < len(linhas):
        avisos.append("Linhas de unidades diferentes não vão nas mesmas barras (foram mostradas só as de "
                      f"{dict(Quadro.TIPOS).get(tipo, tipo).lower()}). Para mostrar as duas, use a opção "
                      "“Linha sobre as barras”.")
        linhas = mesmo_tipo
    if tipo in (Quadro.TEXTO, Quadro.SIM_NAO):
        return [], [], tipo, ["Este quadro não tem valores numéricos para desenhar."]
    rotulos_linhas = [(li.chave, li.rotulo) for li in linhas]
    if config.get("total") and quadro.linha_total:
        rotulos_linhas.append((TOTAL, quadro.rotulo_total))
    inverter = config.get("inverter", len(cols) == 1)
    matriz = {(lk, c.pk): calc.celula(quadro, lk, c) for lk, _ in rotulos_linhas for c in cols}
    if not inverter:
        categorias = [c.rotulo for c in cols]
        series = [(rot, [_num(matriz[(lk, c.pk)]) for c in cols]) for lk, rot in rotulos_linhas]
    else:
        categorias = [rot for _, rot in rotulos_linhas]
        series = [(c.rotulo, [_num(matriz[(lk, c.pk)]) for lk, _ in rotulos_linhas]) for c in cols]
    if config.get("ordenar") and len(series) == 1:      # ranking: do maior para o menor (vazios no fim)
        pares = sorted(zip(categorias, series[0][1]), key=lambda p: (p[1] is None, -(p[1] or 0)))
        categorias = [c for c, _ in pares]
        series = [(series[0][0], [v for _, v in pares])]
    if len(series) > len(PALETA) - 1:
        avisos.append(f"Muitas séries: foram desenhadas as {len(PALETA) - 1} primeiras. Divida em mais de um gráfico.")
        series = series[:len(PALETA) - 1]
    return categorias, series, tipo, avisos


def serie_linha(calc, quadro, config):
    """Série desenhada como linha sobre as barras: (nome, [valores], tipo, casas) ou None."""
    config = config or {}
    ref = (config.get("linha") or "").strip()
    if not ref or config.get("tipo", "barras") not in BARRAS:
        return None
    cols = calc.colunas_de(quadro)
    if config.get("colunas"):
        cols = [c for c in cols if c.chave in config["colunas"]] or cols
    inverter = config.get("inverter", len(cols) == 1)
    partes = ref.split(".")
    alvo = quadro if len(partes) == 1 else calc.quadros.get(partes[0])
    if alvo is None:
        return None
    if inverter:
        if len(partes) != 2 or partes[1] != "*":
            return None
        linhas = calc.linhas_de(quadro)
        if config.get("linhas"):
            linhas = [li for li in linhas if li.chave in config["linhas"]]
        col = calc.coluna_alinhada(alvo, cols[0]) if cols else None
        if col is None:
            return None
        chaves_alvo = calc.linhas.get(alvo.pk, {})
        vals = [_num(calc.celula(alvo, li.chave, col)) if li.chave in chaves_alvo else None for li in linhas]
        nome = config.get("linha_rotulo") or alvo.titulo
        return nome, vals, alvo.tipo_valor, alvo.casas_decimais
    lk = partes[-1] if len(partes) == 1 else partes[1]
    li = calc.linhas.get(alvo.pk, {}).get(lk)
    if li is None:
        return None
    vals = []
    for c in cols:
        ca = c if alvo is quadro else calc.coluna_alinhada(alvo, c)
        vals.append(_num(calc.celula(alvo, lk, ca)) if ca is not None else None)
    return config.get("linha_rotulo") or li.rotulo, vals, li.tipo, alvo.casas_decimais


def _num(r):
    return float(r.numero) if r.numero is not None and not r.erro else None


def _assinatura(*partes):
    bruto = json.dumps(partes, sort_keys=True, default=str)
    return hashlib.sha1(bruto.encode()).hexdigest()


def desenhar(calc, quadro, config, titulo="", formato_saida="svg", largura=7.0):
    """SVG (texto) ou PNG (bytes) do gráfico. Devolve (conteúdo, avisos)."""
    categorias, series, tipo, avisos = dados(calc, quadro, config)
    if not series or not categorias:
        return None, avisos
    extra = serie_linha(calc, quadro, config)
    if config and config.get("linha") and extra is None:
        avisos.append("A linha sobre as barras não foi encontrada: confira a configuração do gráfico.")
    valores = [v for _, vals in series for v in vals] + (extra[1] if extra else [])
    if all(v is None for v in valores):
        return None, avisos + ["Ainda não há valores preenchidos para desenhar o gráfico."]
    if quadro.modo_colunas == Quadro.ANOS and len(categorias) > 1 and categorias[0].isdigit():
        # anos do começo da série sem nenhum dado (ex.: série publicada só a partir de 2023) ficam de fora
        k = 0
        while k < len(categorias) - 1 and all(vals[k] is None for _, vals in series) and \
                (extra is None or extra[1][k] is None):
            k += 1
        if k:
            categorias = categorias[k:]
            series = [(nome, vals[k:]) for nome, vals in series]
            if extra:
                extra = (extra[0], extra[1][k:], extra[2], extra[3])
    cores = paletas.cores()
    chave = _assinatura(categorias, series, tipo, config, titulo, formato_saida, largura, extra,
                        quadro.casas_decimais, cores)
    with _trava:
        if chave in _cache:
            _cache.move_to_end(chave)
            return _cache[chave], avisos
    conteudo = desenhar_com_cores(cores, categorias, series, tipo, config or {}, titulo, formato_saida, largura,
                                  extra, quadro.casas_decimais)
    with _trava:
        _cache[chave] = conteudo
        while len(_cache) > 300:
            _cache.popitem(last=False)
    return conteudo, avisos


def desenhar_com_cores(cores, *args, **kw):
    """Desenha com a paleta `cores` (também usado na amostra da tela "Cores dos gráficos")."""
    with _desenho:
        PALETA[:] = cores
        return _figura(*args, **kw)


def _figura(categorias, series, tipo, config, titulo, formato_saida, largura, extra=None, casas=2):
    t = config.get("tipo", "barras")
    if t not in dict(TIPOS):
        t = "barras"
    if t == "barras" and len(categorias) > 6 and max((len(str(c)) for c in categorias), default=0) > 10 \
            and not str(categorias[0]).strip().isdigit():
        t = "barras_horizontais"      # muitos nomes compridos: na horizontal os rótulos não se encavalam
    rotulos = config.get("rotulos", True)
    n = len(series)
    if t == "barras_horizontais":
        altura = max(2.4, 0.34 * len(categorias) * max(1, n) + 1.0)
    elif t in ("pizza", "rosca"):
        altura = 3.2 if largura >= 6 else 3.0 + 0.24 * len(categorias)    # estreito: legenda embaixo
    else:
        altura = 3.4
    if config.get("_altura"):
        altura = float(config["_altura"])          # área do gráfico numa página do RG
    fig, ax = plt.subplots(figsize=(largura, altura), dpi=100 if formato_saida == "svg" else 200)
    fig.patch.set_facecolor("white")
    fmt = FuncFormatter(lambda v, _p: abreviar(v, tipo))
    escrever = (lambda v: valor_por_extenso(v, tipo, casas))
    legenda = None
    if t in ("pizza", "rosca"):
        _pizza(ax, categorias, series, tipo, escrever, rosca=(t == "rosca"))
    elif t == "linhas":
        _linhas(ax, categorias, series, rotulos, escrever, fmt)
        if n > 1:
            legenda = ([Line2D([0], [0], color=PALETA[i], linewidth=2) for i in range(n)], [s[0] for s in series])
    else:
        legenda = _barras(ax, categorias, series, t, rotulos, escrever, fmt, extra, casas, dict(config, _tipo=tipo))
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if legenda and legenda[0]:
        fig.legend(legenda[0], legenda[1], loc="lower center", ncol=min(len(legenda[1]), 5), frameon=False,
                   fontsize=8, bbox_to_anchor=(0.5, -0.01))
    if titulo:
        ax.set_title(titulo, loc="center", fontsize=10, fontweight="bold", color=PALETA[0], pad=24 if t in ("pizza", "rosca") else 12)
    fig.tight_layout(rect=(0, 0.07 if legenda and legenda[0] else 0, 1, 1))
    buf = io.BytesIO()
    if formato_saida == "png":
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue().decode("utf-8")
    svg = svg[svg.find("<svg"):]
    return svg.replace("<svg ", '<svg class="grafico-svg" role="img" ', 1)


def _pizza(ax, categorias, series, tipo, escrever, rosca):
    """Pizza/rosca no padrão do RG: percentuais com duas casas fora da fatia (linha de chamada em cotovelo, sem
    rótulos encavalados), o valor de cada grupo na legenda e, na rosca, o total no centro."""
    import math
    _nome, vals = series[0]
    pares = [(c, v) for c, v in zip(categorias, vals) if v]
    if len(pares) > len(PALETA):
        # cores nunca se repetem: as menores fatias viram "Outros"
        pares.sort(key=lambda p: -p[1])
        pares = pares[:len(PALETA) - 1] + [("Outros", sum(v for _, v in pares[len(PALETA) - 1:]))]
    if not pares:
        ax.axis("off")
        return
    cores = PALETA[:len(pares)]
    total = sum(v for _, v in pares)
    props = {"edgecolor": "white", "linewidth": 2}
    if rosca:
        props["width"] = 0.34
    fatias, _ = ax.pie([v for _, v in pares], colors=cores, startangle=90, counterclock=False, wedgeprops=props,
                       radius=1.0)
    # rótulos: cada lado em coluna, na altura da fatia, afastando os que ficariam colados
    lados = {True: [], False: []}
    for f, (c, v) in zip(fatias, pares):
        ang = math.radians((f.theta1 + f.theta2) / 2)
        x, y = math.cos(ang), math.sin(ang)
        lados[x >= 0].append({"x": x, "y": y, "ty": 1.12 * y, "v": v})
    passo = 0.15
    for lado, itens in lados.items():
        itens.sort(key=lambda d: -d["ty"])
        for k in range(1, len(itens)):                 # de cima para baixo: ninguém a menos de `passo` do anterior
            if itens[k - 1]["ty"] - itens[k]["ty"] < passo:
                itens[k]["ty"] = itens[k - 1]["ty"] - passo
        if itens and itens[-1]["ty"] < -1.2:           # passou do pé: sobe o bloco todo
            desloca = -1.2 - itens[-1]["ty"]
            for d in itens:
                d["ty"] += desloca
        for d in itens:
            sinal = 1 if lado else -1
            pct = 100 * d["v"] / total
            txt = formato.numero_br(pct, 2) + "%"
            # linha de chamada: da borda da fatia até o cotovelo, e dali na horizontal até o texto
            ax.plot([1.0 * d["x"], 1.06 * d["x"] if abs(d["ty"] - 1.06 * d["y"]) < 0.02 else sinal * 1.12, sinal * 1.19],
                    [1.0 * d["y"], 1.06 * d["y"] if abs(d["ty"] - 1.06 * d["y"]) < 0.02 else d["ty"], d["ty"]],
                    color=TINTA_2, linewidth=0.6, solid_capstyle="round", clip_on=False)
            ax.text(sinal * 1.22, d["ty"], txt, ha="left" if lado else "right", va="center", fontsize=8.5, color=TINTA)
    if rosca:
        if tipo == Quadro.MOEDA and total >= 1e6:
            grande, unidade = (formato.numero_br(total / 1e9, 2), "BILHÕES") if total >= 1e9 else \
                (formato.numero_br(total / 1e6, 2), "MILHÕES")
            ax.text(0, 0.07, f"R$ {grande}", ha="center", va="center", fontsize=13, fontweight="bold", color=TINTA)
            ax.text(0, -0.13, unidade, ha="center", va="center", fontsize=7, color=TINTA_2)
        else:
            ax.text(0, 0, escrever(total), ha="center", va="center", fontsize=12, fontweight="bold", color=TINTA)
    def valor(v):
        return abreviar(v, tipo) if tipo == Quadro.MOEDA else escrever(v)
    nomes = [f"{c}  ({valor(v)})" for c, v in pares]
    if ax.figure.get_size_inches()[0] < 6:      # prévia estreita (ao lado da tabela): legenda embaixo
        ax.legend(fatias, nomes, loc="upper center", bbox_to_anchor=(0.5, -0.02), frameon=False, fontsize=8,
                  handlelength=1.0, handleheight=1.0, ncol=1)
    else:
        ax.legend(fatias, nomes, loc="center left", bbox_to_anchor=(1.32, 0.5),
                  frameon=False, fontsize=8.5, handlelength=1.0, handleheight=1.0, labelspacing=0.9)
    ax.set_aspect("equal")
    ax.set_xlim(-1.45, 1.45)
    ax.set_ylim(-1.3, 1.3)


def _linhas(ax, categorias, series, rotulos, escrever, fmt):
    x = list(range(len(categorias)))
    n = len(series)
    pontos = {}
    for i, (nome, vals) in enumerate(series):
        pts = [(xi, v) for xi, v in zip(x, vals) if v is not None]
        if not pts:
            continue
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=PALETA[i], linewidth=2, marker="o", markersize=4,
                label=nome, zorder=3)
        for xi, v in pts:
            pontos.setdefault(xi, []).append((v, i))
    if rotulos:
        # como no RG: o valor ao lado de cada ponto; a série mais alta escreve acima, as outras abaixo
        for xi, lista in pontos.items():
            lista.sort(reverse=True)
            for k, (v, i) in enumerate(lista):
                acima = k == 0 or n == 1
                ax.annotate(escrever(v), (xi, v), textcoords="offset points", xytext=(0, 7 if acima else -12),
                            ha="center", fontsize=7.5, color=TINTA,
                            fontweight="bold" if xi == len(categorias) - 1 else "normal")
        ax.set_yticks([])
        ax.spines["bottom"].set_color(GRADE)
    else:
        ax.yaxis.set_major_formatter(fmt)
        ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_xticks(x, categorias)
    ax.set_xlim(-0.4, len(categorias) - 0.6)
    ax.margins(y=0.25)


def _barras(ax, categorias, series, t, rotulos, escrever, fmt, extra, casas, config):
    horizontal = t == "barras_horizontais"
    empilhar = t == "barras_empilhadas"
    n = len(series)
    if horizontal and config.get("recentes_primeiro"):
        categorias = list(reversed(categorias))
        series = [(nome, list(reversed(vals))) for nome, vals in series]
    x = list(range(len(categorias)))
    largura_barra = (0.72 if (empilhar and not horizontal and len(categorias) > 5) else 0.55) \
        if (empilhar or n == 1) else 0.8 / n
    base = [0.0] * len(categorias)
    handles, nomes = [], []
    maximo = max((sum((vv or 0) for vv in col) for col in zip(*[sv for _, sv in series])), default=0) if empilhar \
        else max((v or 0 for _, vals in series for v in vals), default=0)
    dentro = extra is not None and not empilhar and n == 1     # combinado: valor da barra escrito dentro dela
    # muitas barras empilhadas: o valor completo (R$ 77.500.000,00) não cabe na barra; vai abreviado
    # (77,5 mi) e o total da barra aparece em cima (R$ 83,2 mi), como no RG
    compacto = empilhar and not horizontal and len(categorias) > 5
    tipo_q = config.get("_tipo")

    if maximo >= 1e9:
        div, unid = 1e9, "bilhões"
    elif maximo >= 1e6:
        div, unid = 1e6, "milhões"
    elif maximo >= 1e4:
        div, unid = 1e3, "mil"
    else:
        div, unid = 1, ""

    def curto(v):
        return formato.numero_br(float(v) / div, 1 if div > 1 else 0)
    if compacto and rotulos and unid:
        ax.text(0, 1.03, ("Valores em R$ " if tipo_q == Quadro.MOEDA else "Valores em ") + unid, transform=ax.transAxes,
                fontsize=7.5, color=TINTA_2, ha="left", va="bottom")
    for i, (nome, vals) in enumerate(series):
        vals0 = [v or 0 for v in vals]
        pos = x if (empilhar or n == 1) else [xi - 0.4 + largura_barra * (i + 0.5) for xi in x]
        kw = dict(color=PALETA[i], label=nome, edgecolor="white", linewidth=0.8, zorder=3)
        if horizontal:
            barras = ax.barh(pos, vals0, height=largura_barra, left=base if empilhar else None, **kw)
        else:
            barras = ax.bar(pos, vals0, width=largura_barra, bottom=base if empilhar else None, **kw)
        handles.append(Patch(color=PALETA[i]))
        nomes.append(config.get("barras_rotulo") if (n == 1 and config.get("barras_rotulo")) else nome)
        if rotulos:
            txt = [(curto(v) if compacto else escrever(v)) if v is not None else "" for v in vals]
            if empilhar or dentro:
                limite = (0.06 if compacto else 0.07) * maximo
                txt = [tx if (v or 0) >= limite else "" for tx, v in zip(txt, vals)]
            ax.bar_label(barras, labels=txt, label_type="center" if (empilhar or dentro) else "edge", padding=2,
                         fontsize=7.2 if compacto else (6.5 if n >= 4 else 7.5),
                         color=("white" if paletas.escura(PALETA[i]) else TINTA) if (empilhar or dentro) else TINTA)
        if empilhar:
            base = [b + v for b, v in zip(base, vals0)]
    if compacto and rotulos and n > 1:
        for xi, tot in zip(x, base):
            if tot:
                ax.annotate(curto(tot), (xi, tot), textcoords="offset points",
                            xytext=(0, 3), ha="center", va="bottom", fontsize=8, fontweight="bold", color=TINTA)
    if horizontal:
        ax.set_yticks(x, categorias)
        ax.invert_yaxis()
        if rotulos:
            ax.set_xticks([])
            ax.spines["bottom"].set_visible(False)
            ax.spines["left"].set_visible(True)
            ax.spines["left"].set_color(GRADE)
        else:
            ax.xaxis.set_major_formatter(fmt)
            ax.grid(axis="x", color=GRADE, linewidth=0.8)
        ax.margins(x=0.15)
    else:
        ax.set_xticks(x, categorias)
        if rotulos:
            ax.set_yticks([])
        else:
            ax.yaxis.set_major_formatter(fmt)
            ax.grid(axis="y", color=GRADE, linewidth=0.8)
        ax.margins(y=0.15)
        if max(len(str(c)) for c in categorias) > 12 and len(categorias) > 3:
            import textwrap
            ax.set_xticks(x, ["\n".join(textwrap.wrap(str(c), 16)) for c in categorias])
    if extra is not None and not horizontal:
        nome, vals, tipo_l, casas_l = extra
        cor = PALETA[n] if n < len(PALETA) else PALETA[1]
        ax2 = ax.twinx()
        pts = [(xi, v) for xi, v in zip(x, vals) if v is not None]
        if pts:
            ax2.plot([p[0] for p in pts], [p[1] for p in pts], color=cor, linewidth=2.2, zorder=4)
            if rotulos:
                for xi, v in pts:
                    ax2.annotate(valor_por_extenso(v, tipo_l, casas_l), (xi, v), textcoords="offset points",
                                 xytext=(0, 7), ha="center", fontsize=7.5, color=TINTA, zorder=5,
                                 bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85},
                                 fontweight="bold" if xi == len(categorias) - 1 else "normal")
            topo = max(v for _, v in pts)
            ax2.set_ylim(0, topo * 1.3 if topo > 0 else 1)
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: abreviar(v, tipo_l)))
        ax2.tick_params(length=0, labelsize=7, colors=TINTA_2)
        for lado in ("top", "left", "bottom"):
            ax2.spines[lado].set_visible(False)
        ax2.spines["right"].set_visible(False)
        handles.append(Line2D([0], [0], color=cor, linewidth=2.2))
        nomes.append(nome)
        if maximo:
            ax.set_ylim(0, maximo * 1.12)
    return (handles, nomes) if (len(nomes) > 1) else None
