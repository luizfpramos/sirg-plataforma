"""Importador de PDF: o administrador envia o PDF diagramado do Relatório de Gestão e o sistema gera, sozinho, o
fundo das páginas e as caixas de texto — sem depender de desenvolvedor.

1. `receber()` guarda o PDF em dados/arquivos/importacoes/<id>/original.pdf;
2. `iniciar()` lê o PDF em segundo plano (relatorio/pdf_paginas.py): pNNN.jpg (fundo sem texto) e paginas.json;
3. o administrador confere as páginas e `aplicar()` cria as páginas e os trechos de texto no ciclo.

`aplicar()` só vale para um ciclo que ainda não tem páginas. Num ciclo que já tem páginas, o PDF revisado entra por
relatorio/reimportador.py, que não altera o que os setores escreveram.
"""
import json
import logging
import re
import threading
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .models import Bloco, Ciclo, ImportacaoPDF, Pagina

log = logging.getLogger("sirg")
TAMANHO_MAXIMO = 250 * 1024 * 1024       # 250 MB


class Recusado(Exception):
    pass


# --- receber e ler ---------------------------------------------------------------------------------------------
def receber(ciclo, arquivo, user):
    """Guarda o PDF enviado e cria a importação (ainda sem ler o PDF)."""
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("O ciclo está encerrado.")
    if not arquivo:
        raise Recusado("Escolha o arquivo PDF.")
    if not arquivo.name.lower().endswith(".pdf"):
        raise Recusado("O arquivo precisa ser um PDF.")
    if arquivo.size > TAMANHO_MAXIMO:
        raise Recusado(f"O PDF tem mais de {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
    inicio = arquivo.read(5)
    arquivo.seek(0)
    if inicio != b"%PDF-":
        raise Recusado("O arquivo não é um PDF válido.")
    if ciclo.importacoes.filter(situacao=ImportacaoPDF.PROCESSANDO).exclude(
            atualizado_em__lt=timezone.now() - timedelta(minutes=15)).exists():
        raise Recusado("Já há um PDF sendo lido neste ciclo. Espere terminar.")
    imp = ImportacaoPDF.objects.create(ciclo=ciclo, nome=arquivo.name[:255], tamanho=arquivo.size, enviado_por=user,
                                       etapa="Na fila")
    imp.pasta.mkdir(parents=True, exist_ok=True)
    with open(imp.pasta / "original.pdf", "wb") as f:
        for pedaco in arquivo.chunks():
            f.write(pedaco)
    return imp


def _marcar(pk, **campos):
    campos["atualizado_em"] = timezone.now()
    ImportacaoPDF.objects.filter(pk=pk).update(**campos)


def processar(pk):
    """Lê o PDF da importação `pk`: fundos (pNNN.jpg) e caixas de texto (paginas.json)."""
    from . import pdf_paginas as PP
    imp = ImportacaoPDF.objects.get(pk=pk)
    pdf = imp.pasta / "original.pdf"
    try:
        total = PP.contar_paginas(pdf)
        _marcar(pk, situacao=ImportacaoPDF.PROCESSANDO, progresso=0, mensagem="",
                etapa=f"Gerando o fundo das {total} páginas")
        # o fundo é rápido (~10% do tempo); ler o texto é o resto
        PP.fundos(pdf, imp.pasta, ao_avancar=lambda n: n % 5 == 0 and _marcar(
            pk, progresso=int(10 * n / total), etapa=f"Fundo da página {n} de {total}"))
        paginas = PP.extrair(pdf, ao_avancar=lambda n: _marcar(
            pk, progresso=10 + int(89 * n / total), etapa=f"Lendo o texto da página {n} de {total}"))
        (imp.pasta / "paginas.json").write_text(json.dumps(paginas, ensure_ascii=False), encoding="utf-8")
        fontes = Counter()
        for p in paginas:
            for c in p["caixas"]:
                fontes[c["fam"]] += len(c["texto"])
        resumo = {"paginas": len(paginas), "caixas": sum(len(p["caixas"]) for p in paginas),
                  "largura": paginas[0]["w"] if paginas else 0, "altura": paginas[0]["h"] if paginas else 0,
                  "fontes": [PP.familia_css(f).split(",")[0].strip("'") for f, _ in fontes.most_common(6)],
                  "sem_texto": [p["n"] for p in paginas if not p["caixas"]]}
        _marcar(pk, situacao=ImportacaoPDF.PRONTA, progresso=100, etapa="Pronta", resumo=resumo)
    except Exception as e:  # PDF protegido, corrompido etc.: a pessoa vê a mensagem e pode tentar de novo
        log.exception("importação de PDF %s", pk)
        _marcar(pk, situacao=ImportacaoPDF.ERRO, etapa="Erro",
                mensagem=f"Não foi possível ler o PDF ({type(e).__name__}: {e})."[:2000])


def iniciar(imp):
    """Lê o PDF em segundo plano (a leitura de um relatório de ~100 páginas leva alguns minutos)."""
    _marcar(imp.pk, situacao=ImportacaoPDF.PROCESSANDO, progresso=0, etapa="Começando a leitura", mensagem="")
    if getattr(settings, "SIRG_IMPORTACAO_SINCRONA", False):
        processar(imp.pk)
        return

    def rodar(pk):
        close_old_connections()
        try:
            processar(pk)
        finally:
            connection.close()

    threading.Thread(target=rodar, args=(imp.pk,), name=f"importacao-pdf-{imp.pk}", daemon=True).start()


def paginas_lidas(imp):
    arq = imp.pasta / "paginas.json"
    if not arq.exists():
        return []
    return json.loads(arq.read_text(encoding="utf-8"))


def url_fundo(imp, n):
    return f"arquivos/importacoes/{imp.pk}/p{n:03d}.jpg"


# --- textos fixos (cabeçalho, rodapé, número da página) -------------------------------------------------------
def _assinatura(c):
    return round(c["y"] / 4), re.sub(r"\d+", "#", re.sub(r"\s+", " ", c["texto"].strip()))[:60]


def textos_fixos(paginas):
    """Função que diz se uma caixa é texto fixo: número de página ou texto repetido no alto/pé de muitas páginas."""
    from .paginas import _e_fixo
    faixa = lambda c, H: c["y"] < H * 0.1 or c["y"] > H * 0.85     # noqa: E731
    conta = Counter()
    for p in paginas:
        for a in {_assinatura(c) for c in p["caixas"] if faixa(c, p["h"])}:
            conta[a] += 1
    limite = max(3, 0.25 * len(paginas))
    repetidas = {a for a, k in conta.items() if k >= limite}

    def e_fixo(c, H):
        if _e_fixo(c, H):
            return True
        if not faixa(c, H):
            return False
        t = c["texto"].strip()
        return (t.isdigit() and len(t) <= 3 and c["y"] > H * 0.85) or _assinatura(c) in repetidas
    return e_fixo


# --- onde começa cada seção -----------------------------------------------------------------------------------
def _ordem_secao(s):
    return ((s.pai.ordem if s.pai_id else s.ordem), (s.ordem if s.pai_id else -1), s.pk)


def limite_de_titulo(paginas):
    """Tamanho de letra a partir do qual uma caixa é título (30% maior que o texto corrido, no mínimo 12,5)."""
    pesos = Counter()
    for p in paginas:
        for c in p["caixas"]:
            pesos[c["tam"]] += len(c["texto"])
    corpo = max(pesos, key=pesos.get) if pesos else 10
    return max(12.5, corpo * 1.3)


def marcos_das_secoes(ciclo, paginas, e_fixo):
    """Procura o título de cada seção (na ordem do relatório) entre os títulos do PDF. Não usa IA: compara o nome
    da seção com os textos de letra grande (sem acentos nem maiúsculas; a partir de 80% de semelhança). Devolve
    ([(página, coluna, altura, seção)], [seções não encontradas])."""
    from .paginas import _coluna, _parecido, normalizar
    limite = limite_de_titulo(paginas)
    titulos = []
    for p in paginas:
        if any(normalizar(c["texto"]) == "sumario" for c in p["caixas"]):
            continue                                        # o sumário repete todos os títulos
        for c in p["caixas"]:
            if c["tam"] >= limite and not e_fixo(c, p["h"]):
                titulos.append((p["n"], _coluna(c, p["w"]), c["y"], c["texto"]))
    titulos.sort(key=lambda t: t[:3])
    secoes = sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao)
    marcos, faltam, pos = [], [], 0
    for s in secoes:
        nome = re.sub(r"^\d+(\.\d+)*\.?\s*", "", s.titulo)
        achou = next((k for k in range(pos, len(titulos)) if _parecido(nome, titulos[k][3]) >= 0.8), None)
        if achou is None:
            faltam.append(s)
            continue
        n, col, y, _ = titulos[achou]
        marcos.append((n, col, y - 1, s))
        pos = achou + 1
    return marcos, faltam


