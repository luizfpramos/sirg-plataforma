"""
Ajustes que deixam o RG 2026 pronto para os setores, a partir do RG 2025 publicado.

- Cada seção guarda o texto do RG 2025 como referência (com a página do PDF).
- O texto do RG 2025 vira o rascunho de 2026, sem destaques prévios (quem atualiza revisa a seção
  inteira); os números dos quadros viram números vivos e os gráficos entram no meio do texto, como no RG.
- Instalações criadas numa versão anterior recebem os quadros, linhas, regras e gráficos novos
  (`sincronizar_estrutura`) e perdem os destaques amarelos que vieram prontos (`tirar_destaques_previos`).
- O apêndice ganha, por área, a tabela de acompanhamento das metas do PDI para 2026.
- Toda seção tem um trecho de texto, para a pessoa só clicar e escrever.
- Títulos de tabelas e gráficos passam a citar 2026; gráficos com anos fixos avançam um ano.
- Observações de conferência do RG 2025 saem das descrições dos quadros.

Tudo aqui pode rodar mais de uma vez sem duplicar nada, e não mexe em texto que alguém já alterou.
"""
import re
from html import escape

from django.db import transaction

import json
from pathlib import Path

from relatorio import rascunho as R
from relatorio.calculo import Calculadora
from relatorio.html_seguro import limpar
from relatorio.models import Bloco, Coluna, Linha, Quadro, Secao, Valor

PASTA = Path(__file__).resolve().parent


def _textos_rg2025():
    return json.loads((PASTA / "rg2025_texto.json").read_text(encoding="utf-8"))


def _metas_rg2025():
    return json.loads((PASTA / "rg2025_pdi.json").read_text(encoding="utf-8"))


COLUNAS_PDI = [("oe", "Objetivos estratégicos", True), ("status_ant", "Status (dez/{ant})", True),
               ("just_ant", "Justificativa ({ant})", True), ("status", "Status (dez/{ano})", False),
               ("justificativa", "Justificativa ({ano})", False)]


def _apendice_pdi(ciclo):
    """Uma tabela por área: as metas do PDI, com o status e a justificativa do ano anterior (travados,
    para consulta) e as colunas do ano para a área preencher. Devolve quantas metas foram criadas."""
    from contas.models import Setor

    from relatorio.dados_iniciais.rg2025 import AREAS_PDI
    ant, n = ciclo.ano - 1, 0
    metas = _metas_rg2025()
    for area, chave_secao in AREAS_PDI.items():
        s = ciclo.secoes.filter(chave=chave_secao).first()
        if s is None or area not in metas:
            continue
        chave_q = f"{chave_secao}_metas"
        q = Quadro.objects.filter(ciclo=ciclo, chave=chave_q).first()
        if q is None:
            setor = s.setores.first() or Setor.objects.filter(sigla="DGDI").first()
            q = Quadro.objects.create(
                ciclo=ciclo, secao=s, chave=chave_q, ordem=1, titulo=f"Acompanhamento das metas do PDI – {area}",
                descricao=f"Para cada meta, informe o status em dezembro de {ciclo.ano} e a justificativa. "
                          f"O status e a justificativa de {ant} ficam ao lado, para consulta.",
                fonte=setor.sigla if setor else "", setor=setor, tipo_valor=Quadro.TEXTO,
                modo_colunas=Quadro.CATEGORIAS, linha_total=False, coluna_total=False, obrigatorio=True)
            cols = {}
            for k, (ch, rot, travada) in enumerate(COLUNAS_PDI, start=1):
                cols[ch] = Coluna.objects.create(quadro=q, ordem=k, chave=ch, travada=travada,
                                                 rotulo=rot.format(ant=ant, ano=ciclo.ano))
            for k, m in enumerate(metas[area], start=1):
                li = Linha.objects.create(quadro=q, ordem=k, chave=f"m{k}", rotulo=m["meta"][:600],
                                          tipo_valor=Quadro.TEXTO, soma_no_total=False)
                for ch, valor in (("oe", m["oe"]), ("status_ant", m["status"]), ("just_ant", m["justificativa"])):
                    if valor:
                        Valor.objects.create(linha=li, coluna=cols[ch], texto=valor)
                n += 1
            Bloco.objects.create(secao=s, tipo=Bloco.TABELA, ordem=20, quadro=q,
                                 titulo=f"Acompanhamento das metas do PDI {ciclo.ano} – {area}",
                                 config={"colunas": ["oe", "status", "justificativa"]})
        if not s.referencia:
            linhas = "".join(f"<tr><td>{escape(m['oe'])}</td><td>{escape(m['meta'])}</td><td>{escape(m['status'])}</td>"
                             f"<td>{escape(m['justificativa'])}</td></tr>" for m in metas[area])
            s.referencia = limpar(f"<table><tr><th>Obj. estratégicos</th><th>Meta</th><th>Status (dez/{ant})</th>"
                                  f"<th>Justificativa</th></tr>{linhas}</table>")
            s.referencia_fonte = f"RG {ant}, Apêndice"
            s.save(update_fields=["referencia", "referencia_fonte"])
    return n


def _intercalar_graficos(secao, primeiro, resto, preparar, ant):
    """Onde o texto do RG trazia um gráfico ({{GRAFICO:chaves}}), o gráfico vivo do quadro entra
    no meio do texto, como no relatório publicado: texto, gráfico, texto, gráfico..."""
    blocos = list(secao.blocos.order_by("ordem", "id"))
    usados = {primeiro.pk}
    sequencia = [x for x in blocos if x.ordem <= primeiro.ordem and x.pk != primeiro.pk] + [primeiro]
    usados |= {x.pk for x in sequencia}
    for i in range(0, len(resto), 2):
        for chave in resto[i].split(","):
            if chave == "destaques":        # painel de números em destaque (sem quadro próprio)
                g = next((x for x in blocos if x.tipo == Bloco.DESTAQUES and x.pk not in usados), None)
            else:
                g = next((x for x in blocos if x.quadro_id and x.quadro.chave == chave and x.pk not in usados), None)
            if g is not None:
                sequencia.append(g)
                usados.add(g.pk)
        html = resto[i + 1] if i + 1 < len(resto) else ""
        if html.strip():
            novo = Bloco(secao=secao, tipo=Bloco.TEXTO, conteudo=preparar(html), config={"rascunho_rg": ant, SEM_PREVIOS: True})
            novo._change_reason = f"rascunho a partir do RG {ant}"
            sequencia.append(novo)
    sequencia += [x for x in blocos if x.pk not in usados]
    for k, x in enumerate(sequencia, start=1):
        x.ordem = k * 10
        if x.pk:
            Bloco.objects.filter(pk=x.pk).update(ordem=x.ordem)
        else:
            x.save()


