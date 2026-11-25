"""
Montar o relatório do ano (2.18): os passos em ordem, as seções do ciclo e o ciclo de trabalho.

  passos(ciclo)            — os passos da montagem, cada um com a situação e a tela onde se faz
  ROTEIRO, navegacao(...)  — títulos e telas dos passos, para a barra "Passo N de 8" de cada tela (2.21)
  adicionar_em_lote(...)   — cria capítulos e seções a partir de uma lista colada (ex.: o sumário do PDF)
  mover_secao(...)         — sobe ou desce uma seção entre as irmãs
  inicios_das_secoes(...), mudar_inicios(...) — a página em que cada seção começa, corrigível depois de aplicar o
                             PDF (2.21): as páginas e os blocos passam para a seção certa
  tornar_de_trabalho(...)  — o ciclo que o menu abre para todos
  excluir_ciclo(...)       — só onde a configuração permite (homologação): apaga o ciclo e os arquivos
"""
import re
import shutil

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from contas.models import Setor

from .forms import gerar_chave
from .models import Bloco, Ciclo, Secao


class Recusado(Exception):
    pass


# --- passos ------------------------------------------------------------------------------------------------------
# Título curto e tela de cada passo, na ordem. A barra no alto de cada tela (passo anterior, próximo, volta à
# montagem) sai daqui, e as URLs de passos() também, para as duas nunca divergirem.
ROTEIRO = [
    ("Setores e pessoas", lambda ano: reverse("setores") + f"?montagem={ano}"),
    ("Seções", lambda ano: reverse("secoes_lista", args=[ano])),
    ("PDF diagramado", lambda ano: reverse("importar_pdf", args=[ano])),
    ("Blocos nas páginas", lambda ano: reverse("editor_inicio", args=[ano])),
    ("Atributos dos blocos", lambda ano: reverse("blocos_atributos", args=[ano])),
    ("Quadros de números", lambda ano: reverse("quadros_lista", args=[ano])),
    ("PDF do relatório anterior", lambda ano: reverse("pdf_anterior_enviar", args=[ano])),
    ("Abrir a coleta", lambda ano: reverse("ciclo_editar", args=[ano])),
]


def navegacao(ciclo, n):
    """Dados da barra de navegação do passo `n` (contado de 1)."""
    total = len(ROTEIRO)
    n = max(1, min(int(n), total))

    def item(i):
        titulo, url = ROTEIRO[i - 1]
        return {"n": i, "titulo": titulo, "url": url(ciclo.ano)}
    return {"ciclo": ciclo, "n": n, "total": total, "titulo": ROTEIRO[n - 1][0],
            "montagem": reverse("montagem", args=[ciclo.ano]),
            "anterior": item(n - 1) if n > 1 else None, "proximo": item(n + 1) if n < total else None}