def conferencia(imp):
    """Linhas da tabela "seção → página inicial" que o administrador confere antes de aplicar: o que o sistema
    achou e o que ficou gravado como escolha (imp.resumo["inicios"], {pk: página ou None})."""
    paginas = paginas_lidas(imp)
    marcos, _ = marcos_das_secoes(imp.ciclo, paginas, textos_fixos(paginas))
    achadas = {m[3].pk: m[0] for m in marcos}
    escolhas = (imp.resumo or {}).get("inicios") or {}
    linhas, maior = [], 0
    for s in sorted(imp.ciclo.secoes.select_related("pai").prefetch_related("setores"), key=_ordem_secao):
        k = str(s.pk)
        # 2.23: sem escolha gravada, vale a página prevista na lista de seções; depois, a que o sistema achou
        pagina = escolhas[k] if k in escolhas else (s.pagina_inicio or achadas.get(s.pk))
        linhas.append({"s": s, "achada": achadas.get(s.pk), "prevista": s.pagina_inicio, "pagina": pagina,
                       "difere": bool(s.pagina_inicio and achadas.get(s.pk) and s.pagina_inicio != achadas.get(s.pk)),
                       "fixo": s.conteudo_fixo,
                       "fora_de_ordem": bool(pagina and pagina < maior)})   # começa antes de uma seção anterior
        maior = max(maior, pagina or 0)
    return linhas