_DADOS = ("Comente os números desta seção: o que cresceu, o que caiu e por quê. Destaque as principais conquistas "
          "e os desafios do ano. Para citar um número dos quadros, use o botão Inserir número.")
_PDI_ANTES = ("Na tabela, informe para cada meta o status em dezembro do ano e uma justificativa curta. O status e a "
              "justificativa do ano anterior aparecem ao lado, para consulta.")
_PDI = ("Na tabela abaixo, informe para cada meta o status em dezembro do ano e uma justificativa curta. O que foi "
        "informado no ano anterior aparece logo abaixo de cada meta, para consulta.")
_ORCAMENTO = ("Explique os números do ano: o que foi recebido e executado e as principais variações em relação ao "
              "ano anterior, em linguagem simples.")
ORIENTACOES = {
    "base_juridica": "Liste as normas que criam a instituição e definem sua missão e competências (lei de criação, "
                     "estatuto, regimento geral), com número e data de cada uma.",
    "estrutura_organizacional": "Descreva como a instituição se organiza (conselhos, direção, unidades e campi) e "
                                "indique onde o organograma completo pode ser consultado.",
    "cadeia_valor": "Explique como a instituição transforma recursos (pessoas, orçamento, infraestrutura) em serviços "
                    "para a sociedade: ensino, pesquisa e extensão.",
    "valor_publico": "Mostre os resultados que a sociedade recebeu no ano (formados, pesquisas, ações de extensão, "
                     "atendimentos), de preferência com números.",
    "ambiente_externo": "Fale dos principais públicos atendidos (estudantes, comunidade, empresas, governo), dos "
                        "canais de relacionamento e do que mudou no ano.",
    "sustentabilidade_social": "Apresente as ações de inclusão, permanência estudantil, acessibilidade e "
                               "responsabilidade social do ano.",
    "sustentabilidade_ambiental": "Apresente as ações de gestão ambiental: energia, água, resíduos, compras "
                                  "sustentáveis e metas do plano de logística sustentável.",
    "governanca": "Descreva as instâncias de governança (conselhos e comitês) e as principais decisões e melhorias "
                  "do ano.",
    "gestao_estrategica": "Relacione os objetivos do PDI aos resultados do ano e explique os principais avanços e "
                          "atrasos.",
    "gestao_riscos": "Apresente os principais riscos que podem afetar os objetivos da instituição e o que está sendo "
                     "feito para tratá-los.",
    "conflito_interesses": "Informe as ações de prevenção, os canais de consulta e denúncia e os números do ano, sem "
                           "identificar pessoas.",
    "assedio": "Informe as ações de prevenção, os canais de acolhimento e denúncia e os números do ano, sem "
               "identificar pessoas.",
    "swot": "Liste as forças, fraquezas, oportunidades e ameaças identificadas pela gestão.",
    "areas_finalisticas": "Texto de abertura das áreas finalísticas: como estão organizadas e os destaques gerais do "
                          "ano (por exemplo, avaliações externas como o IGC).",
    "desafios_perspectivas": "Liste os principais desafios da gestão orçamentária e financeira e as iniciativas "
                             "prioritárias para enfrentá-los.",
    "dirigentes": "Confira nomes e cargos de todos os dirigentes em dezembro do ano do relatório.",
    "orgaos_controle": "Liste as recomendações e determinações do TCU, da CGU e de outros órgãos de controle no ano e "
                       "as providências adotadas.",
}
for _ch in ("destaques_orcamentarios", "execucao_orcamentaria", "restos_a_pagar", "receitas", "custos", "contabeis"):
    ORIENTACOES[_ch] = _ORCAMENTO

SEM_PREVIOS = "sem_destaque_previo"
MARCA = re.compile(r'<mark class="atualizar"(?: data-orig="([^"]*)")?>(.*?)</mark>', re.S)


def tirar_destaques_previos(ciclo):
    """Tira, uma única vez por trecho, os destaques amarelos que o rascunho do RG 2025 trazia prontos
    (versão 2.1). O texto fica como está; avisos de figura viram itálico. Destaques que as pessoas
    fizerem depois com o marca-texto não são tocados. Devolve quantos destaques saíram."""
    n = 0
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO):
        cfg = dict(b.config or {})
        if cfg.get(SEM_PREVIOS):
            continue
        cont = b.conteudo or ""
        achados = len(MARCA.findall(cont))
        if achados:
            cont = MARCA.sub(lambda m: f"<em>{m.group(2)}</em>" if m.group(1) == "figura" else m.group(2), cont)
        cfg[SEM_PREVIOS] = True
        # atualização direta: não conta como edição de ninguém nem cria versão nova a cada execução
        Bloco.objects.filter(pk=b.pk).update(conteudo=cont, config=cfg)
        n += achados
    return n


# --- nome da instituição: CEFET-MG passa a UFCIMG --------------------------------------------------
SECOES_SETORES_CORRIGIDOS = ("quem_somos", "ambiente_externo")


def _migrar_orc_loa(ciclo, vivos):
    """O quadro "orc_loa" (só a dotação por grupo) virou a coluna Dotação de "orc_execucao" (Tabela 1 e
    Gráfico 1). O que já foi digitado passa para lá; o quadro antigo sai se nenhum texto cita os números dele."""
    antigo, novo = vivos.get("orc_loa"), vivos.get("orc_execucao")
    if antigo is None or novo is None:
        return
    col = novo.colunas.filter(chave="dotacao").first()
    linhas = {x.chave: x for x in novo.linhas.all()}
    for v in Valor.objects.filter(linha__quadro=antigo, coluna__ano=ciclo.ano).select_related("linha"):
        li = linhas.get(v.linha.chave)
        if li is not None and col is not None and v.numero is not None and \
                not Valor.objects.filter(linha=li, coluna=col).exists():
            Valor.objects.create(linha=li, coluna=col, numero=v.numero, atualizado_por=v.atualizado_por)
    citado = Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO, conteudo__contains='data-ref="orc_loa.').exists()
    if not citado:
        Bloco.objects.filter(quadro=antigo).delete()
        antigo.delete()
        vivos.pop("orc_loa", None)


