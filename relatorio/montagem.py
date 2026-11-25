"""
Montar o relatório do ano (2.18): os passos em ordem, as seções do ciclo e o ciclo de trabalho.

  passos(ciclo)            — os passos da montagem, cada um com a situação e a tela onde se faz
  ROTEIRO, navegacao(...)  — títulos e telas dos passos, para a barra "Passo N de 8" de cada tela (2.21)
  ler_lista(...), adicionar_em_lote(...) — lê e grava a lista colada de capítulos e seções (ex.: o sumário do PDF),
                             com setores e página; título que já existe é atualizado, não duplicado (2.23)
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

from .formato import qtd
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
    ("Situação e prazo", lambda ano: reverse("ciclo_editar", args=[ano])),
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
        txt = (f"{qtd(len(ativos), 'setor ativo', 'setores ativos')}. Os setores valem para todos os anos: confira se surgiu algum, "
               f"se algum deixou de existir e se cada um tem pessoas cadastradas.")
        if vazios:
            resto = f" e mais {len(vazios) - 8}" if len(vazios) > 8 else ""
            txt += f" Sem ninguém cadastrado: {', '.join(vazios[:8])}{resto}."
        s_set = p("Setores e pessoas", txt, "aviso" if vazios else "feito", ROTEIRO[0][1](ano),
                  "Conferir os setores")

    if not (caps or secs):
        s_sec = p("Seções", "Crie os capítulos e as seções. Dá para colar o sumário do PDF de uma vez.", "falta",
                  reverse("secoes_lista", args=[ano]), "Criar as seções")
    else:
        aviso = f" {qtd(sem_setor, 'seção', 'seções')} sem setor responsável." if sem_setor else ""
        s_sec = p("Seções", f"{qtd(caps, 'capítulo', 'capítulos')} e {qtd(secs, 'seção', 'seções')}.{aviso}", "aviso" if sem_setor else "feito",
                  reverse("secoes_lista", args=[ano]), "Ver as seções")

    if n_pag:
        s_pdf = p("PDF diagramado", f"{qtd(n_pag, 'página aplicada', 'páginas aplicadas')} ao relatório. Seção na página errada? Corrija no "
                                    f"passo 2, em “Página em que cada seção começa”.", "feito",
                  reverse("importar_pdf", args=[ano]), "Ver a importação")
    elif imp and imp.situacao == ImportacaoPDF.PRONTA:
        s_pdf = p("PDF diagramado", "O PDF foi lido. Confira as páginas de cada seção e aplique ao relatório.", "aviso",
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
        s_blo = p("Blocos nas páginas", f"{qtd(n_pag, 'página', 'páginas')} ainda sem blocos. No editor, clique no texto do PDF para "
                  f"criar cada bloco, ou desenhe a área de imagens e gráficos.", "falta",
                  reverse("editor_inicio", args=[ano]), "Criar os blocos")
    elif not n_blocos:
        s_blo = p("Blocos nas páginas", "Os blocos se criam no editor, depois de aplicar o PDF.", "falta",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    else:
        vazios = texto.filter(conteudo="").count()
        txt = f"{qtd(n_blocos, 'bloco', 'blocos')} nas páginas, {qtd(vazios, 'vazio', 'vazios')} para os setores."
        if sem_bloco:
            txt += f" {qtd(sem_bloco, 'página', 'páginas')} ainda sem nenhum bloco."
        if numeros:
            txt += (f" {qtd(len(numeros), 'texto fixo', 'textos fixos')} com número do ano anterior (em laranja no editor): troque a área "
                    f"por um gráfico ou tabela, libere para o setor ou confira.")
        s_blo = p("Blocos nas páginas", txt, "aviso" if (numeros or sem_bloco) else "feito",
                  reverse("editor_inicio", args=[ano]), "Editar os blocos")
    s_atr = p("Atributos dos blocos",
              (f"{qtd(sem_descricao, 'bloco vazio', 'blocos vazios')} sem a descrição do que escrever." if sem_descricao
               else "Todos os blocos de texto têm descrição.") if n_blocos else "Setor, descrição e tamanho de cada bloco.",
              ("aviso" if sem_descricao else "feito") if n_blocos else "falta",
              reverse("blocos_atributos", args=[ano]), "Definir os atributos")
    s_qua = p("Quadros de números",
              f"{qtd(n_quadros, 'quadro', 'quadros')}. Os gráficos e as tabelas dos blocos vêm daqui; os anos anteriores são "
              f"preenchidos pela DGDI." if n_quadros
              else "As tabelas de números que alimentam os gráficos e as tabelas dos blocos.",
              "feito" if n_quadros else "falta", reverse("quadros_lista", args=[ano]), "Quadros de números")
    tem_ant = caminho_pdf_anterior(ciclo).is_file()
    s_ant = p("PDF do relatório anterior (consulta)",
              "Enviado: os setores abrem pelo botão no alto do relatório." if tem_ant
              else ("Opcional. Os setores consultam o relatório publicado no ano anterior ao lado do SiRG."
                    + (f" Enquanto nenhum for enviado, os setores consultam o RG {ciclo.ano - 1} que já vem no sistema."
                       if url_pdf_anterior(ciclo) else "")),
              "feito" if tem_ant else "falta", reverse("pdf_anterior_enviar", args=[ano]),
              "Trocar o PDF" if tem_ant else "Enviar o PDF")
    s_col = p("Situação e prazo",
              f"Situação: {ciclo.get_situacao_display().split(' (')[0].lower()}."
              + ("" if aberto else " Quando tudo estiver pronto, mude para “coleta” para os setores começarem."),
              "feito" if aberto else "falta", reverse("ciclo_editar", args=[ano]), "Situação e prazo")
    return [s_set, s_sec, s_pdf, s_blo, s_atr, s_qua, s_ant, s_col]


# --- seções ------------------------------------------------------------------------------------------------------
# Página no fim da linha (2.23), como no sumário do PDF: "Título ........ 51", "Título<Tab>51", "Título, p. 51",
# "Título p. 51" ou "Título  51" (dois espaços). Um número só com um espaço antes não conta: pode ser parte do título
# ("Metas do PDI para 2026", "Objetivo 4").
_PAGINA_NO_TITULO = re.compile(
    r"^(?P<t>.*?\S)(?:\s*(?:\.{2,}|…+|·{2,}|_{2,})\s*|\t+\s*|\s{2,}|\s*,\s*p(?:ág(?:ina)?)?\.?\s*"
    r"|\s+p(?:ág(?:ina)?)?\.\s*)(?P<n>\d{1,4})\s*$", re.I)
# Um trecho depois de "|" só com a página: "| 51", "| p. 51", "| pág. 51".
_PAGINA_SOZINHA = re.compile(r"^\s*(?:p(?:ág(?:ina)?)?\.?\s*)?(\d{1,4})\s*$", re.I)


def _chave_livre(ciclo, titulo):
    base = gerar_chave(titulo, 34)
    ch, n = base, 2
    while Secao.objects.filter(ciclo=ciclo, chave=ch).exists():
        ch, n = f"{base}_{n}", n + 1
    return ch


def _normal(t):
    """Título para comparar: sem acento, sem caixa e sem espaços repetidos."""
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower())
    return " ".join("".join(ch for ch in t if unicodedata.category(ch) != "Mn").split())


def ler_lista(ciclo, texto):
    """2.23: lê a lista colada sem gravar nada, para a tela mostrar o que vai acontecer antes de confirmar.

    Uma linha por item. Linha comum = capítulo; linha que começa com "-" (ou com recuo) = seção do capítulo acima.
    Depois de "|", opcional: os setores ("| SIGLA, SIGLA") e a página ("| p. 51"); a página também pode vir no fim
    do título, como no sumário ("Título ...... 51"). Um título igual ao de um capítulo (ou de uma seção do mesmo
    capítulo) que já existe atualiza esse item, em vez de criar outro.

    Devolve uma lista de itens {"linha", "tipo" ("capitulo" | "secao"), "titulo", "setores" [Setor], "siglas_faltando"
    [str], "pagina" (int | None), "existente" (Secao | None), "acao" ("criar" | "atualizar" | "igual"), "avisos"}."""
    siglas = {x.sigla.upper(): x for x in Setor.objects.all()}
    caps = {_normal(c.titulo): c for c in ciclo.secoes.filter(pai__isnull=True)}
    filhas = {}
    for f in ciclo.secoes.filter(pai__isnull=False).prefetch_related("setores"):
        filhas.setdefault(f.pai_id, {})[_normal(f.titulo)] = f
    tem_cap = ciclo.secoes.filter(pai__isnull=True).exists()
    cap_atual = None            # o capítulo existente da linha de capítulo acima (None se é novo)
    cap_acima = False           # já houve linha de capítulo nesta lista (ou existe capítulo no relatório)
    vistos = set()
    itens = []
    for n, bruta in enumerate((texto or "").splitlines(), start=1):
        if not bruta.strip():
            continue
        e_secao = bool(re.match(r"^(\s+|\s*[-–•*]\s*)", bruta))
        partes = re.sub(r"^\s*[-–•*]?\s*", "", bruta).rstrip().split("|")
        linha, pagina, setores, faltando, avisos = partes[0].strip(), None, [], [], []
        for parte in partes[1:]:
            m = _PAGINA_SOZINHA.match(parte)
            if m:
                pagina = int(m.group(1))
                continue
            for sg in re.split(r"[,;/ ]+", parte.strip()):
                if not sg:
                    continue
                x = siglas.get(sg.upper())
                if x:
                    setores.append(x)
                else:
                    faltando.append(sg.upper())
                    avisos.append(f"Linha {n}: setor “{sg}” não existe.")
        m = _PAGINA_NO_TITULO.match(linha)
        if m:
            linha, pagina = m.group("t").strip(" .·…_-–"), pagina or int(m.group("n"))
        if not linha:
            itens.append({"linha": n, "tipo": None, "titulo": "", "setores": [], "siglas_faltando": faltando,
                          "pagina": None, "existente": None, "acao": None, "avisos": avisos})
            continue
        titulo = linha[:255]
        if pagina == 0:
            avisos.append(f"Linha {n}: página 0 ignorada.")
            pagina = None
        if e_secao and not (cap_acima or tem_cap):
            avisos.append(f"Linha {n}: “{titulo}” é uma seção, mas não há capítulo acima. Fica como capítulo.")
            e_secao = False
        if e_secao:
            pai_existente = cap_atual if cap_acima else (cap_atual or ciclo.secoes.filter(
                pai__isnull=True).order_by("-ordem", "-id").first())
            existente = filhas.get(pai_existente.pk, {}).get(_normal(titulo)) if pai_existente else None
        else:
            existente = caps.get(_normal(titulo))
            cap_atual, cap_acima = existente, True
        if existente is not None and existente.pk in vistos:
            avisos.append(f"Linha {n}: “{titulo}” aparece de novo na lista; fica só a primeira.")
            existente, acao = None, None
        elif existente is not None:
            vistos.add(existente.pk)
            muda_setores = setores and {x.pk for x in setores} != {x.pk for x in existente.setores.all()}
            muda_pagina = pagina is not None and pagina != existente.pagina_inicio
            acao = "atualizar" if (muda_setores or muda_pagina) else "igual"
        else:
            acao = "criar"
        itens.append({"linha": n, "tipo": "secao" if e_secao else "capitulo", "titulo": titulo, "setores": setores,
                      "siglas_faltando": faltando, "pagina": pagina, "existente": existente, "acao": acao,
                      "avisos": avisos})
    # páginas fora de ordem (seção começando antes da anterior): só aviso, a pessoa confere
    maior = 0
    for it in itens:
        if it["pagina"]:
            if it["pagina"] < maior:
                it["avisos"].append(f"Linha {it['linha']}: página {it['pagina']} vem antes da página da linha anterior "
                                    f"({maior}). Confira a ordem.")
            maior = max(maior, it["pagina"])
    return itens


@transaction.atomic
def adicionar_em_lote(ciclo, texto):
    """Grava a lista colada (ver `ler_lista`). Cria os capítulos e seções novos, atualiza setores e página dos que
    já existem e, se o PDF já foi aplicado, passa as páginas para a seção certa (`mudar_inicios`).
    Devolve {"capitulos", "secoes", "atualizadas", "avisos", "faltando": {sigla: [pk]}, "paginas": {..} | None}."""
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("Este relatório está encerrado.")
    itens = ler_lista(ciclo, texto)
    cap_atual = ciclo.secoes.filter(pai__isnull=True).order_by("-ordem", "-id").first()
    ordem_cap = (ciclo.secoes.filter(pai__isnull=True).order_by("-ordem").values_list("ordem", flat=True).first() or 0)
    n_caps = n_secs = n_atu = 0
    avisos, faltando, paginas = [], {}, {}
    for it in itens:
        avisos += it["avisos"]
        if it["acao"] is None:
            continue
        s = it["existente"]
        if it["acao"] == "criar":
            if it["tipo"] == "secao":
                ordem = (cap_atual.filhas.count() + 1) * 10
                s = Secao.objects.create(ciclo=ciclo, pai=cap_atual, titulo=it["titulo"], ordem=ordem,
                                         chave=_chave_livre(ciclo, it["titulo"]), pagina_inicio=it["pagina"])
                n_secs += 1
            else:
                ordem_cap += 10
                s = Secao.objects.create(ciclo=ciclo, titulo=it["titulo"], ordem=ordem_cap,
                                         chave=_chave_livre(ciclo, it["titulo"]), pagina_inicio=it["pagina"])
                n_caps += 1
            if it["setores"]:
                s.setores.set(it["setores"])
        elif it["acao"] == "atualizar":
            if it["setores"]:
                s.setores.set(it["setores"])
            if it["pagina"] is not None and it["pagina"] != s.pagina_inicio:
                s.pagina_inicio = it["pagina"]
                s.save(update_fields=["pagina_inicio"])
            n_atu += 1
        if it["tipo"] == "capitulo":
            cap_atual = s
        if it["pagina"] is not None:
            paginas[s.pk] = it["pagina"]
        for sg in it["siglas_faltando"]:
            faltando.setdefault(sg, []).append(s.pk)
    feito_pag = None
    if paginas and ciclo.paginas.exists():
        atuais = dict((x.pk, n) for x, n in inicios_das_secoes(ciclo))
        mudar = {pk: n for pk, n in paginas.items() if atuais.get(pk) != n}
        if mudar:
            feito_pag = mudar_inicios(ciclo, mudar)      # Recusado desfaz tudo (transação): a pessoa corrige e tenta de novo
    return {"capitulos": n_caps, "secoes": n_secs, "atualizadas": n_atu, "avisos": avisos, "faltando": faltando,
            "paginas": feito_pag}


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