def marcos_com_escolhas(ciclo, paginas, e_fixo, inicios=None):
    """Os marcos achados, com as páginas escolhidas pelo administrador no lugar. `inicios`: {pk: página ou None}
    (None = a seção não está no PDF). Mesma página que a achada = mantém a posição exata do título; outra página
    = a seção começa no alto dela. Devolve ([marcos em ordem de posição], [seções sem página])."""
    marcos, faltam = marcos_das_secoes(ciclo, paginas, e_fixo)
    if inicios is None:
        return marcos, faltam
    por_secao = {m[3].pk: m for m in marcos}
    numeros = {p["n"] for p in paginas}
    novos, sem = [], []
    for s in sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao):
        n = inicios.get(s.pk, por_secao[s.pk][0] if s.pk in por_secao else None)
        if not n:
            sem.append(s)
            continue
        if n not in numeros:
            raise Recusado(f"A página {n} (seção “{s.titulo}”) não existe no PDF.")
        achado = por_secao.get(s.pk)
        novos.append(achado if achado and achado[0] == n else (n, -1, -1, s))
    ordem = {s.pk: i for i, s in enumerate(sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao))}
    novos.sort(key=lambda m: (m[:3], ordem[m[3].pk]))
    return novos, sem


# --- aplicar ao ciclo -----------------------------------------------------------------------------------------
def inicios_gravados(ciclo, exceto=None):
    """As páginas iniciais escolhidas na última aplicação de PDF do ciclo ({pk: página ou None}), ou None."""
    for imp in ciclo.importacoes.exclude(pk=getattr(exceto, "pk", None)).filter(situacao=ImportacaoPDF.APLICADA):
        ini = (imp.resumo or {}).get("inicios")
        if ini:
            return {int(k): v for k, v in ini.items()}
    return None