NOME_ANTIGO, SIGLA_ANTIGA = "Centro Federal de Educação Tecnológica de Minas Gerais", "CEFET-MG"
NOME_NOVO, SIGLA_NOVA = "Universidade Federal de Ciência e Inovação de Minas Gerais", "UFCIMG"
_ARTIGO = {"o": "a", "do": "da", "no": "na", "ao": "à", "pelo": "pela"}
_NOME_COM_SIGLA = re.compile(r"(?:\b(o|do|no|ao|pelo)(\s+))?(Centro Federal de Educação Tecnológica de Minas Gerais|"
                             r"CENTRO FEDERAL DE EDUCAÇÃO TECNOLÓGICA DE MINAS GERAIS)(\s*[–—-]\s*)CEFET-MG\b",
                             re.IGNORECASE)


def _trocar_nome(m):
    artigo, espaco, nome, traco = m.group(1), m.group(2) or "", m.group(3), m.group(4)
    novo = NOME_NOVO.upper() if nome.isupper() else NOME_NOVO
    if artigo:
        a = _ARTIGO[artigo.lower()]
        artigo = a.upper() if artigo.isupper() else (a[0].upper() + a[1:] if artigo[0].isupper() else a)
    return f"{artigo or ''}{espaco}{novo}{traco}{SIGLA_NOVA}"


def trocar_nome_no_texto(html):
    """“Centro Federal de Educação Tecnológica de Minas Gerais – CEFET-MG” (nome com a sigla, em
    maiúsculas ou não) vira “Universidade Federal de Ciência e Inovação de Minas Gerais – UFCIMG”,
    acertando o artigo (o → a, do → da...). Menções históricas, sem a sigla junto, ficam como estão."""
    return _NOME_COM_SIGLA.sub(_trocar_nome, html or "")


def renomear_instituicao(ciclo):
    """Troca o nome nos dados da instituição (capa, telas, Word) e nos textos do relatório.
    Devolve quantos trechos de texto mudaram."""
    from contas.models import Instituicao
    inst = Instituicao.atual()
    if inst.nome.strip() == NOME_ANTIGO or inst.sigla.strip() == SIGLA_ANTIGA:
        inst.nome, inst.sigla = NOME_NOVO, SIGLA_NOVA
        inst.save(update_fields=["nome", "sigla"])
    # Nos textos, cada menção ao CEFET-MG (ou ao nome por extenso) fica em amarelo para quem escreve escolher:
    # CEFET-MG (fato histórico) ou UFCIMG (a instituição hoje). Isso é feito uma vez por trecho
    # (config "nome_inst"), para que a escolha "manter CEFET-MG" não volte a ser marcada na atualização seguinte.
    from relatorio import nome_inst
    n = 0
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO):
        cfg = dict(b.config or {})
        if cfg.get("nome_inst"):
            continue
        # o nome por extenso COM a sigla junto ("Centro Federal ... – CEFET-MG") é a designação formal da instituição
        # (capa, dirigentes, expediente) e passa direto para UFCIMG; o resto fica para quem escreve decidir
        novo, k = nome_inst.marcar(trocar_nome_no_texto(b.conteudo))
        cfg["nome_inst"] = True
        Bloco.objects.filter(pk=b.pk).update(conteudo=novo, config=cfg)
        n += 1 if k else 0
    trocar_sigla_nos_rotulos(ciclo)
    return n


def trocar_sigla_nos_rotulos(ciclo):
    """Nos títulos de seções, quadros, tabelas e gráficos e nos nomes das linhas do ciclo, “CEFET-MG” passa a
    “UFCIMG” (ex.: “Bolsas stricto sensu com recursos da UFCIMG”). As metas do PDI ficam com o texto original
    do PDI 2023–2027, e os textos ficam com quem escreve (o nome completo com a sigla já foi trocado)."""
    def troca(t):
        if not t or SIGLA_ANTIGA not in t:
            return t
        for ant, nov in (("do " + SIGLA_ANTIGA, "da " + SIGLA_NOVA), ("no " + SIGLA_ANTIGA, "na " + SIGLA_NOVA),
                         ("pelo " + SIGLA_ANTIGA, "pela " + SIGLA_NOVA), ("ao " + SIGLA_ANTIGA, "à " + SIGLA_NOVA),
                         ("o " + SIGLA_ANTIGA, "a " + SIGLA_NOVA)):
            t = re.sub(r"\b" + re.escape(ant) + r"\b", nov, t)
        return t.replace(SIGLA_ANTIGA, SIGLA_NOVA)
    n = 0
    for modelo, campos, filtro in ((Secao, ("titulo",), {"ciclo": ciclo}),
                                   (Quadro, ("titulo", "descricao"), {"ciclo": ciclo}),
                                   (Linha, ("rotulo",), {"quadro__ciclo": ciclo}),
                                   (Bloco, ("titulo",), {"secao__ciclo": ciclo})):
        qs = modelo.objects.filter(**filtro)
        if modelo is Linha:
            qs = qs.exclude(quadro__chave__startswith="pdi_")
        for obj in qs:
            mud = {c: troca(getattr(obj, c)) for c in campos if troca(getattr(obj, c)) != getattr(obj, c)}
            if mud:
                modelo.objects.filter(pk=obj.pk).update(**mud)
                n += 1
    return n


