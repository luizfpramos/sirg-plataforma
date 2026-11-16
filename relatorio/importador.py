"""Importador de PDF: o administrador envia o PDF diagramado do Relatório de Gestão e o sistema gera, sozinho, o
fundo das páginas e as caixas de texto — sem depender de desenvolvedor.

1. `receber()` guarda o PDF em dados/arquivos/importacoes/<id>/original.pdf;
2. `iniciar()` lê o PDF em segundo plano (relatorio/pdf_paginas.py): pNNN.jpg (fundo sem texto) e paginas.json;
3. o administrador confere as páginas e `aplicar()` cria as páginas e os trechos de texto no ciclo.

Por enquanto só se aplica a um ciclo que ainda não tem páginas. Reimportar um PDF revisado num ciclo que já tem
páginas, sem perder o que os setores escreveram, é a etapa 4 do plano do editor de blocos.
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


def marcos_das_secoes(ciclo, paginas, e_fixo):
    """Procura o título de cada seção (na ordem do relatório) entre os títulos do PDF. Devolve
    ([(página, coluna, altura, seção)], [seções não encontradas])."""
    from .paginas import _coluna, _parecido, normalizar
    pesos = Counter()
    for p in paginas:
        for c in p["caixas"]:
            pesos[c["tam"]] += len(c["texto"])
    corpo = max(pesos, key=pesos.get) if pesos else 10
    limite = max(12.5, corpo * 1.3)
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


# --- aplicar ao ciclo -----------------------------------------------------------------------------------------
def motivo_para_nao_aplicar(imp):
    if imp.situacao == ImportacaoPDF.APLICADA:
        return "Este PDF já foi aplicado ao ciclo."
    if imp.situacao != ImportacaoPDF.PRONTA:
        return "O PDF ainda não foi lido."
    if imp.ciclo.situacao == Ciclo.ENCERRADO:
        return "O ciclo está encerrado."
    if imp.ciclo.paginas.exists():
        return ("Este ciclo já tem páginas. Trocar as páginas sem perder o que os setores escreveram "
                "(reimportação) é a próxima fase; por enquanto, use esta tela para conferir o PDF.")
    if not imp.ciclo.secoes.exists():
        return "O ciclo ainda não tem seções."
    return ""


def aplicar(imp, user):
    """Cria as páginas e os trechos de texto do ciclo a partir do PDF lido. Só num ciclo sem páginas."""
    from . import campos as CT
    from .html_seguro import limpar
    from .paginas import _caixa_css, _coluna
    motivo = motivo_para_nao_aplicar(imp)
    if motivo:
        raise Recusado(motivo)
    paginas = paginas_lidas(imp)
    if not paginas:
        raise Recusado("Não há páginas lidas neste PDF.")
    ciclo = imp.ciclo
    e_fixo = textos_fixos(paginas)
    marcos, faltam = marcos_das_secoes(ciclo, paginas, e_fixo)
    primeira_secao = sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao)[0]

    def dono(n, col, y):
        atual = None
        for m in marcos:
            if m[:3] <= (n, col, y):
                atual = m[3]
            else:
                break
        return atual or primeira_secao

    feito = {"paginas": 0, "caixas": 0, "campos": 0}
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
                html, novos = CT.camposificar(limpar(c["html"]))
                feito["campos"] += len(novos)
                Bloco.objects.create(
                    secao=dono(n, _coluna(c, W), c["y"]), pagina=pg, tipo=Bloco.TEXTO, ordem=n * 1000 + i,
                    conteudo=html, config={"caixa": {"x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"],
                                                     "css": c["css"], "quebra": c["quebra"]},
                                           "importacao": imp.pk, "campos212": True})
                feito["caixas"] += 1
        resumo = dict(imp.resumo or {}, aplicado=feito, secoes_achadas=len(marcos),
                      secoes_faltando=[s.titulo for s in faltam])
        ImportacaoPDF.objects.filter(pk=imp.pk).update(
            situacao=ImportacaoPDF.APLICADA, aplicada_em=timezone.now(), aplicada_por=user, resumo=resumo)
    imp.refresh_from_db()
    return feito