def motivo_para_nao_aplicar(imp):
    if imp.situacao == ImportacaoPDF.APLICADA:
        return "Este PDF já foi aplicado ao ciclo."
    if imp.situacao != ImportacaoPDF.PRONTA:
        return "O PDF ainda não foi lido."
    if imp.ciclo.situacao == Ciclo.ENCERRADO:
        return "O ciclo está encerrado."
    if imp.ciclo.paginas.exists():
        return "Este ciclo já tem páginas. Use a reimportação, que não altera o que os setores escreveram."
    if not imp.ciclo.secoes.exists():
        return "O ciclo ainda não tem seções."
    return ""


ROTULO_CURTO = 40      # caracteres: abaixo disso a caixa do PDF é rótulo (fica fixa), não parágrafo


def tamanho_sugerido(n):
    """Mínimo e máximo de caracteres sugeridos a partir do tamanho do texto que estava no PDF (70% a 130%).
    Textos muito curtos (rótulos, legendas) ficam sem limite."""
    if n < 40:
        return None, None
    return int(n * 0.7), int(n * 1.3) + 1


def conteudo_da_caixa(c, secao, limite, automatico=False):
    """O que entra no bloco criado a partir de uma caixa do PDF. Devolve (conteúdo, config extra, mínimo, máximo,
    campos criados).

    - Título (letra grande) ou seção de conteúdo fixo: o texto do PDF como está; só o Editor-chefe altera.
    - Texto curto (menos de ROTULO_CURTO caracteres): também fixo, marcado como rótulo (e, se tem número, como
      número do ano anterior, para o administrador conferir).
    - Demais caixas: o bloco nasce vazio. O texto do PDF fica guardado como referência do ano anterior e o
      tamanho dele sugere o mínimo e o máximo de caracteres.
    - RG 2026 automático (montado pelo desenvolvedor a partir do RG 2025): o texto do PDF com os números como xxxxx,
      como antes da 2.18."""
    from . import atributos as AT
    from . import campos as CT
    from .html_seguro import limpar, texto_puro
    html = limpar(c["html"])
    if automatico:
        html, novos = CT.camposificar(html)
        return html, {}, None, None, len(novos)
    if c["tam"] >= limite or secao.conteudo_fixo:
        return html, {"fixo": True}, None, None, 0
    n = AT.contar_caracteres(html)
    if n < ROTULO_CURTO:
        # rótulo de gráfico, célula de tabela, texto de infográfico: fica como texto fixo do modelo. O administrador
        # libera para o setor (indicadores) ou troca a área por um bloco de gráfico ou tabela.
        return html, {"fixo": True, "rotulo": True, "numero_antigo": bool(re.search(r"\d", texto_puro(html)))}, \
            None, None, 0
    minimo, maximo = tamanho_sugerido(n)
    return "", {"referencia_pdf": html}, minimo, maximo, 0


MANUAL, SUGERIDOS = "manual", "sugeridos"
MODOS_DOS_BLOCOS = [
    (MANUAL, "Eu crio os blocos no editor (recomendado). A importação cria só as páginas; no editor, o texto do PDF "
             "aparece por cima do fundo e cada bloco nasce de um clique ou de uma área desenhada. Só as seções "
             "marcadas como conteúdo fixo já recebem os textos do PDF."),
    (SUGERIDOS, "O sistema sugere os blocos de texto (como antes): cria um bloco para cada caixa de texto do PDF e "
                "decide sozinho o que fica fixo. Imagens e gráficos continuam a desenhar à mão."),
]