# --- "<sigla> em números": objetivos estratégicos (minuta do RG 2025, 26/03/2026) -----------------
OBJETIVOS = [
    "Assegurar a oferta de educação tecnológica de excelência, inclusiva e integral, para formar cidadãos críticos, "
    "éticos e comprometidos com o desenvolvimento social.",
    "Ampliar a oferta e aprimorar a qualidade e a efetividade do ensino, orientando-o por uma perspectiva da educação "
    "integral do aluno.",
    "Ampliar e fortalecer o sistema interno de pesquisa, desenvolvimento e inovação (PD&I), articulando-o às demandas "
    "da sociedade e do setor produtivo.",
    "Ampliar e fortalecer a extensão promovendo interações dialógicas com os setores da sociedade e contribuindo para "
    "seu desenvolvimento socioeconômico, artístico e cultural.",
    "Aprimorar a gestão de currículos e da aprendizagem, promovendo práticas pedagógicas que propiciem a integração do "
    "ensino, da pesquisa, da extensão e das atividades educacionais complementares em prol do desenvolvimento integral "
    "do aluno.",
    "Assegurar as condições para o acesso, a permanência e o êxito dos alunos, suprindo suas necessidades nas "
    "perspectivas da equidade, da inclusão, do pleno desenvolvimento do estudante e da inserção profissional.",
    "Ampliar e fortalecer a cooperação acadêmica internacional, promovendo o intercâmbio científico e tecnológico e a "
    "mobilidade de pessoas, e fomentando o multiculturalismo.",
    "Ampliar e desenvolver os canais de comunicação com a comunidade interna e com a sociedade, fomentando a "
    "participação dos alunos, servidores, colaboradores e dos segmentos sociais no desenvolvimento da instituição, e "
    "assegurando a ampla divulgação dos resultados de valor alcançados.",
    "Aprimorar a governança institucional, fortalecendo os mecanismos de controle interno, de gestão de riscos e "
    "integridade, de monitoramento e avaliação, de participação e controle social nas ações institucionais, e "
    "assegurando o acesso à informação e à transparência pública.",
    "Aprimorar a gestão da instituição, fortalecendo os mecanismos de planejamento, execução, controle e avaliação das "
    "ações, de gestão por processos e resultados, promovendo a modernização organizacional e o uso de recursos "
    "tecnológicos na gestão.",
    "Aperfeiçoar a gestão de pessoas – comprometida com a capacitação profissional, com o desenvolvimento de pessoas, "
    "com a saúde e qualidade de vida dos servidores e colaboradores –, e otimizar a gestão do quadro de pessoal da "
    "instituição.",
    "Ampliar e modernizar a infraestrutura de TI e aprimorar a oferta de serviços de TI para o ensino, a pesquisa, a "
    "extensão e a gestão da instituição, assegurando a qualidade e a continuidade dos serviços, e fomentando a "
    "transformação digital da instituição.",
    "Expandir e modernizar a infraestrutura física, assegurando sua usabilidade, e aperfeiçoar a gestão dos espaços "
    "físicos administrativos e acadêmicos, aumentando sua efetividade e fomentando o uso compartilhado destes recursos.",
    "Otimizar a gestão orçamentária e financeira, favorecendo a execução do planejamento estratégico institucional e "
    "assegurando efetividade no uso dos recursos financeiros, e aumentar a eficiência na captação de recursos "
    "extraordinários.",
]


def _html_objetivos(nome, ano):
    h = f"<p>Objetivos estratégicos da {escape(nome)} para {ano}</p>"
    for i, t in enumerate(OBJETIVOS, start=1):
        h += f"<h4>OBJETIVO ESTRATÉGICO {i}</h4><p>OE-{i} – {escape(t)}</p>"
    return h


def secao_em_numeros(ciclo):
    """Cria, na Apresentação, a seção “<sigla> em números” com os 14 objetivos estratégicos (logo depois da
    mensagem da dirigente máxima). Devolve 1 se criou."""
    from contas.models import Instituicao, Setor
    from relatorio.models import Secao
    if ciclo.secoes.filter(chave="em_numeros").exists():
        return 0
    apres = ciclo.secoes.filter(chave="apresentacao").first()
    if apres is None:
        return 0
    inst = Instituicao.atual()
    irmas = list(apres.filhas.order_by("ordem", "id"))
    s = Secao.objects.create(ciclo=ciclo, pai=apres, chave="em_numeros", titulo=f"{inst.sigla} em números",
                             orientacao="Confira os objetivos estratégicos do PDI vigente. Se quiser, acrescente os "
                                        "principais números do ano com o botão Inserir número.")
    dgdi = Setor.objects.filter(sigla="DGDI").first()
    if dgdi:
        s.setores.set([dgdi])
    pos = next((k for k, x in enumerate(irmas) if x.chave == "mensagem"), len(irmas) - 1) + 1
    irmas.insert(pos, s)
    for k, x in enumerate(irmas, start=1):
        Secao.objects.filter(pk=x.pk).update(ordem=k * 10)
    ant = ciclo.ano - 1
    s.referencia = limpar(_html_objetivos(NOME_ANTIGO, ant))
    s.referencia_fonte = f"RG {ant} (minuta de 26/03/{ant + 1})"
    s.save(update_fields=["referencia", "referencia_fonte"])
    Bloco.objects.create(secao=s, tipo=Bloco.TEXTO, ordem=10, conteudo=limpar(_html_objetivos(inst.nome, ciclo.ano)),
                         config={SEM_PREVIOS: True})
    return 1


# --- instalações criadas numa versão anterior ----------------------------------------------------
def _copiar_linha(li, nq, cols_por_ano):
    nl = Linha.objects.create(quadro=nq, ordem=li.ordem, chave=li.chave, rotulo=li.rotulo, formula=li.formula,
                              tipo_valor=li.tipo_valor, minimo=li.minimo, maximo=li.maximo,
                              soma_no_total=li.soma_no_total)
    for v in li.valores.select_related("coluna"):
        if not v.coluna.ano:
            continue      # quadro por categorias: os valores são do ano anterior e não passam para o novo ciclo
        c = cols_por_ano.get(v.coluna.ano)
        if c is not None:
            Valor.objects.create(linha=nl, coluna=c, numero=v.numero, texto=v.texto, justificativa=v.justificativa)
    return nl


def _copiar_quadro(q, ciclo, secao):
    from relatorio.servicos import sincronizar_colunas_de_anos
    nq = Quadro.objects.create(
        ciclo=ciclo, secao=secao, ordem=q.ordem, chave=q.chave, titulo=q.titulo, descricao=q.descricao,
        fonte=q.fonte, setor=q.setor, tipo_valor=q.tipo_valor, casas_decimais=q.casas_decimais,
        modo_colunas=q.modo_colunas, anos_exibidos=q.anos_exibidos, linha_total=q.linha_total,
        coluna_total=q.coluna_total, rotulo_total=q.rotulo_total, obrigatorio=q.obrigatorio,
        variacao_alerta=q.variacao_alerta)
    if q.modo_colunas == Quadro.ANOS:
        sincronizar_colunas_de_anos(nq)
        nq.colunas.filter(ano__lt=ciclo.ano).update(travada=True)
        cols = {c.ano: c for c in nq.colunas.all()}
    else:
        cols = {c.chave: Coluna.objects.create(quadro=nq, ordem=c.ordem, chave=c.chave, rotulo=c.rotulo, ano=None,
                                               travada=c.travada) for c in q.colunas.all()}
    for li in q.linhas.all():
        _copiar_linha(li, nq, cols)
    return nq


