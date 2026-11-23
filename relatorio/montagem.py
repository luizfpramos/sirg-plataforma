"""
Montar o relatório do ano (2.18): os passos em ordem, as seções do ciclo e o ciclo de trabalho.

  passos(ciclo)            — os passos da montagem, cada um com a situação e a tela onde se faz
  adicionar_em_lote(...)   — cria capítulos e seções a partir de uma lista colada (ex.: o sumário do PDF)
  mover_secao(...)         — sobe ou desce uma seção entre as irmãs
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

    if not (caps or secs):
        s_sec = p("Seções", "Crie os capítulos e as seções. Dá para colar o sumário do PDF de uma vez.", "falta",
                  reverse("secoes_lista", args=[ano]), "Criar as seções")
    else:
        aviso = f" {sem_setor} seção(ões) sem setor responsável." if sem_setor else ""
        s_sec = p("Seções", f"{caps} capítulo(s) e {secs} seção(ões).{aviso}", "aviso" if sem_setor else "feito",
                  reverse("secoes_lista", args=[ano]), "Ver as seções")

    if n_pag:
        s_pdf = p("PDF diagramado", f"{n_pag} páginas aplicadas ao ciclo.", "feito",
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
    if not n_blocos:
        s_blo = p("Blocos nas páginas", "Os blocos aparecem depois de aplicar o PDF.", "falta",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    else:
        vazios = texto.filter(conteudo="").count()
        txt = f"{n_blocos} bloco(s) nas páginas, {vazios} vazio(s) para os setores."
        if numeros:
            txt += (f" {len(numeros)} texto(s) fixo(s) com número do ano anterior (em laranja no editor): troque a área "
                    f"por um gráfico ou tabela, libere para o setor ou confira.")
        s_blo = p("Blocos nas páginas", txt, "aviso" if numeros else "feito",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    s_atr = p("Atributos dos blocos",
              (f"{sem_descricao} bloco(s) vazio(s) sem a descrição do que escrever." if sem_descricao
               else "Todos os blocos de texto têm descrição.") if n_blocos else "Setor, descrição e tamanho de cada bloco.",
              ("aviso" if sem_descricao else "feito") if n_blocos else "falta",
              reverse("blocos_atributos", args=[ano]), "Definir os atributos")
    s_qua = p("Quadros de números",
              f"{n_quadros} quadro(s). Os gráficos e as tabelas dos blocos vêm daqui." if n_quadros
              else "As tabelas de números que alimentam os gráficos e as tabelas dos blocos.",
              "feito" if n_quadros else "falta", reverse("ciclo", args=[ano]), "Ver os quadros")
    s_col = p("Abrir a coleta",
              f"Situação: {ciclo.get_situacao_display().split(' (')[0].lower()}."
              + ("" if aberto else " Quando tudo estiver pronto, mude para “coleta” para os setores começarem."),
              "feito" if aberto else "falta", reverse("ciclo_editar", args=[ano]), "Situação e prazo")
    return [s_sec, s_pdf, s_blo, s_atr, s_qua, s_col]


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
    Devolve (capítulos, seções, avisos)."""
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("O ciclo está encerrado.")
    siglas = {s.sigla.upper(): s for s in Setor.objects.all()}
    cap_atual = ciclo.secoes.filter(pai__isnull=True).order_by("-ordem", "-id").first()
    ordem_cap = (cap_atual.ordem if cap_atual else 0)
    n_caps = n_secs = 0
    avisos = []
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
        if not linha:
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
    return n_caps, n_secs, avisos


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