def aplicar(imp, user, inicios=None, blocos=SUGERIDOS):
    """Cria as páginas e os blocos do ciclo a partir do PDF lido. Só num ciclo sem páginas. `inicios`: as páginas
    iniciais escolhidas na conferência ({pk da seção: página ou None}); sem elas, vale o que o sistema achou.
    `blocos` (2.21): MANUAL (o padrão da tela) cria só as páginas, mais os blocos fixos das seções de conteúdo fixo; quem
    decide os demais é a pessoa, no editor. SUGERIDOS cria um bloco por caixa de texto, como até a 2.20. O RG 2026
    automático segue sempre como antes."""
    from .html_seguro import limpar
    from .paginas import _caixa_css, _coluna
    motivo = motivo_para_nao_aplicar(imp)
    if motivo:
        raise Recusado(motivo)
    paginas = paginas_lidas(imp)
    if not paginas:
        raise Recusado("Não há páginas lidas neste PDF.")
    ciclo = imp.ciclo
    manual = blocos == MANUAL and not ciclo.automatico
    e_fixo = textos_fixos(paginas)
    limite = limite_de_titulo(paginas)
    marcos, faltam = marcos_com_escolhas(ciclo, paginas, e_fixo, inicios)
    primeira_secao = sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao)[0]

    def dono(n, col, y):
        atual = None
        for m in marcos:
            if m[:3] <= (n, col, y):
                atual = m[3]
            else:
                break
        return atual or primeira_secao

    feito = {"paginas": 0, "caixas": 0, "campos": 0, "vazios": 0, "fixos": 0}
    with transaction.atomic():
        if Pagina.objects.select_for_update().filter(ciclo=ciclo).exists():
            raise Recusado("Este ciclo já tem páginas.")
        for p in paginas:
            n, W, H = p["n"], p["w"], p["h"]
            caixas = sorted(p["caixas"], key=lambda c: (_coluna(c, W), c["y"], c["x"]))
            fixos = "".join(f'<div class="pg-fixo" style="{_caixa_css(c)}">{limpar(c["html"])}</div>'
                            for c in caixas if e_fixo(c, H))
            corpo = [c for c in caixas if not e_fixo(c, H)]
            sec_pag = dono(n, _coluna(corpo[0], W), corpo[0]["y"]) if corpo else dono(n, 0, 0)
            pg = Pagina.objects.create(ciclo=ciclo, numero=n, largura=W, altura=H, fundo=url_fundo(imp, n),
                                       secao=sec_pag, fixos=fixos)
            feito["paginas"] += 1
            for i, c in enumerate(corpo):
                secao = dono(n, _coluna(c, W), c["y"])
                if manual and not secao.conteudo_fixo:
                    continue            # a pessoa cria o bloco no editor, a partir do texto do PDF
                html, extra, minimo, maximo, campos = conteudo_da_caixa(c, secao, limite, ciclo.automatico)
                feito["campos"] += campos
                if extra.get("fixo"):
                    feito["fixos"] += 1
                elif not html:
                    feito["vazios"] += 1
                Bloco.objects.create(
                    secao=secao, pagina=pg, tipo=Bloco.TEXTO, ordem=n * 1000 + i, conteudo=html,
                    min_caracteres=minimo, max_caracteres=maximo,
                    config={"caixa": {"x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"], "css": c["css"],
                                      "quebra": c["quebra"]}, "importacao": imp.pk, "campos212": True, **extra})
                feito["caixas"] += 1
        resumo = dict(imp.resumo or {}, aplicado=feito, blocos=MANUAL if manual else SUGERIDOS, secoes_achadas=len(marcos),
                      secoes_faltando=[s.titulo for s in faltam],
                      inicios={str(m[3].pk): m[0] for m in marcos} | {str(s.pk): None for s in faltam})
        ImportacaoPDF.objects.filter(pk=imp.pk).update(
            situacao=ImportacaoPDF.APLICADA, aplicada_em=timezone.now(), aplicada_por=user, resumo=resumo)
    imp.refresh_from_db()
    return feito