def _ano_no_bloco(titulo, cfg, ano):
    """Mesmo ajuste de ano que `ajustar` faz nos títulos e colunas dos blocos."""
    ant = str(ano - 1)
    titulo = (titulo or "").replace(ant, str(ano))
    cols = (cfg or {}).get("colunas") or []
    anos = [int(m.group(1)) for c in cols for m in [COLUNA_ANO.match(c)] if m]
    if cols and len(anos) == len(cols) and max(anos) == ano - 1:
        cfg = dict(cfg, colunas=[f"a{a + 1}" for a in anos])
    return titulo, cfg or {}


@transaction.atomic
def _mexido_por_alguem(obj):
    """Alguém mudou este registro pela plataforma (há histórico com usuário)?"""
    return obj.history.filter(history_user__isnull=False).exists()


def sincronizar_estrutura(ciclo):
    """Traz para um RG 2026 já em uso o que versões novas acrescentaram à estrutura do RG 2025:
    quadros e linhas novos (com o histórico publicado), regras, rótulos e os gráficos no formato do RG.
    Nada que os setores digitaram é apagado. Pode rodar várias vezes (o que já está igual fica)."""
    from relatorio.models import Ciclo, Regra
    from relatorio.dados_iniciais import rg2025
    feito = {"quadros": 0, "linhas": 0, "regras": 0, "secoes_graficos": 0, "movidos": 0}
    if Ciclo.objects.filter(ano=ciclo.ano - 1).exists():
        return feito          # há um ciclo anterior real: a estrutura vem dele, não do RG 2025 embutido
    base = rg2025.carregar()
    try:
        secoes = {x.chave: x for x in ciclo.secoes.all()}
        vivos = {x.chave: x for x in ciclo.quadros.all()}
        # quadros e linhas
        for q in base.quadros.select_related("secao").order_by("ordem", "id"):
            vq = vivos.get(q.chave)
            if vq is None:
                if q.secao.chave in secoes:
                    vivos[q.chave] = _copiar_quadro(q, ciclo, secoes[q.secao.chave])
                    feito["quadros"] += 1
                continue
            if vq.secao.chave != q.secao.chave and q.secao.chave in secoes:
                vq.secao = secoes[q.secao.chave]       # quadro que mudou de seção (ex.: estava em "Quem somos")
                vq.save(update_fields=["secao"])
                feito["movidos"] += 1
            if q.linha_total and not vq.linha_total:
                vq.linha_total = True
                vq.save(update_fields=["linha_total"])
            if vq.modo_colunas == Quadro.ANOS:
                cols = {c.ano: c for c in vq.colunas.all()}
            else:
                cols = {c.chave: c for c in vq.colunas.all()}
            linhas = {x.chave: x for x in vq.linhas.all()}
            for li in q.linhas.all():
                vl = linhas.get(li.chave)
                if vl is None:
                    _copiar_linha(li, vq, cols)
                    feito["linhas"] += 1
                elif vl.rotulo != li.rotulo or (vl.formula != li.formula and (vl.formula or li.formula)):
                    if _mexido_por_alguem(vl):
                        # o Master mudou o nome ou a fórmula na plataforma (ex.: curso de 2026): fica como está
                        feito.setdefault("preservadas", []).append(f"{vq.chave}.{vl.chave}")
                        continue
                    vl.rotulo, vl.formula = li.rotulo, li.formula
                    vl.save(update_fields=["rotulo", "formula"])
        _migrar_orc_loa(ciclo, vivos)
        # setores de seções que estavam errados na versão anterior (ex.: DPG e DTI em "Quem somos")
        for sch in SECOES_SETORES_CORRIGIDOS:
            vs, bs = secoes.get(sch), base.secoes.filter(chave=sch).first()
            if vs is not None and bs is not None:
                certos = set(bs.setores.values_list("sigla", flat=True))
                if set(vs.setores.values_list("sigla", flat=True)) != certos:
                    from contas.models import Setor
                    vs.setores.set(Setor.objects.filter(sigla__in=certos))
        for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO, conteudo__contains="<h4>Obras "):
            novo = R.obras_em_cartoes(b.conteudo)
            if novo != b.conteudo:
                Bloco.objects.filter(pk=b.pk).update(conteudo=novo)
        # regra nova só entra se não existe (pela conta, não pela descrição) e se ninguém a apagou de propósito
        def _assinatura(qch, r):
            return (qch, r.esquerda.strip(), r.operador, r.direita.strip())
        existentes = {_assinatura(r.quadro.chave if r.quadro else "", r) for r in
                      Regra.objects.filter(ciclo=ciclo).select_related("quadro")}
        existentes |= set(Regra.objects.filter(ciclo=ciclo).values_list("descricao", flat=True))
        apagadas = set(Regra.history.filter(ciclo_id=ciclo.pk, history_type="-", history_user__isnull=False)
                       .values_list("esquerda", "direita"))
        for r in base.regras.select_related("quadro"):
            if (_assinatura(r.quadro.chave, r) not in existentes and r.descricao not in existentes
                    and (r.esquerda, r.direita) not in apagadas and r.quadro.chave in vivos):
                Regra.objects.create(ciclo=ciclo, quadro=vivos[r.quadro.chave], descricao=r.descricao,
                                     esquerda=r.esquerda, operador=r.operador, direita=r.direita,
                                     tolerancia=r.tolerancia, escopo=r.escopo, severidade=r.severidade, ativa=r.ativa)
                feito["regras"] += 1
        # tabelas, gráficos e destaques de cada seção, no formato do RG publicado
        textos = _textos_rg2025()
        for sch in rg2025.MONTAGEM:
            vs = secoes.get(sch)
            bs = base.secoes.filter(chave=sch).first()
            if vs is None or bs is None:
                continue
            modelo, antes = [], set()
            base_txt = bs.blocos.filter(tipo=Bloco.TEXTO).order_by("ordem", "id").first()
            for b in bs.blocos.exclude(tipo=Bloco.TEXTO).select_related("quadro").order_by("ordem", "id"):
                titulo, cfg = _ano_no_bloco(b.titulo, b.config, ciclo.ano)
                if base_txt is not None and b.ordem < base_txt.ordem:
                    antes.add(len(modelo))      # no RG, vem antes do texto (ex.: os números em destaque)
                modelo.append((b.tipo, b.quadro.chave if b.quadro else None, titulo, cfg))
            atuais = list(vs.blocos.exclude(tipo=Bloco.TEXTO).select_related("quadro").order_by("ordem", "id"))
            if [(b.tipo, b.quadro.chave if b.quadro else None, b.titulo,
                 {k: v for k, v in (b.config or {}).items() if k != "caixa"}) for b in atuais] == modelo:
                continue
            if vs.blocos.filter(pagina__isnull=False).exists():
                # 2.13: a seção já está nas páginas do RG (gráficos no lugar, texto em caixas): não refaz nada
                continue
            if any(_mexido_por_alguem(b) for b in atuais) or Bloco.history.filter(
                    secao_id=vs.pk, history_user__isnull=False).exclude(tipo=Bloco.TEXTO).exists():
                # o Master incluiu, apagou ou ajustou tabela/gráfico nesta seção: não refaz nada aqui
                feito.setdefault("secoes_preservadas", []).append(sch)
                continue
            for b in atuais:
                b.delete()
            txt = list(vs.blocos.filter(tipo=Bloco.TEXTO).order_by("ordem", "id"))
            novos = [Bloco(secao=vs, tipo=t, quadro=vivos.get(qch), titulo=tit, config=cfg)
                     for t, qch, tit, cfg in modelo]
            sequencia = [b for k, b in enumerate(novos) if k in antes] + txt + \
                        [b for k, b in enumerate(novos) if k not in antes]
            for k, b in enumerate(sequencia, start=1):
                b.ordem = k * 10
                if b.pk:
                    Bloco.objects.filter(pk=b.pk).update(ordem=b.ordem)
                else:
                    b.save()
            feito["secoes_graficos"] += 1
            # texto ainda intacto (ninguém editou): refaz o rascunho com os gráficos no meio do texto
            d = textos.get(sch)
            if d and txt and all(t.atualizado_por_id is None for t in txt) and R.GRAFICO.search(d["html"]):
                b0 = txt[0]
                for t in txt[1:]:       # trechos que a versão anterior intercalou entre os gráficos antigos
                    t.delete()
                ini, fim = d["paginas"]
                pags = f"{ini}" if ini == fim else f"{ini}–{fim}"
                calc = Calculadora(ciclo)
                partes = R.GRAFICO.split(d["html"])
                b0.conteudo = limpar(R.rascunho(partes[0], calc, ciclo.ano - 1, pags))
                b0.config = dict(b0.config or {}, rascunho_rg=ciclo.ano - 1, **{SEM_PREVIOS: True})
                b0.config.pop("nome_inst", None)     # texto novo: as menções ao CEFET-MG são marcadas de novo
                b0._change_reason = "rascunho refeito com os gráficos no meio do texto (v2.2)"
                b0.save()
                _intercalar_graficos(vs, b0, partes[1:],
                                     lambda h: limpar(R.rascunho(h, calc, ciclo.ano - 1, pags)), ciclo.ano - 1)
            del novos
    finally:
        base.delete()
    return feito