def passos(ciclo):
    """Os passos da montagem, em ordem. situacao: "feito", "falta" ou "aviso"."""
    from .models import ImportacaoPDF
    ano = ciclo.ano
    caps = ciclo.secoes.filter(pai__isnull=True).count()
    secs = ciclo.secoes.filter(pai__isnull=False).count()
    sem_setor = ciclo.secoes.filter(pai__isnull=False, setores__isnull=True).count()
    n_pag = ciclo.paginas.count()
    imp = ciclo.importacoes.first()
    blocos = Bloco.objects.filter(secao__ciclo=ciclo, pagina__isnull=False)
    n_blocos = blocos.count()
    texto = blocos.filter(tipo=Bloco.TEXTO)
    sem_descricao = texto.filter(descricao="", conteudo="").count()       # os vazios, que os setores escrevem
    n_quadros = ciclo.quadros.count()
    aberto = ciclo.situacao != Ciclo.PREPARACAO

    def p(titulo, texto, situacao, url, botao):
        return {"titulo": titulo, "texto": texto, "situacao": situacao, "url": url, "botao": botao}

    from django.db.models import Count, Q
    ativos = list(Setor.objects.filter(ativo=True).annotate(
        n=Count("vinculos", filter=Q(vinculos__fim__isnull=True, vinculos__usuario__is_active=True))))
    vazios = [st.sigla for st in ativos if not st.n]
    if not ativos:
        s_set = p("Setores e pessoas", "Cadastre os setores que respondem pelo relatório e as pessoas de cada um.",
                  "falta", ROTEIRO[0][1](ano), "Cadastrar os setores")
    else:
        txt = (f"{len(ativos)} setor(es) ativo(s). Os setores valem para todos os anos: confira se surgiu algum, "
               f"se algum deixou de existir e se cada um tem pessoas cadastradas.")
        if vazios:
            txt += f" Sem ninguém cadastrado: {', '.join(vazios[:8])}{'…' if len(vazios) > 8 else ''}."
        s_set = p("Setores e pessoas", txt, "aviso" if vazios else "feito", ROTEIRO[0][1](ano),
                  "Conferir os setores")

    if not (caps or secs):
        s_sec = p("Seções", "Crie os capítulos e as seções. Dá para colar o sumário do PDF de uma vez.", "falta",
                  reverse("secoes_lista", args=[ano]), "Criar as seções")
    else:
        aviso = f" {sem_setor} seção(ões) sem setor responsável." if sem_setor else ""
        s_sec = p("Seções", f"{caps} capítulo(s) e {secs} seção(ões).{aviso}", "aviso" if sem_setor else "feito",
                  reverse("secoes_lista", args=[ano]), "Ver as seções")

    if n_pag:
        s_pdf = p("PDF diagramado", f"{n_pag} páginas aplicadas ao ciclo. Seção na página errada? Corrija no "
                                    f"passo 2, em “Página em que cada seção começa”.", "feito",
                  reverse("importar_pdf", args=[ano]), "Ver a importação")
    elif imp and imp.situacao == ImportacaoPDF.PRONTA:
        s_pdf = p("PDF diagramado", "O PDF foi lido. Confira as páginas de cada seção e aplique ao ciclo.", "aviso",
                  reverse("importacao_ver", args=[ano, imp.pk]), "Conferir e aplicar")
    elif imp and imp.situacao == ImportacaoPDF.PROCESSANDO:
        s_pdf = p("PDF diagramado", "O sistema está lendo o PDF.", "aviso",
                  reverse("importacao_ver", args=[ano, imp.pk]), "Acompanhar")
    else:
        s_pdf = p("PDF diagramado", "Envie o PDF diagramado do relatório. Crie as seções antes.", "falta",
                  reverse("importar_pdf", args=[ano]), "Importar o PDF")

    numeros = [b for b in texto.filter(conteudo__gt="").only("config") if (b.config or {}).get("numero_antigo")]
    sem_bloco = ciclo.paginas.filter(caixas__isnull=True).count() if n_pag else 0
    if not n_blocos and n_pag:
        s_blo = p("Blocos nas páginas", f"{n_pag} página(s) ainda sem blocos. No editor, clique no texto do PDF para "
                  f"criar cada bloco, ou desenhe a área de imagens e gráficos.", "falta",
                  reverse("editor_inicio", args=[ano]), "Criar os blocos")
    elif not n_blocos:
        s_blo = p("Blocos nas páginas", "Os blocos se criam no editor, depois de aplicar o PDF.", "falta",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    else:
        vazios = texto.filter(conteudo="").count()
        txt = f"{n_blocos} bloco(s) nas páginas, {vazios} vazio(s) para os setores."
        if sem_bloco:
            txt += f" {sem_bloco} página(s) ainda sem nenhum bloco."
        if numeros:
            txt += (f" {len(numeros)} texto(s) fixo(s) com número do ano anterior (em laranja no editor): troque a área "
                    f"por um gráfico ou tabela, libere para o setor ou confira.")
        s_blo = p("Blocos nas páginas", txt, "aviso" if (numeros or sem_bloco) else "feito",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    s_atr = p("Atributos dos blocos",
              (f"{sem_descricao} bloco(s) vazio(s) sem a descrição do que escrever." if sem_descricao
               else "Todos os blocos de texto têm descrição.") if n_blocos else "Setor, descrição e tamanho de cada bloco.",
              ("aviso" if sem_descricao else "feito") if n_blocos else "falta",
              reverse("blocos_atributos", args=[ano]), "Definir os atributos")
    s_qua = p("Quadros de números",
              f"{n_quadros} quadro(s). Os gráficos e as tabelas dos blocos vêm daqui; os anos anteriores são "
              f"preenchidos pela DGDI." if n_quadros
              else "As tabelas de números que alimentam os gráficos e as tabelas dos blocos.",
              "feito" if n_quadros else "falta", reverse("quadros_lista", args=[ano]), "Quadros de números")
    tem_ant = caminho_pdf_anterior(ciclo).is_file()
    s_ant = p("PDF do relatório anterior (consulta)",
              "Enviado: os setores abrem pelo botão no alto do relatório." if tem_ant
              else ("Opcional. Os setores consultam o relatório publicado no ano anterior ao lado do SiRG."
                    + (" Hoje vale o que vem no sistema." if url_pdf_anterior(ciclo) else "")),
              "feito" if tem_ant else "falta", reverse("pdf_anterior_enviar", args=[ano]),
              "Trocar o PDF" if tem_ant else "Enviar o PDF")
    s_col = p("Abrir a coleta",
              f"Situação: {ciclo.get_situacao_display().split(' (')[0].lower()}."
              + ("" if aberto else " Quando tudo estiver pronto, mude para “coleta” para os setores começarem."),
              "feito" if aberto else "falta", reverse("ciclo_editar", args=[ano]), "Situação e prazo")
    return [s_set, s_sec, s_pdf, s_blo, s_atr, s_qua, s_ant, s_col]


# --- seções ------------------------------------------------------------------------------------------------------
_SETORES = re.compile(r"\s*\|\s*([A-Za-zÀ-ÿ0-9 ,;/-]*)$")


def _chave_livre(ciclo, titulo):
    base = gerar_chave(titulo, 34)
    ch, n = base, 2
    while Secao.objects.filter(ciclo=ciclo, chave=ch).exists():
        ch, n = f"{base}_{n}", n + 1
    return ch


@transaction.atomic
def adicionar_em_lote(ciclo, texto):
    """Uma linha por item. Linha comum = capítulo; linha que começa com "-" (ou com recuo) = seção do capítulo
    acima. No fim da linha, opcional: "| SIGLA, SIGLA" com os setores responsáveis.
    Devolve (capítulos, seções, avisos, {sigla que não existe: [pk das seções que a pediram]})."""
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("O ciclo está encerrado.")
    siglas = {s.sigla.upper(): s for s in Setor.objects.all()}
    cap_atual = ciclo.secoes.filter(pai__isnull=True).order_by("-ordem", "-id").first()
    ordem_cap = (cap_atual.ordem if cap_atual else 0)
    n_caps = n_secs = 0
    avisos, faltando = [], []
    for n, bruta in enumerate((texto or "").splitlines(), start=1):
        if not bruta.strip():
            continue
        e_secao = bool(re.match(r"^(\s+|\s*[-–•*]\s*)", bruta))
        linha = re.sub(r"^\s*[-–•*]?\s*", "", bruta).strip()
        setores = []
        m = _SETORES.search(linha)
        if m:
            linha = linha[:m.start()].strip()
            for sg in re.split(r"[,;/ ]+", m.group(1)):
                if not sg:
                    continue
                s = siglas.get(sg.upper())
                if s:
                    setores.append(s)
                else:
                    avisos.append(f"Linha {n}: setor “{sg}” não existe.")
                    faltando.append((sg.upper(), None))
        if not linha:
            faltando = [(sg, pk) for sg, pk in faltando if pk]      # sigla numa linha sem título: só o aviso
            continue
        titulo = linha[:255]
        if e_secao:
            if cap_atual is None:
                avisos.append(f"Linha {n}: “{titulo}” é uma seção, mas não há capítulo acima. Ficou como capítulo.")
                e_secao = False
        if e_secao:
            ordem = (cap_atual.filhas.count() + 1) * 10
            s = Secao.objects.create(ciclo=ciclo, pai=cap_atual, titulo=titulo, ordem=ordem,
                                     chave=_chave_livre(ciclo, titulo))
            n_secs += 1
        else:
            ordem_cap += 10
            s = Secao.objects.create(ciclo=ciclo, titulo=titulo, ordem=ordem_cap, chave=_chave_livre(ciclo, titulo))
            cap_atual = s
            n_caps += 1
        if setores:
            s.setores.set(setores)
        faltando = [(sg, pk or s.pk) for sg, pk in faltando]
    por_sigla = {}
    for sg, pk in faltando:
        por_sigla.setdefault(sg, []).append(pk)
    return n_caps, n_secs, avisos, por_sigla


@transaction.atomic
def mover_secao(secao, direcao):
    irmas = list(Secao.objects.filter(ciclo=secao.ciclo, pai=secao.pai).order_by("ordem", "id"))
    i = next(k for k, s in enumerate(irmas) if s.pk == secao.pk)
    j = i - 1 if direcao == "subir" else i + 1
    if 0 <= j < len(irmas):
        irmas[i], irmas[j] = irmas[j], irmas[i]
    for k, s in enumerate(irmas, start=1):
        if s.ordem != k * 10:
            Secao.objects.filter(pk=s.pk).update(ordem=k * 10)


def arvore(ciclo):
    """[(capítulo, [seções])] na ordem do relatório."""
    secoes = list(ciclo.secoes.prefetch_related("setores", "paginas"))
    caps = sorted((s for s in secoes if s.pai_id is None), key=lambda s: (s.ordem, s.pk))
    filhas = {}
    for s in secoes:
        if s.pai_id:
            filhas.setdefault(s.pai_id, []).append(s)
    return [(c, sorted(filhas.get(c.pk, []), key=lambda s: (s.ordem, s.pk))) for c in caps]


# --- página inicial de cada seção (2.21) --------------------------------------------------------------------------
def _em_ordem(ciclo):
    from .importador import _ordem_secao
    return sorted(ciclo.secoes.select_related("pai"), key=_ordem_secao)


def inicios_das_secoes(ciclo):
    """[(seção, página inicial ou None)] na ordem do relatório. A página inicial é a primeira página da seção."""
    from django.db.models import Min
    primeira = dict(ciclo.paginas.filter(secao__isnull=False).values("secao").annotate(n=Min("numero"))
                    .values_list("secao", "n"))
    return [(s, primeira.get(s.pk)) for s in _em_ordem(ciclo)]


@transaction.atomic
def mudar_inicios(ciclo, novos):
    """Corrige onde cada seção começa. `novos`: {pk da seção: número da página ou None (seção fora do PDF)}; seção
    que não vem em `novos` mantém a página atual. Cada página passa a ser da última seção que começa nela ou antes; os
    blocos da página que eram da seção antiga da página vão junto. Blocos que a pessoa pôs em outra seção ficam.
    Páginas antes da primeira seção não mudam. Devolve {"paginas": n, "blocos": n}."""
    from .models import ImportacaoPDF, Pagina
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("O ciclo está encerrado.")
    atuais = inicios_das_secoes(ciclo)
    numeros = set(ciclo.paginas.values_list("numero", flat=True))
    marcos, ultima, anterior = [], None, None
    for ordem, (s, atual) in enumerate(atuais):
        n = novos.get(s.pk, atual) if s.pk in novos else atual
        if n is None:
            continue
        if n not in numeros:
            raise Recusado(f"A página {n} não existe (seção “{s.titulo}”).")
        if ultima is not None and n < ultima:
            raise Recusado(f"“{s.titulo}” começaria na página {n}, antes de “{anterior}” (página {ultima}). "
                           f"As seções seguem a ordem do relatório; mude a ordem em Seções, se for o caso.")
        marcos.append((n, ordem, s))
        ultima, anterior = n, s.titulo
    feito = {"paginas": 0, "blocos": 0}
    for pg in Pagina.objects.select_for_update().filter(ciclo=ciclo).order_by("numero"):
        dono = None
        for n, _o, s in marcos:
            if n <= pg.numero:
                dono = s
            else:
                break
        if dono is None or dono.pk == pg.secao_id:
            continue
        if pg.secao_id:
            feito["blocos"] += Bloco.objects.filter(pagina=pg, secao_id=pg.secao_id).update(secao=dono)
        else:
            feito["blocos"] += Bloco.objects.filter(pagina=pg, secao__isnull=True).update(secao=dono)
        Pagina.objects.filter(pk=pg.pk).update(secao=dono)
        feito["paginas"] += 1
    # a reimportação usa as páginas iniciais guardadas na importação aplicada
    imp = ciclo.importacoes.filter(situacao=ImportacaoPDF.APLICADA).order_by("-aplicada_em", "-pk").first()
    if imp:
        ini = {str(s.pk): None for s, _ in atuais}
        ini.update({str(s.pk): n for n, _o, s in marcos})
        ImportacaoPDF.objects.filter(pk=imp.pk).update(resumo=dict(imp.resumo or {}, inicios=ini))
    return feito


# --- ciclo de trabalho e exclusão ---------------------------------------------------------------------------------
@transaction.atomic
def tornar_de_trabalho(ciclo):
    Ciclo.objects.exclude(pk=ciclo.pk).filter(em_trabalho=True).update(em_trabalho=False)
    Ciclo.objects.filter(pk=ciclo.pk).update(em_trabalho=True)


def pode_excluir_ciclo():
    return bool(getattr(settings, "SIRG_PERMITE_EXCLUIR_CICLO", False))


def resumo_do_ciclo(ciclo):
    return {"secoes": ciclo.secoes.count(), "paginas": ciclo.paginas.count(),
            "blocos": Bloco.objects.filter(secao__ciclo=ciclo).count(), "quadros": ciclo.quadros.count(),
            "importacoes": ciclo.importacoes.count()}


def excluir_ciclo(ciclo, confirmacao, user=None, request=None):
    """Apaga o ciclo, tudo o que é dele (seções, páginas, blocos, quadros, valores, comentários) e os arquivos das
    importações de PDF. Só onde a configuração permite (homologação). O histórico de alterações fica guardado."""
    from contas.servicos import registrar
    if not pode_excluir_ciclo():
        raise Recusado("Excluir um relatório só é permitido no ambiente de homologação.")
    if str(confirmacao or "").strip() != str(ciclo.ano):
        raise Recusado(f"Para confirmar, digite o ano-base ({ciclo.ano}).")
    resumo = resumo_do_ciclo(ciclo)
    pastas = [imp.pasta for imp in ciclo.importacoes.all()]
    titulo, ano = ciclo.titulo, ciclo.ano
    with transaction.atomic():
        Ciclo.objects.filter(origem=ciclo).update(origem=None)
        ciclo.delete()
    for p in pastas:
        shutil.rmtree(p, ignore_errors=True)
    registrar("ciclo_excluido", ator=user, descricao=f"{titulo} (ano-base {ano}) excluído na homologação.",
              dados=resumo, request=request)
    return resumo


# --- quadros (2.18, etapa 3) ----------------------------------------------------------------------------------
def _chave_quadro_livre(ciclo, titulo):
    from .models import Quadro
    base = gerar_chave(titulo, 34)
    ch, n = base, 2
    while Quadro.objects.filter(ciclo=ciclo, chave=ch).exists():
        ch, n = f"{base}_{n}", n + 1
    return ch


def _itens(texto):
    """Uma linha por item, sem repetidos e sem linhas em branco."""
    vistos, itens = set(), []
    for t in (texto or "").splitlines():
        t = t.strip().lstrip("-–•*").strip()[:200]
        if t and t.lower() not in vistos:
            vistos.add(t.lower())
            itens.append(t)
    return itens


@transaction.atomic
def criar_quadro_simples(ciclo, *, titulo, secao, linhas, setor=None, tipo="inteiro", modo="anos", anos=None,
                         colunas="", total=False, descricao=""):
    """Quadro de números pela tela de montagem, sem chaves nem fórmulas: um título, as linhas (uma por linha) e as
    colunas (anos da série histórica, que nascem travadas antes do ano-base, ou categorias livres). Fórmulas e regras
    continuam no formulário completo do quadro."""
    from .models import Coluna, Linha, Quadro
    from .servicos import sincronizar_colunas_de_anos
    titulo = (titulo or "").strip()[:255]
    if not titulo:
        raise Recusado("Dê um título ao quadro.")
    if secao is None or secao.ciclo_id != ciclo.pk:
        raise Recusado("Escolha a seção do quadro.")
    rotulos = _itens(linhas)
    if not rotulos:
        raise Recusado("Escreva as linhas do quadro, uma por linha.")
    if tipo not in dict(Quadro.TIPOS):
        tipo = Quadro.INTEIRO
    cats = _itens(colunas) if modo == Quadro.CATEGORIAS else []
    if modo == Quadro.CATEGORIAS and not cats:
        raise Recusado("Escreva as colunas (categorias), uma por linha.")
    q = Quadro.objects.create(
        ciclo=ciclo, secao=secao, chave=_chave_quadro_livre(ciclo, titulo), titulo=titulo, descricao=descricao,
        setor=setor, tipo_valor=tipo, modo_colunas=Quadro.CATEGORIAS if cats else Quadro.ANOS,
        anos_exibidos=max(1, min(int(anos or ciclo.anos_serie or 5), 15)), linha_total=bool(total),
        ordem=secao.quadros.count() + 1)
    usadas = set()
    for i, r in enumerate(rotulos, start=1):
        ch = gerar_chave(r, 40)
        while ch in usadas:
            ch = f"{ch[:36]}_{i}"
        usadas.add(ch)
        Linha.objects.create(quadro=q, ordem=i, chave=ch, rotulo=r)
    if cats:
        usadas = set()
        for i, r in enumerate(cats, start=1):
            ch = gerar_chave(r, 40)
            while ch in usadas:
                ch = f"{ch[:36]}_{i}"
            usadas.add(ch)
            Coluna.objects.create(quadro=q, ordem=i, chave=ch, rotulo=r[:120])
    else:
        sincronizar_colunas_de_anos(q, travar_passado=True)
    return q


# --- PDF do relatório anterior, para consulta (2.18, etapa 3) -------------------------------------------------------
def caminho_pdf_anterior(ciclo):
    from pathlib import Path
    return Path(settings.MEDIA_ROOT) / "referencia" / f"anterior_ciclo_{ciclo.pk}.pdf"


def receber_pdf_anterior(ciclo, arquivo):
    from .importador import TAMANHO_MAXIMO
    if not arquivo:
        raise Recusado("Escolha o arquivo PDF.")
    if not arquivo.name.lower().endswith(".pdf") or arquivo.read(5) != b"%PDF-":
        raise Recusado("O arquivo precisa ser um PDF.")
    arquivo.seek(0)
    if arquivo.size > TAMANHO_MAXIMO:
        raise Recusado(f"O PDF passa de {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
    destino = caminho_pdf_anterior(ciclo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "wb") as f:
        for pedaco in arquivo.chunks():
            f.write(pedaco)


def url_pdf_anterior(ciclo):
    """O PDF do relatório anterior para consulta: o enviado pela tela ou, para o RG 2026, o que vem no código."""
    from django.contrib.staticfiles import finders
    from django.templatetags.static import static
    if caminho_pdf_anterior(ciclo).is_file():
        return reverse("pdf_anterior", args=[ciclo.ano])
    nome = f"referencia/RG{ciclo.ano - 1}.pdf"
    return static(nome) if finders.find(nome) else ""