NOTAS_2025 = re.compile(r"RG 2025|^Conferir|^Atenção: no RG")
COLUNA_ANO = re.compile(r"^a(\d{4})$")


# seções cujo texto é escrito do zero todo ano (não vem rascunho do relatório anterior)
TEXTO_SEMPRE_NOVO = ("mensagem",)
ORIENTACAO_MENSAGEM = ("Texto escrito pela dirigente máxima a cada ano: começa em branco. Apresente os principais "
                       "resultados do ano, os desafios e as perspectivas, com a assinatura da dirigente. "
                       "A mensagem do ano anterior pode ser consultada, mas não é ponto de partida.")
ORIENTACOES["mensagem"] = ORIENTACAO_MENSAGEM


@transaction.atomic
def ajustar(ciclo):
    """Aplica os ajustes ao ciclo (2026). Devolve um resumo do que mudou."""
    feito = {"referencias": 0, "rascunhos": 0, "trechos_novos": 0, "titulos": 0, "descricoes": 0, "orientacoes": 0,
             "metas_pdi": 0, "destaques_retirados": 0, "nome_trocado": 0, "em_numeros": 0}
    ano_ant = str(ciclo.ano - 1)

    # 1. toda seção (e capítulo com texto no RG 2025) tem ao menos um trecho de texto
    textos = _textos_rg2025()
    for s in ciclo.secoes.all():
        if (s.pai_id is None and s.chave not in textos) or s.chave.startswith("pdi_"):
            continue      # capítulo sem texto de abertura; apêndice: só a tabela de metas
        if not s.blocos.filter(tipo=Bloco.TEXTO).exists():
            Bloco.objects.create(secao=s, tipo=Bloco.TEXTO, ordem=5, conteudo="", config={"modelo": True, SEM_PREVIOS: True})
            feito["trechos_novos"] += 1

    # 2. texto do RG 2025: referência na seção e rascunho de 2026 no primeiro trecho (se ninguém o alterou)
    calc = Calculadora(ciclo)
    ant = ciclo.ano - 1
    for s in ciclo.secoes.all():
        d = textos.get(s.chave)
        if not d:
            continue
        ini, fim = d["paginas"]
        pags = f"{ini}" if ini == fim else f"{ini}–{fim}"
        ref = limpar(R.referencia(d["html"], ant, pags))
        fonte = f"RG {ant}, p. {pags}"
        if s.referencia != ref or s.referencia_fonte != fonte:
            s.referencia, s.referencia_fonte = ref, fonte
            s.save(update_fields=["referencia", "referencia_fonte"])
            feito["referencias"] += 1
        b = s.blocos.filter(tipo=Bloco.TEXTO).order_by("ordem", "id").first()
        if s.chave in TEXTO_SEMPRE_NOVO:
            # a mensagem da dirigente máxima é escrita de novo a cada ano: começa em branco (se alguém já
            # escreveu nela, fica como está); o texto do ano anterior continua só como consulta
            if b is not None and b.pagina_id is None and b.atualizado_por_id is None and b.conteudo.strip():
                b.conteudo = ""
                b.config = {"texto_novo": True, SEM_PREVIOS: True, "nome_inst": True}
                b._change_reason = "a mensagem da dirigente começa em branco a cada ano"
                b.save()
                for extra in s.blocos.filter(tipo=Bloco.TEXTO, atualizado_por__isnull=True).exclude(pk=b.pk):
                    extra.delete()
                feito["mensagem_em_branco"] = 1
            continue
        if b is not None and b.atualizado_por_id is None and not (b.config or {}).get("rascunho_rg"):
            tudo = s.chave in ("dirigentes", "expediente")
            partes = R.GRAFICO.split(d["html"])      # texto, gráficos, texto, gráficos, texto...
            b.conteudo = limpar(R.rascunho(partes[0], calc, ant, pags, tudo=tudo))
            b.config = {"rascunho_rg": ant, SEM_PREVIOS: True}
            b._change_reason = f"rascunho a partir do RG {ant}"
            b.save()
            feito["rascunhos"] += 1
            if len(partes) > 1:
                _intercalar_graficos(s, b, partes[1:], lambda h: limpar(R.rascunho(h, calc, ant, pags, tudo=tudo)),
                                     ant)

    # apêndice: até a 2.11, metas do PDI por área (RG 2025); desde a 2.12, a planilha de metas de 2026
    if not Quadro.objects.filter(ciclo=ciclo, chave=METAS_2026).exists():
        feito["metas_pdi"] = _apendice_pdi(ciclo)
    feito["metas_2026"] = apendice_metas_2026(ciclo)
    if feito["metas_2026"]:
        feito["metas_pdi"] = 0          # as tabelas por área do RG 2025 foram trocadas pela planilha de 2026
    # 2.13: o relatório nas páginas do RG publicado (uma vez): caixas de texto, gráficos e tabelas no lugar
    from relatorio import paginas as PG
    feito["paginas"] = PG.criar_paginas(ciclo)
    from relatorio import paineis
    feito["paineis"] = paineis.aplicar_paineis(ciclo)
    if feito["paginas"].get("paginas"):
        feito.pop("mensagem_em_branco", None)      # a mensagem fica como está na página (é o ponto de partida)
    # instalações anteriores à 2.2: os destaques amarelos que vieram prontos saem (o texto fica)
    feito["destaques_retirados"] = tirar_destaques_previos(ciclo)
    # novo nome da instituição e a seção "<sigla> em números" (objetivos estratégicos)
    feito["nome_trocado"] = renomear_instituicao(ciclo)
    # regras que apontavam para a coluna fixa do ano anterior (ex.: ri_mobilidade.entrada.a2025) comparavam os
    # números de 2026 com os de 2025: passam a usar a coluna do ano do relatório (".atual")
    from relatorio.models import Regra
    for rg in Regra.objects.filter(ciclo=ciclo):
        esq = re.sub(rf"\.a{ciclo.ano - 1}$", ".atual", rg.esquerda or "")
        dir_ = re.sub(rf"\.a{ciclo.ano - 1}$", ".atual", rg.direita or "")
        if (esq, dir_) != (rg.esquerda, rg.direita):
            Regra.objects.filter(pk=rg.pk).update(esquerda=esq, direita=dir_,
                                                  descricao=re.sub(rf"de {ciclo.ano - 1}$", "do ano", rg.descricao))
    Quadro.objects.filter(ciclo=ciclo, chave="ouv_lai", casas_decimais=1).update(casas_decimais=2)   # 90,48%, como o RG
    Quadro.objects.filter(ciclo=ciclo, chave="ri_mobilidade_nivel", titulo__contains=" em 2025 ").update(
        titulo="Alunos em mobilidade no ano, por nível")
    # fonte única: a dotação atualizada da LOA vem da Tabela 1 (antes eram dois números para a mesma coisa)
    Linha.objects.filter(quadro__ciclo=ciclo, quadro__chave="orc_lei", chave="atualizado", formula="").update(
        formula="orc_execucao.total.dotacao")
    # tabelas e gráficos do RG anterior colados no texto (com o aviso “[Figura do RG ...]”) quando o sistema já
    # monta o mesmo objeto sozinho: sai a cópia, fica o automático (vale também para textos já editados)
    automaticos = {R.chave_objeto(b.titulo) for b in Bloco.objects.filter(secao__ciclo=ciclo).exclude(tipo=Bloco.TEXTO)}
    automaticos.discard(None)
    feito["duplicados_tirados"] = 0
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO):
        novo, k = R.tirar_duplicados(b.conteudo, automaticos)
        if k:
            Bloco.objects.filter(pk=b.pk).update(conteudo=novo)
            feito["duplicados_tirados"] += k
    # números do texto escritos como o RG escreve ("R$ 570,87 milhões") passam a ser ligados aos quadros, nos
    # textos que ninguém editou ainda (num texto editado, o número pode ser uma citação de propósito do ano anterior)
    feito["numeros_ligados"] = 0
    idx = R.indice_de_valores(Calculadora(ciclo), ciclo.ano - 1)
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO, atualizado_por__isnull=True):
        if not (b.config or {}).get("rascunho_rg") or not b.conteudo:
            continue
        novo, k = R.religar(b.conteudo, idx)
        if k > 0:
            Bloco.objects.filter(pk=b.pk).update(conteudo=novo)
            feito["numeros_ligados"] += k
    # números de normas e processos (nº 198/2022) que tinham sido ligados por engano a um dado de mesmo valor
    feito["ligacoes_desfeitas"] = 0
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO, conteudo__contains="sirg-num"):
        novo, k = R.desligar_identificadores(b.conteudo)
        if k:
            Bloco.objects.filter(pk=b.pk).update(conteudo=novo)
            feito["ligacoes_desfeitas"] += k
    feito["em_numeros"] = secao_em_numeros(ciclo)
    # 2.12: os números-dado que ainda estão escritos no texto viram campos “xxxxx” (uma vez por trecho)
    feito["campos"] = camposificar_textos(ciclo)

    # 3. títulos e colunas de tabelas e gráficos acompanham o ano
    for b in Bloco.objects.filter(secao__ciclo=ciclo).exclude(tipo=Bloco.TEXTO):
        mudou = False
        if ano_ant in (b.titulo or ""):
            b.titulo = b.titulo.replace(ano_ant, str(ciclo.ano))
            mudou = True
        cols = (b.config or {}).get("colunas") or []
        anos = [int(m.group(1)) for c in cols for m in [COLUNA_ANO.match(c)] if m]
        if cols and len(anos) == len(cols) and max(anos) == ciclo.ano - 1:
            b.config = dict(b.config, colunas=[f"a{a + 1}" for a in anos])
            mudou = True
        if mudou:
            b.save()
            feito["titulos"] += 1

    # 4. observações de conferência do RG 2025 saem das descrições dos quadros
    #    (só as frases de conferência; o resto da orientação fica, e o que o Master escreveu não é tocado)
    for q in Quadro.objects.filter(ciclo=ciclo):
        if q.descricao and NOTAS_2025.search(q.descricao) and not _mexido_por_alguem(q):
            frases = re.split(r"(?<=[.!?])\s+", q.descricao.strip())
            novo = " ".join(f for f in frases if not NOTAS_2025.search(f)).strip()
            if novo != q.descricao:
                q.descricao = novo
                q.save(update_fields=["descricao"])
                feito["descricoes"] += 1
    Quadro.objects.filter(ciclo=ciclo, chave="frota_km", descricao="").update(descricao=(
        "Quilometragem rodada por tipo de veículo (Gráfico 5). Preencha 2026. A série de anos anteriores não foi "
        "publicada em números no RG: se a DPG tiver os valores, envie ao Master para lançar."))
    # 5. toda seção diz, em uma frase, o que se espera do texto
    com_dados = set(Quadro.objects.filter(ciclo=ciclo).values_list("secao_id", flat=True))
    ciclo.secoes.filter(orientacao=_PDI_ANTES).update(orientacao=_PDI)
    for s in ciclo.secoes.filter(pai__isnull=False, orientacao=""):
        texto = ORIENTACOES.get(s.chave) or (_PDI if s.chave.startswith("pdi_") else _DADOS if s.pk in com_dados else "")
        if texto:
            s.orientacao = texto
            s.save(update_fields=["orientacao"])
            feito["orientacoes"] += 1
    return feito



# --- 2.12 ------------------------------------------------------------------------------------------------
METAS_2026 = "pdi_metas"
UNIDADE_SETOR = {"GDG": "GAB"}     # Gabinete da Direção-Geral


def camposificar_textos(ciclo):
    """Os números-dado do texto (quantidades, R$, %) viram campos “xxxxx”, para preencher com o valor do ano.
    Num trecho que alguém já editou, o número que não está no texto do RG anterior é tratado como já atualizado
    (fica como valor do campo); os que continuam iguais ao RG anterior viram xxxxx. Roda uma vez por trecho."""
    from relatorio import campos as CT
    from relatorio.models import CampoTexto
    textos = _textos_rg2025()
    n = 0
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO).select_related("secao"):
        cfg = b.config or {}
        if cfg.get("campos212"):
            continue
        editado = b.atualizado_por_id is not None or _mexido_por_alguem(b)
        original = R.texto_puro(textos.get(b.secao.chave, {}).get("html", ""))

        def inicial(t, editado=editado, original=original):
            if not editado or t in original:
                return None
            return CT.numero_original(t)
        novo, novos = CT.camposificar(b.conteudo or "", inicial)
        Bloco.objects.filter(pk=b.pk).update(conteudo=novo, config=dict(cfg, campos212=True))
        CampoTexto.objects.bulk_create([CampoTexto(bloco=b, chave=ch, numero=num) for ch, num in novos if num is not None])
        n += len(novos)
    return n


def _metas_2026():
    return json.loads((PASTA / "pdi_metas_2026.json").read_text(encoding="utf-8"))


def apendice_metas_2026(ciclo):
    """O apêndice passa a ser a planilha de acompanhamento das metas do PDI de 2026: uma tabela com as 41 metas,
    cada uma preenchida pela unidade líder (situação, justificativa e evidência). As tabelas por área do RG 2025
    saem, a não ser que alguém já tenha preenchido algo nelas (aí ficam, e o resumo avisa)."""
    from contas.models import Setor

    from relatorio.dados_iniciais.rg2025 import AREAS_PDI
    from relatorio.models import Secao
    cap = ciclo.secoes.filter(chave="apendice", pai__isnull=True).first()
    if cap is None:
        return 0
    dados = _metas_2026()
    # tabelas antigas (por área), se ninguém preencheu
    for chave in AREAS_PDI.values():
        s = ciclo.secoes.filter(chave=chave).first()
        if s is None:
            continue
        usado = Valor.objects.filter(linha__quadro__secao=s, atualizado_por__isnull=False).exists() or \
            Bloco.objects.filter(secao=s, atualizado_por__isnull=False).exists()
        if not usado:
            s.delete()
    if Quadro.objects.filter(ciclo=ciclo, chave=METAS_2026).exists():
        return 0
    if cap.titulo.startswith("Apêndice – Tabelas de acompanhamento"):
        cap.titulo = "Apêndice – Acompanhamento das metas do PDI"
        cap.save(update_fields=["titulo"])
    siglas = []
    for m in dados["metas"]:
        sg = UNIDADE_SETOR.get(m["unidade"], m["unidade"])
        if sg not in siglas:
            siglas.append(sg)
    setores = {x.sigla: x for x in Setor.objects.filter(sigla__in=siglas)}
    s, _ = Secao.objects.get_or_create(ciclo=ciclo, chave=METAS_2026, defaults={
        "pai": cap, "ordem": 5, "titulo": f"Metas do PDI 2023–2027 para {ciclo.ano}",
        "orientacao": "Para cada meta da sua unidade, escolha a situação. Não iniciado ou Interrompido: escreva a "
                      "justificativa. Em andamento ou Concluído: informe a evidência (documento, link, número do processo)."})
    s.setores.set([setores[x] for x in siglas if x in setores])
    q = Quadro.objects.create(
        ciclo=ciclo, secao=s, chave=METAS_2026, ordem=1, titulo=f"Acompanhamento das metas do PDI em {ciclo.ano}",
        descricao=dados.get("instrucao") or "", fonte="Unidades líderes dos objetivos de desenvolvimento",
        setor=None, tipo_valor=Quadro.TEXTO, modo_colunas=Quadro.CATEGORIAS, linha_total=False, coluna_total=False,
        obrigatorio=False)
    colunas = [("oe", "Objetivo estratégico", True), ("od", "Objetivo de desenvolvimento", True),
               ("desc_od", "Descrição do objetivo de desenvolvimento", True), ("unidade", "Unidade líder", True),
               ("situacao", "Situação", False), ("justificativa", "Justificativa", False), ("evidencia", "Evidência", False)]
    cols = {ch: Coluna.objects.create(quadro=q, ordem=k, chave=ch, rotulo=rot, travada=trav)
            for k, (ch, rot, trav) in enumerate(colunas, start=1)}
    for m in dados["metas"]:
        sg = UNIDADE_SETOR.get(m["unidade"], m["unidade"])
        li = Linha.objects.create(quadro=q, ordem=m["n"], chave=f"m{m['n']}", rotulo=m["meta"][:600],
                                  tipo_valor=Quadro.TEXTO, soma_no_total=False, setor=setores.get(sg))
        for ch in ("oe", "od", "desc_od", "unidade"):
            if m.get(ch):
                Valor.objects.create(linha=li, coluna=cols[ch], texto=m[ch])
    Bloco.objects.create(secao=s, tipo=Bloco.TABELA, ordem=10, quadro=q, titulo=q.titulo,
                         config={"colunas": ["od", "unidade", "situacao", "justificativa", "evidencia"]})
    return len(dados["metas"])
