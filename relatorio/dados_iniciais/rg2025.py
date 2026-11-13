"""
Carga do Relatório de Gestão 2025 (publicado em 31/03/2026) como ciclo inicial do SiRG.

Os números são os PUBLICADOS no RG 2025 (painéis das áreas finalísticas, p. 25–61, e
metas do PDI, p. 84–108). Onde o próprio RG trazia números diferentes para a mesma
coisa, os dois foram mantidos em quadros distintos e uma REGRA de consistência aponta
a divergência — exatamente o que a plataforma passa a impedir nos próximos ciclos.

Os quadros que repetiam números de outra área (ex.: matriculados do Técnico, da
Graduação e da Assistência Estudantil) agora são FÓRMULAS que buscam o dado na
Gestão Acadêmica: fonte única.
"""
from django.db import transaction

from relatorio import construtor as K
from relatorio.models import Ciclo, Quadro, Regra

I, D, M, P, T, SN = Quadro.INTEIRO, Quadro.DECIMAL, Quadro.MOEDA, Quadro.PERCENTUAL, Quadro.TEXTO, Quadro.SIM_NAO
NPP = "Conceitos do Glossário da Plataforma Nilo Peçanha (www.gov.br/mec/pt-br/pnp)."
_ = None


def lin(chave, rotulo, formula="", tipo="", total=True, minimo=None, maximo=None):
    return {"chave": chave, "rotulo": rotulo, "formula": formula, "tipo_valor": tipo, "soma_no_total": total,
            "minimo": minimo, "maximo": maximo}


ESTRUTURA = [
    # (chave, título, setores, [(chave, título, setores, orientação[, nível])]) — na ordem do RG 2025 publicado
    ("apresentacao", "Apresentação", ["DGDI"], [
        ("dirigentes", "Dirigentes", ["GAB"], "Nomes e cargos da Direção-Geral, das diretorias, secretarias e campi."),
        ("expediente", "Expediente técnico", ["DGDI"], "Coordenação, comissão de elaboração, diagramação e aprovação."),
        ("mensagem", "Mensagem da dirigente máxima", ["GAB"],
         "Apresentação dos principais resultados do ano, desafios e perspectivas, assinada pela dirigente máxima."),
        ("sobre_rg", "Sobre o Relatório de Gestão", ["DGDI"], "Objetivo, critérios de seleção dos resultados e estrutura do relatório."),
    ]),
    ("visao_geral", "1. Visão geral organizacional e ambiente externo", ["DGDI"], [
        ("base_juridica", "Base jurídica", ["DGDI"], ""),
        ("estrutura_organizacional", "Estrutura organizacional", ["DGDI"], ""),
        ("cadeia_valor", "Cadeia de valor e modelo de negócios do CEFET-MG", ["DGDI"], ""),
        ("valor_publico", "Geração de valor público", ["DGDI"], ""),
        ("ambiente_externo", "Relação com ambiente externo e destinatárias/os de bens e serviços", ["DGDI", "SECOM", "GAB"], ""),
        ("sustentabilidade_social", "Sustentabilidade social", ["DAE"], ""),
        ("sustentabilidade_ambiental", "Sustentabilidade ambiental", ["DPG"], ""),
        ("quem_somos", "Quem somos", ["SEGEP"],
         "Força de trabalho, titulação e capacitação dos servidores em números."),
    ]),
    ("governanca_desempenho", "2. Governança, estratégia e desempenho", ["DGDI"], [
        ("governanca", "Governança", ["DGDI"], ""),
        ("gestao_estrategica", "Gestão estratégica institucional", ["DGDI", "CPA"], ""),
        ("areas_finalisticas", "Desempenho e resultados das áreas finalísticas", ["DGDI"], ""),
        ("ensino_tecnico", "Ensino Técnico de Nível Médio", ["DEPT"], "", 2),
        ("ensino_graduacao", "Ensino de Graduação", ["DIRGRAD"], "", 2),
        ("ensino_pos", "Ensino de Pós-graduação", ["DPPG"], "", 2),
        ("pesquisa_inovacao", "Pesquisa e Inovação Tecnológica", ["DPPG"], "", 2),
        ("extensao", "Extensão", ["DEDC"], "", 2),
        ("desenvolvimento_estudantil", "Desenvolvimento Estudantil", ["DAE"], "", 2),
        ("desenvolvimento_pedagogico", "Desenvolvimento Pedagógico", ["DAE"],
         "Principais resultados dos quatro eixos do Programa de Acompanhamento Pedagógico.", 2),
        ("inclusao", "Inclusão Social e Educacional", ["DAE"], "", 2),
        ("cooperacao_internacional", "Cooperação Internacional", ["SRI"], "", 2),
        ("desenvolvimento_carreiras", "Desenvolvimento de Carreiras", ["DEDC"], "", 2),
        ("gestao_academica", "Gestão Acadêmica", ["SRCA"],
         "Números gerais de cursos, vagas, ingressantes, matriculados e concluintes. São a FONTE ÚNICA "
         "usada pelas demais áreas: os painéis do Técnico, da Graduação e da Assistência Estudantil leem daqui.", 2),
    ]),
    ("riscos_perspectivas", "3. Riscos, oportunidades e perspectivas", ["DGDI"], [
        ("gestao_riscos", "Riscos, oportunidades e perspectivas", ["DGDI"], ""),
        ("conflito_interesses", "Prevenção ao conflito de interesses", ["DGDI"], ""),
        ("assedio", "Assédio, discriminação e violência", ["DGDI"], ""),
        ("swot", "Forças, fraquezas, oportunidades e ameaças", ["DGDI"], ""),
    ]),
    ("orcamento", "4. Informações orçamentárias, financeiras e contábeis", ["DPG"], [
        ("destaques_orcamentarios", "Destaques orçamentários", ["DPG"], ""),
        ("execucao_orcamentaria", "Execução orçamentária", ["DPG"], ""),
        ("restos_a_pagar", "Restos a pagar", ["DPG"], ""),
        ("receitas", "Receitas", ["DPG"], ""),
        ("desafios_perspectivas", "Desafios e perspectivas", ["DPG"], ""),
        ("custos", "Informações de custos", ["DPG"], ""),
        ("contabeis", "Informações contábeis, patrimoniais e de infraestrutura", ["DPG"], ""),
        ("orgaos_controle", "Manifestações dos órgãos de controle externo", ["GAB", "DGDI"], ""),
    ]),
    ("apendice", "Apêndice – Tabelas de acompanhamento do PDI", ["DGDI"], [
        ("pdi_eptnm", "Área: Educação Profissional Tecnológica de Nível Médio", ["DEPT"], ""),
        ("pdi_graduacao", "Área: Ensino de Graduação", ["DIRGRAD"], ""),
        ("pdi_pesquisa_pos", "Área: Pesquisa e Ensino de Pós-graduação", ["DPPG"], ""),
        ("pdi_extensao", "Área: Extensão e Desenvolvimento Comunitário", ["DEDC"], ""),
        ("pdi_estudantil", "Área: Desenvolvimento Estudantil", ["DAE"], ""),
        ("pdi_planejamento", "Área: Planejamento e Gestão", ["DPG"], ""),
        ("pdi_governanca", "Área: Governança e Desenvolvimento Institucional", ["DGDI"], ""),
        ("pdi_ti", "Área: Tecnologia da Informação e Comunicação", ["DTI"], ""),
        ("pdi_ri", "Área: Relações Internacionais", ["SRI"], ""),
        ("pdi_comunicacao", "Área: Comunicação Social", ["SECOM"], ""),
        ("pdi_pessoas", "Área: Gestão de Pessoas", ["SEGEP"], ""),
    ]),
]

# área do apêndice no RG 2025 -> seção do SiRG
AREAS_PDI = {
    "Educação Profissional Tecnológica de Nível Médio": "pdi_eptnm", "Ensino de Graduação": "pdi_graduacao",
    "Pesquisa e Ensino de Pós-graduação": "pdi_pesquisa_pos", "Extensão e Desenvolvimento Comunitário": "pdi_extensao",
    "Desenvolvimento Estudantil": "pdi_estudantil", "Planejamento e Gestão": "pdi_planejamento",
    "Governança e Desenvolvimento Institucional": "pdi_governanca", "Tecnologia da Informação e Comunicação": "pdi_ti",
    "Relações Internacionais": "pdi_ri", "Comunicação Social": "pdi_comunicacao", "Gestão de Pessoas": "pdi_pessoas",
}


@transaction.atomic
def carregar(ano=2025, situacao=Ciclo.ENCERRADO):
    ciclo = Ciclo.objects.create(ano=ano, titulo=f"Relatório de Gestão {ano}", situacao=situacao, anos_serie=5,
                                 observacao="Carga inicial com os números publicados no RG 2025 (31/03/2026). "
                                            "As regras de consistência mostram onde o relatório publicado "
                                            "trazia números divergentes.")
    S = {}
    for i, (ch, titulo, setores, secoes) in enumerate(ESTRUTURA, start=1):
        cap = K.secao(ciclo, ch, titulo, ordem=i * 10, setores=setores)
        for j, (sch, stit, sset, orient, *nivel) in enumerate(secoes, start=1):
            S[sch] = K.secao(ciclo, sch, stit, pai=cap, ordem=j * 10, setores=sset, orientacao=orient)
            if nivel:
                S[sch].nivel = nivel[0]
                S[sch].save(update_fields=["nivel"])
        S[ch] = cap

    # --- Gestão Acadêmica (fonte única) -------------------------------------------
    ga = S["gestao_academica"]
    niveis = [("tecnico", "Técnico"), ("graduacao", "Graduação"), ("pos", "Pós-graduação")]
    ing = K.quadro(ga, "ga_ingressantes", "Alunos ingressantes", niveis, total=True, descricao=NPP, fonte="SRCA",
                   valores={"tecnico": [2017, 1875, 2128, 2097, 2227], "graduacao": [1308, 1203, 1515, 1552, 1620],
                            "pos": [347, 262, 261, 336, 376]})
    mat = K.quadro(ga, "ga_matriculados", "Alunos matriculados", niveis, total=True, descricao=NPP, fonte="SRCA",
                   valores={"tecnico": [5938, 6010, 6275, 6809, 6895], "graduacao": [4716, 5050, 5685, 6279, 6770],
                            "pos": [879, 846, 917, 1023, 1090]})
    con = K.quadro(ga, "ga_concluintes", "Alunos concluintes", niveis, total=True, descricao=NPP, fonte="SRCA",
                   valores={"tecnico": [1765, 1986, 1642, 1904, 2127], "graduacao": [514, 514, 550, 586, 589],
                            "pos": [224, 249, 306, 306, 347]})
    vag = K.quadro(ga, "ga_vagas", "Vagas ofertadas", niveis, total=True, fonte="SRCA",
                   valores={"tecnico": [_, _, _, _, 2232], "graduacao": [_, _, _, _, 1844], "pos": [_, _, _, _, 512]},
                   descricao="O RG 2025 publicou só o ano de 2025.")
    gcur = K.quadro(ga, "ga_cursos", "Cursos ofertados", niveis + [("outros", "Outros")], anos=1, total=True, fonte="SRCA",
             valores={"tecnico": [43], "graduacao": [29], "pos": [21], "outros": [1]},
             descricao="O RG 2025 informa 94 cursos ofertados; a diferença para técnico + graduação + pós aparece "
                       "em “Outros” — confirmar a natureza.")

    # --- Pós-graduação ---------------------------------------------------------------
    pos = S["ensino_pos"]
    pn = K.quadro(pos, "pos_numeros", "Pós-graduação stricto sensu em números", [
        ("cursos", "Cursos"), ("vagas", "Vagas ofertadas"), ("ingressantes", "Ingressantes"),
        ("matriculados", "Matriculados"), ("concluintes", "Concluintes"),
        ("disciplinas_isoladas", "Matrículas em disciplinas isoladas")],
        modo=Quadro.CATEGORIAS, colunas=[("mestrado", "Mestrado"), ("doutorado", "Doutorado")], coluna_total=True,
        fonte="DPPG", valores={"cursos": [14, 7], "vagas": [403, 109], "ingressantes": [210, 106],
                               "matriculados": [777, 313], "concluintes": [166, 36], "disciplinas_isoladas": [876, 146]})
    K.quadro(pos, "pos_bolsas", "Bolsas stricto sensu com recursos do CEFET-MG", [
        lin("bolsas", "Bolsas pagas"), lin("recursos", "Recursos utilizados", tipo=M, total=False)], fonte="DPPG",
        valores={"bolsas": [85, 65, 66, 23, 35], "recursos": [2080516.67, 2007625, 1248200, 722000, 1042400]})
    K.quadro(pos, "pos_auxilio", "Auxílio discente na pós-graduação", [
        lin("alunos", "Alunos atendidos"), lin("recursos", "Recursos utilizados", tipo=M, total=False)], fonte="DPPG",
        descricao="Não inclui recursos da assistência estudantil.",
        valores={"alunos": [34, 45, 80, 85, 105], "recursos": [7165.5, 10412.66, 219351.25, 161014.73, 187234.95]})
    K.quadro(pos, "pos_capacitacao", "Capacitação de docentes para o ensino (pós)", [("investimento", "Investimento")],
             anos=1, tipo=M, valores={"investimento": [3924.30]}, fonte="DPPG")
    pdef = K.quadro(pos, "pos_defesas", "Defesas registradas no ano", [
        ("dissertacoes", "Dissertações de mestrado"), ("teses", "Teses de doutorado")], anos=1, fonte="DPPG",
        valores={"dissertacoes": [131], "teses": [38]}, descricao="Valores citados no acompanhamento das metas do PDI.")
    # o mesmo número aparece nos dois quadros (21 = 14 mestrados + 7 doutorados)
    K.regra(gcur, "Cursos de pós = cursos de mestrado + doutorado da Pós-graduação em números", "pos",
            "pos_numeros.cursos.mestrado + pos_numeros.cursos.doutorado", severidade=Regra.AVISO)

    K.regra(ing, "Ingressantes da pós iguais aos do painel da Pós-graduação", "pos", "pos_numeros.ingressantes.total")
    K.regra(con, "Concluintes da pós iguais aos do painel da Pós-graduação", "pos", "pos_numeros.concluintes.total")
    K.regra(mat, "Matriculados da pós iguais aos do painel da Pós-graduação", "pos", "pos_numeros.matriculados.total")
    K.regra(vag, "Vagas da pós iguais às do painel da Pós-graduação", "pos", "pos_numeros.vagas.total")
    K.regra(pdef, "Dissertações defendidas = concluintes de mestrado do painel", "dissertacoes",
            "pos_numeros.concluintes.mestrado", severidade=Regra.AVISO)
    K.regra(pdef, "Teses defendidas = concluintes de doutorado do painel", "teses",
            "pos_numeros.concluintes.doutorado", severidade=Regra.AVISO)

    # --- Ensino Técnico ----------------------------------------------------------------
    tec = S["ensino_tecnico"]
    K.quadro(tec, "tec_numeros", "Ensino técnico em números (da Gestão Acadêmica)", [
        ("cursos", "Cursos ofertados", "ga_cursos.tecnico"), ("vagas", "Vagas ofertadas", "ga_vagas.tecnico"),
        ("ingressantes", "Ingressantes", "ga_ingressantes.tecnico"),
        ("matriculados", "Matriculados", "ga_matriculados.tecnico"),
        ("concluintes", "Concluintes", "ga_concluintes.tecnico")], anos=1,
        descricao="Calculado: lê os números da Gestão Acadêmica (fonte única). Não é preciso digitar de novo.")
    K.quadro(tec, "tec_modalidade", "Cursos técnicos por forma de oferta", [
        ("integrados", "Integrados"), ("concomitante", "Concomitante"), ("subsequente", "Subsequente")], anos=1,
        fonte="DEPT", valores={"integrados": [38], "concomitante": [18], "subsequente": [19]})
    K.quadro(tec, "tec_meta", "Mostra Específica de Trabalhos e Aplicações (META)", [
        ("trabalhos", "Trabalhos apresentados"), ("alunos", "Alunos participantes")], fonte="DEPT",
        valores={"trabalhos": [34, 11, 127, 238, 248], "alunos": [73, 25, 319, 768, 772]})
    ta = K.quadro(tec, "tec_auxilio", "Auxílio discente no ensino técnico", [
        lin("alunos", "Alunos atendidos"), lin("recursos", "Recursos utilizados", tipo=M, total=False)], fonte="DEPT",
        valores={"alunos": [6, 67, 314, 183, 134], "recursos": [770, 24933.5, 92440, 62549.4, 87062.2]})
    tac = K.quadro(tec, "tec_auxilio_campus", "Alunos atendidos com auxílio discente por campus", [
        ("belo_horizonte", "Belo Horizonte"), ("divinopolis", "Divinópolis"), ("varginha", "Varginha"),
        ("leopoldina", "Leopoldina")], anos=1, total=True, fonte="DEPT",
        valores={"belo_horizonte": [64], "divinopolis": [44], "varginha": [22], "leopoldina": [4]})
    K.regra(tac, "Soma por campus = alunos atendidos", "total", "tec_auxilio.alunos")
    K.quadro(tec, "tec_olimpiadas", "Olimpíadas do conhecimento", [
        ("premiacoes", "Premiações"), ("olimpiadas", "Olimpíadas com participação"), ("ouro", "Medalhas de ouro (OBM)"),
        ("prata", "Medalhas de prata (OBM)"), ("bronze", "Medalhas de bronze (OBM)"),
        ("mencao", "Menções honrosas (OBM)")], anos=1, fonte="DEPT",
        valores={"premiacoes": [931], "olimpiadas": [15], "ouro": [8], "prata": [38], "bronze": [90], "mencao": [140]})
    K.quadro(tec, "tec_capacitacao", "Capacitação de docentes para o ensino (técnico)", [("investimento", "Investimento")],
             anos=1, tipo=M, valores={"investimento": [38464.77]}, fonte="DEPT")

    # --- Graduação ------------------------------------------------------------------------
    gr = S["ensino_graduacao"]
    K.quadro(gr, "grad_numeros", "Graduação em números (da Gestão Acadêmica)", [
        ("cursos", "Cursos ofertados", "ga_cursos.graduacao"), ("vagas", "Vagas ofertadas", "ga_vagas.graduacao"),
        ("ingressantes", "Ingressantes", "ga_ingressantes.graduacao"),
        ("matriculados", "Matriculados", "ga_matriculados.graduacao"),
        ("concluintes", "Concluintes", "ga_concluintes.graduacao"),
        lin("ocupacao", "Ocupação das vagas", "ingressantes / vagas * 100", tipo=P)], anos=1, casas=1,
        descricao="Calculado a partir da Gestão Acadêmica (fonte única).")
    gpet = K.quadro(gr, "grad_pet", "Programa de Educação Tutorial (PET)", [
        lin("alunos", "Alunos participantes"), lin("recursos", "Recursos utilizados", tipo=M, total=False)],
        fonte="DIRGRAD", valores={"alunos": [151, 168, 145, 148, 145],
                                  "recursos": [367054.83, 472003.38, 620341.2, 666890, 671406.99]})
    K.quadro(gr, "grad_auxilio", "Auxílio discente na graduação", [
        lin("alunos", "Alunos atendidos"), lin("recursos", "Recursos utilizados", tipo=M, total=False)],
        fonte="DIRGRAD", descricao="Não inclui recursos da assistência estudantil.",
        valores={"alunos": [28, 20, 110, 104, 81], "recursos": [9119, 34909.62, 52860, 60000, 73249.8]})
    K.quadro(gr, "grad_monitoria", "Monitoria", [
        lin("alunos", "Alunos participantes"), lin("recursos", "Recursos utilizados", tipo=M, total=False)],
        fonte="DIRGRAD", valores={"alunos": [369, 247, 176, 129, 199],
                                  "recursos": [405761.42, 443322.39, 309228.87, 212993.16, 290473.54]})
    K.quadro(gr, "grad_fomento", "Fomento a discentes de graduação (PET + auxílio + monitoria)", [
        ("pet", "PET", "grad_pet.recursos"), ("auxilio", "Auxílio discente", "grad_auxilio.recursos"),
        ("monitoria", "Monitoria", "grad_monitoria.recursos")], tipo=M, total=True,
        descricao="Calculado a partir dos quadros de PET, auxílio discente e monitoria.")
    gav = K.quadro(gr, "grad_avaliacao", "Avaliação dos cursos de graduação (MEC: in loco ou ENADE)", [
        lin("nota5", "Nota 5"), lin("nota4", "Nota 4"), lin("nota3", "Nota 3"),
        lin("avaliados", "Cursos avaliados", "nota5 + nota4 + nota3", total=False),
        lin("sem_avaliacao", "Cursos ainda sem avaliação", total=False)], anos=1, fonte="DIRGRAD / CPA",
        valores={"nota5": [12], "nota4": [8], "nota3": [3], "sem_avaliacao": [6]})
    K.regra(gav, "Avaliados + sem avaliação = cursos de graduação ofertados", "avaliados + sem_avaliacao",
            "ga_cursos.graduacao")
    K.quadro(gr, "grad_outros", "Outros números da graduação", [
        ("grupos_pet", "Grupos PET em atividade"), ("novos_cursos", "Novos cursos aprovados"),
        ("novas_vagas", "Novas vagas anuais previstas")], anos=1, fonte="DIRGRAD",
        valores={"grupos_pet": [12], "novos_cursos": [1], "novas_vagas": [80]})
    del gpet

    # --- Extensão ----------------------------------------------------------------------------
    ex = S["extensao"]
    en = K.quadro(ex, "ext_numeros", "Extensão em números", [
        ("acoes", "Ações de extensão executadas"), ("fomento_interno", "Ações com fomento interno"),
        ("integradas_ppc", "Ações integradas com PPC da graduação"), ("cursos", "Cursos de extensão"),
        ("vulneraveis", "Ações destinadas à população vulnerável"),
        ("acoes_pdi", "Ações com viés de pesquisa, desenvolvimento e inovação")], anos=1, fonte="DEDC",
        valores={"acoes": [377], "fomento_interno": [127], "integradas_ppc": [57], "cursos": [71], "vulneraveis": [23],
                 "acoes_pdi": [15]})
    del en
    ec = K.quadro(ex, "ext_campus", "Ações de extensão por campus", [
        ("nova_gameleira", "BH — Nova Gameleira"), ("nova_suica", "BH — Nova Suíça"), ("varginha", "Varginha"),
        ("leopoldina", "Leopoldina"), ("divinopolis", "Divinópolis"), ("timoteo", "Timóteo"), ("araxa", "Araxá"),
        ("nepomuceno", "Nepomuceno"), ("curvelo", "Curvelo"), ("contagem", "Contagem")], anos=1, total=True,
        fonte="DEDC", valores={"nova_gameleira": [129], "nova_suica": [72], "varginha": [46], "leopoldina": [39],
                               "divinopolis": [34], "timoteo": [17], "araxa": [15], "nepomuceno": [13],
                               "curvelo": [7], "contagem": [5]})
    K.regra(ec, "Soma por campus = ações executadas", "total", "ext_numeros.acoes")
    ea = K.quadro(ex, "ext_area", "Ações de extensão por área temática", [
        ("educacao", "Educação"), ("tecnologia", "Tecnologia e Produção"), ("cultura", "Cultura"), ("saude", "Saúde"),
        ("meio_ambiente", "Meio Ambiente"), ("trabalho", "Trabalho"), ("comunicacao", "Comunicação"),
        ("direitos_humanos", "Direitos Humanos")], anos=1, total=True, fonte="DEDC",
        valores={"educacao": [141], "tecnologia": [130], "cultura": [30], "saude": [29], "meio_ambiente": [20],
                 "trabalho": [13], "comunicacao": [11], "direitos_humanos": [3]})
    K.regra(ea, "Soma por área temática = ações executadas", "total", "ext_numeros.acoes")
    enat = K.quadro(ex, "ext_natureza", "Ações de extensão por natureza", [
        ("projeto", "Projeto"), ("curso", "Curso"), ("evento", "Evento"), ("programa", "Programa"),
        ("prestacao", "Prestação de Serviços")], anos=1, total=True, fonte="DEDC",
        valores={"projeto": [214], "curso": [71], "evento": [43], "programa": [25], "prestacao": [24]})
    K.regra(enat, "Soma por natureza = ações executadas", "total", "ext_numeros.acoes")
    K.regra(enat, "Cursos (natureza) = cursos de extensão de Extensão em números", "curso", "ext_numeros.cursos",
            severidade=Regra.AVISO)
    ecat = K.quadro(ex, "ext_categoria", "Ações de extensão por categoria", [
        ("sem_recursos", "Sem recursos financeiros"), ("fomento_interno", "Fomento interno"),
        ("financiamento_externo", "Financiamento externo"), ("natureza_especial", "Natureza especial"),
        ("lato_sensu", "Curso lato sensu")], anos=1, total=True, fonte="DEDC",
        valores={"sem_recursos": [192], "fomento_interno": [127], "financiamento_externo": [32],
                 "natureza_especial": [25], "lato_sensu": [1]})
    K.regra(ecat, "Soma por categoria = ações executadas", "total", "ext_numeros.acoes")
    K.regra(ecat, "Fomento interno = ações com fomento interno (Extensão em números)", "fomento_interno",
            "ext_numeros.fomento_interno", severidade=Regra.AVISO)

    # --- Pesquisa e Inovação --------------------------------------------------------------------
    pq = S["pesquisa_inovacao"]
    ic = K.quadro(pq, "pq_ic", "Iniciação científica", [
        lin("alunos", "Alunos participantes"), lin("recursos", "Recursos próprios utilizados", tipo=M, total=False)],
        fonte="DPPG", valores={"alunos": [323, 373, 432, 566, 551],
                               "recursos": [267600, 388700, 200250, 202080, 204300]})
    del ic
    icn = K.quadro(pq, "pq_ic_nivel", "Participantes da iniciação científica por nível", [
        ("tecnico", "Técnico"), ("graduacao", "Graduação")], anos=1, total=True, fonte="DPPG",
        valores={"tecnico": [233], "graduacao": [318]})
    K.regra(icn, "Soma por nível = participantes da iniciação científica", "total", "pq_ic.alunos")
    K.quadro(pq, "pq_captacao", "Recursos captados junto às agências de fomento", [
        ("cnpq", "CNPq"), ("fapemig", "FAPEMIG"), ("finep", "FINEP"), ("serrapilheira", "Serrapilheira/FAPEMIG")],
        tipo=M, total=True, fonte="DPPG",
        descricao="Não inclui recursos obtidos por empresas parceiras em projetos conjuntos (ex.: Compete Minas).",
        valores={"cnpq": [0, 316988.65, 119200, 300477.13, 1208960.94],
                 "fapemig": [426699, 1667935.73, 6251812.23, 5104458.49, 2006277.38],
                 "finep": [0, 3719271.19, 0, 3551032.13, 1242424.88], "serrapilheira": [0, 0, 0, 700000, 0]})
    K.quadro(pq, "pq_bolsistas", "Bolsistas de produtividade em pesquisa (CNPq)", [("bolsistas", "Bolsistas")],
             fonte="DPPG", valores={"bolsistas": [13, 17, 17, 16, 18]})
    K.quadro(pq, "pq_artigos", "Artigos publicados", [
        ("eventos", "Em eventos técnico-científicos"), ("periodicos", "Em periódicos"),
        lin("scival", "Indexados no SciVal", total=False)], total=True, rotulo_total="Total (eventos + periódicos)",
        fonte="DPPG", valores={"eventos": [362, 285, 329, 532, 544], "periodicos": [852, 700, 654, 828, 854],
                               "scival": [275, 233, 244, 253, 213]})
    K.quadro(pq, "pq_pi", "Pedidos de propriedade intelectual", [
        ("patentes", "Patentes"), ("programas", "Programas de computador"), ("marcas", "Marcas")], total=True,
        fonte="DPPG", valores={"patentes": [10, 9, 1, 8, 11], "programas": [2, 15, 6, 29, 28], "marcas": [0, 3, 0, 1, 0]})
    K.quadro(pq, "pq_inovacao", "Inovação e empreendedorismo", [
        ("acoes_pdi", "Ações de extensão em pesquisa, desenvolvimento e inovação", "ext_numeros.acoes_pdi"),
        ("empresas_juniores", "Empresas juniores credenciadas"), ("alunos_ej", "Alunos envolvidos em empresas juniores"),
        lin("faturamento_ej", "Faturamento das empresas juniores", tipo=M), ("incubados", "Empreendimentos incubados (Nascente)")],
        anos=1, fonte="DPPG", valores={"empresas_juniores": [9], "alunos_ej": [89], "faturamento_ej": [84625.50],
                                       "incubados": [3]})
    K.quadro(pq, "pq_semana_ct", "Participantes da Semana de Ciência e Tecnologia", [
        ("tecnico", "Técnico"), ("graduacao", "Graduação"), ("pos", "Pós-graduação")], anos=1, total=True,
        fonte="DPPG", valores={"tecnico": [652], "graduacao": [190], "pos": [15]})

    # --- Desenvolvimento Estudantil --------------------------------------------------------------
    de = S["desenvolvimento_estudantil"]
    K.quadro(de, "de_bolsas", "Bolsas e isenções da assistência estudantil", [
        ("permanencia", "Bolsa permanência"), ("complementacao", "Bolsa complementação educacional"),
        ("alimentacao", "Bolsa alimentação"), ("emergencial", "Bolsa emergencial"),
        ("isentos_re", "Alunos isentos no restaurante estudantil")], anos=1, fonte="DAE",
        valores={"permanencia": [1268], "complementacao": [105], "alimentacao": [513], "emergencial": [78],
                 "isentos_re": [807]})
    K.quadro(de, "de_restaurantes", "Restaurantes estudantis", [
        lin("refeicoes", "Refeições servidas"), lin("atendidos", "Alunos atendidos nos restaurantes"),
        lin("matriculados", "Alunos matriculados (Gestão Acadêmica)", "ga_matriculados.total", total=False),
        lin("percentual", "Alunos atendidos (% dos matriculados)", "atendidos / matriculados * 100", tipo=P,
            total=False, maximo=100)], casas=1, fonte="DAE",
        descricao="Os matriculados vêm da Gestão Acadêmica (fonte única); o percentual é calculado.",
        valores={"refeicoes": [0, 549127, 766797, 574290, 696059], "atendidos": [0, 10281, 11402, 10779, 12864]})
    K.quadro(de, "de_custeio", "Custeio e orçamento da assistência estudantil", [
        lin("custos", "Custos da assistência estudantil"), lin("pnaes", "Orçamento PNAES"),
        lin("proprios", "Recursos próprios do CEFET-MG investidos", "custos - pnaes")], tipo=M, fonte="DAE / DPG",
        valores={"custos": [9977736, 12676250, 16046959.46, 14292996.29, 15883738.02],
                 "pnaes": [8407046, 8317099, 9408000, 9408000, 9304801.99]})
    K.quadro(de, "de_re_servico", "Serviço dos restaurantes estudantis", [("valor", "Valor total do serviço no ano")],
             anos=1, tipo=M, fonte="DAE", valores={"valor": [9555541.53]})

    # --- Inclusão ----------------------------------------------------------------------------------
    inc = S["inclusao"]
    K.quadro(inc, "inc_nee", "Alunos com necessidades educacionais específicas atendidos pelos NAAPIs",
             [("atendidos", "Alunos atendidos")], fonte="DAE / NAAPIs",
             valores={"atendidos": [_, _, 239, 366, 561]}, descricao="O RG 2025 publicou a série a partir de 2023.")
    ic2 = K.quadro(inc, "inc_nee_campus", "Alunos com NEE atendidos por campus", [
        ("ns", "BH — Nova Suíça"), ("ng", "BH — Nova Gameleira"), ("lp", "Leopoldina"), ("ax", "Araxá"),
        ("dv", "Divinópolis"), ("tm", "Timóteo"), ("vg", "Varginha"), ("np", "Nepomuceno"), ("cv", "Curvelo"),
        ("ct", "Contagem")], anos=1, total=True, fonte="DAE / NAAPIs",
        valores={"ns": [178], "ng": [91], "lp": [16], "ax": [20], "dv": [44], "tm": [119], "vg": [23], "np": [14],
                 "cv": [26], "ct": [30]})
    K.regra(ic2, "Soma por campus = alunos com NEE atendidos", "total", "inc_nee.atendidos")
    K.quadro(inc, "inc_cotistas", "Ingressantes cotistas (% dos ingressantes)", [
        lin("tecnico", "Técnico", maximo=100), lin("graduacao", "Graduação", maximo=100),
        lin("pos", "Pós-graduação", maximo=100)], tipo=P, casas=2, fonte="SRCA / DAE",
        valores={"tecnico": [42.34, 43.31, 43.94, 43.49, 39.65], "graduacao": [36.70, 36.24, 40.53, 32.80, 36.79],
                 "pos": [0, 0.38, 6.13, 8.63, 10.37]})
    campi = [("ns", "BH — Nova Suíça"), ("ng", "BH — Nova Gameleira"), ("lp", "Leopoldina"), ("ax", "Araxá"),
             ("dv", "Divinópolis"), ("tm", "Timóteo"), ("vg", "Varginha"), ("np", "Nepomuceno"), ("cv", "Curvelo"),
             ("ct", "Contagem")]
    espaco = {"ns", "ng", "dv", "tm", "np", "ct"}
    K.quadro(inc, "inc_acessibilidade", "Acessibilidade por campus", campi, modo=Quadro.CATEGORIAS, tipo=SN,
             colunas=[("mapeado", "Campus mapeado quanto à inclusão"), ("biblioteca", "Biblioteca com acessibilidade"),
                      ("espaco_naapi", "Espaço para o NAAPI")], fonte="DAE / NAAPIs",
             descricao="Atenção: no RG 2025 o painel mostrava todos os campi mapeados e com biblioteca acessível, "
                       "mas a tabela de metas do PDI registrava essas metas como “não cumpridas”. Confirmar.",
             valores={ch: ["sim", "sim", "sim" if ch in espaco else "nao"] for ch, _r in campi})

    # --- Cooperação Internacional --------------------------------------------------------------------
    ri = S["cooperacao_internacional"]
    rm = K.quadro(ri, "ri_mobilidade", "Alunos em mobilidade acadêmica internacional", [
        ("entrada", "Recebidos (IN)"), ("saida", "Enviados (OUT)")], fonte="SRI",
        valores={"entrada": [0, 35, 16, 60, 68], "saida": [1, 95, 91, 87, 97]})
    del rm
    rn = K.quadro(ri, "ri_mobilidade_nivel", "Alunos em mobilidade no ano, por nível", [
        ("tecnico", "Técnico"), ("graduacao", "Graduação"), ("pos", "Pós-graduação"), ("outros", "Outros")],
        modo=Quadro.CATEGORIAS, colunas=[("entrada", "IN"), ("saida", "OUT")], total=True, fonte="SRI",
        valores={"tecnico": [15, 5], "graduacao": [25, 92], "pos": [14, 0], "outros": [14, 0]})
    K.regra(rn, "Mobilidade IN por nível = total IN do ano", "ri_mobilidade_nivel.total.entrada",
            "ri_mobilidade.entrada.atual")
    K.regra(rn, "Mobilidade OUT por nível = total OUT do ano", "ri_mobilidade_nivel.total.saida",
            "ri_mobilidade.saida.atual")
    K.quadro(ri, "ri_series", "Cooperação internacional — séries", [
        ("dupla_diplomacao", "Alunos em dupla diplomação"), ("docentes", "Docentes em mobilidade internacional"),
        ("ple", "Participantes do Programa de Português como Língua Estrangeira")], fonte="SRI",
        valores={"dupla_diplomacao": [3, 16, 16, 32, 22], "docentes": [1, 1, 10, 11, 18], "ple": [163, 191, 209, 151, 178]})
    K.quadro(ri, "ri_numeros", "Cooperação internacional em números", [
        ("acordos_novos", "Acordos de mobilidade novos"), ("acordos_renovados", "Acordos de mobilidade renovados"),
        lin("acordos", "Acordos de mobilidade internacional", "acordos_novos + acordos_renovados"),
        ("leitorado", "Participantes do Programa de Leitorado Francês"),
        ("paises", "Países com mobilidade")], anos=1, fonte="SRI",
        valores={"acordos_novos": [13], "acordos_renovados": [7], "leitorado": [329], "paises": [30]})

    # --- Desenvolvimento de Carreiras --------------------------------------------------------------------
    K.quadro(S["desenvolvimento_carreiras"], "car_numeros", "Desenvolvimento de carreiras em números", [
        ("concluintes_estagio", "Alunos concluintes do estágio supervisionado obrigatório (EPTNM)"),
        ("vagas_divulgadas", "Vagas de estágio e emprego divulgadas aos estudantes"),
        ("acordos_ativos", "Acordos de cooperação ativos com empresas (desde 2021)")], anos=1, fonte="DEDC",
        valores={"concluintes_estagio": [946], "vagas_divulgadas": [1795], "acordos_ativos": [2700]},
        descricao="Conferir: 946 é também o número de docentes da instituição.")

    # --- Quem somos: pessoas, capacitação e orçamento ----------------------------------------------------------
    qs = S["quem_somos"]
    K.quadro(qs, "gp_tae", "Técnico-administrativos em educação por titulação", [
        ("sem_graduacao", "Sem graduação completa"), ("graduacao", "Graduação"), ("lato", "Pós-graduação lato sensu"),
        ("mestrado", "Mestrado"), ("doutorado", "Doutorado")], total=True, setor_sigla="SEGEP",
        fonte="Data Warehouse do SIAPENet (dezembro de cada ano)",
        valores={"sem_graduacao": [43, 38, 36, 35, 39], "graduacao": [94, 89, 87, 73, 62],
                 "lato": [275, 269, 257, 251, 247], "mestrado": [211, 228, 228, 235, 253],
                 "doutorado": [27, 30, 35, 44, 47]})
    K.quadro(qs, "gp_docentes", "Professores por titulação", [
        ("graduacao", "Graduação"), ("lato", "Pós-graduação lato sensu"), ("mestrado", "Mestrado"),
        ("doutorado", "Doutorado")], total=True, setor_sigla="SEGEP",
        fonte="Data Warehouse do SIAPENet (dezembro de cada ano)",
        valores={"graduacao": [4, 2, 3, 2, 2], "lato": [16, 9, 7, 5, 4], "mestrado": [345, 328, 307, 290, 272],
                 "doutorado": [583, 607, 627, 643, 668]})
    K.quadro(qs, "gp_capacitacao_valor", "Valor investido em capacitação de servidores", [
        ("prosup", "Programa de Formação em Ensino Superior (PROSUP)"),
        ("proling", "Programa de Desenvolvimento em Língua Estrangeira (PROLING)"),
        ("prodes", "Programa de Desenvolvimento Proativo (PRODES)"),
        ("eds", "Escola de Desenvolvimento dos Servidores (EDS)"),
        ("docente_ensino", "Capacitação docente para o ensino (técnico + pós)",
         "tec_capacitacao.investimento + pos_capacitacao.investimento")], anos=1, tipo=M, total=True,
        setor_sigla="SEGEP", valores={"prosup": [151861.71], "proling": [23750], "prodes": [103756.93],
                                      "eds": [137672.52]},
        descricao="A capacitação docente para o ensino é calculada a partir dos quadros do Técnico e da Pós.")
    K.quadro(qs, "gp_capacitacao_servidores", "Servidores atendidos em capacitação", [
        ("prosup", "PROSUP"), ("proling", "PROLING"), ("prodes", "PRODES"), ("eds", "EDS"),
        ("docente_ensino", "Capacitação docente para o ensino")], anos=1, total=True,
        setor_sigla="SEGEP", valores={"prosup": [123], "proling": [30], "prodes": [157], "eds": [603],
                                      "docente_ensino": [157]},
        descricao="Conferir PRODES: as tabelas de detalhamento da SEGEP somavam 95 servidores.")
    K.quadro(qs, "gp_eds_cursos", "Servidores atendidos por curso da Escola de Desenvolvimento dos Servidores (EDS)", [
        ("mediacao", "Mediação de Conflitos"), ("habilidades", "Habilidades emocionais (turma 1 e 2)"),
        ("fiscalizacao", "Fiscalização de Contratos"),
        ("cif", "Classificação Internacional de Funcionalidade, Incapacidade e Saúde (CIF)")], anos=1, total=True,
        setor_sigla="SEGEP", fonte="SEGEP",
        descricao="Um curso por linha. Se os cursos de 2026 forem outros, peça ao administrador para trocar os nomes.",
        valores={"mediacao": [15], "habilidades": [18], "fiscalizacao": [29], "cif": [41]})
    # capítulos 1, 2 e 4 (fora das áreas finalísticas): orçamento, custos, patrimônio, ouvidoria, CPA, TCU...
    from relatorio.dados_iniciais import rg2025_gestao
    rg2025_gestao.carregar(S)
    # no ciclo 2025 todos os anos já foram publicados: nada fica "a preencher" nos anos anteriores
    from relatorio.models import Coluna
    Coluna.objects.filter(quadro__ciclo=ciclo, ano__lt=ano).update(travada=True)
    carregar_blocos(ciclo)
    if situacao == Ciclo.ENCERRADO:
        ciclo.secoes.update(situacao="aprovada")
    return ciclo


# ---------------------------------------------------------------------------------------------
# Texto, tabelas, gráficos e destaques do RG 2025 (exemplos de montagem do documento)
# ---------------------------------------------------------------------------------------------
def _n(ref, col=None):
    c = f' data-col="{col}"' if col else ""
    return f'<span class="sirg-num" data-ref="{ref}"{c}>0</span>'


TEXTOS = {
    "mensagem": (
        "<p>Com grande alegria entregamos mais um Relatório de Gestão do Centro Federal de Educação Tecnológica de "
        "Minas Gerais, agora com os resultados alcançados no ano de 2025.</p>"
        f"<p>Contabilizamos {_n('ga_matriculados.total')} alunos matriculados em cursos regulares, sendo "
        f"{_n('ga_ingressantes.total')} ingressantes e {_n('ga_concluintes.total')} concluintes nos diferentes "
        f"cursos da instituição, e ofertamos {_n('ga_vagas.total')} novas vagas.</p>"
        f"<p>No campo da pesquisa e da inovação tecnológica, captamos {_n('pq_captacao.total')} junto às agências "
        f"de fomento. Ao longo de 2025, foram servidas {_n('de_restaurantes.refeicoes')} refeições subsidiadas nos "
        f"restaurantes estudantis, e {_n('de_custeio.proprios')} do orçamento próprio foram investidos na "
        f"assistência estudantil.</p>"
        "<blockquote>No RG 2025 publicado, este parágrafo informava 4.516 novas vagas, enquanto o painel da Gestão "
        "Acadêmica mostrava 4.588. Com o número vivo, o texto passa a ler sempre o mesmo dado do quadro.</blockquote>"),
    "pesquisa_inovacao": (
        f"<p>Em 2025, o CEFET-MG captou {_n('pq_captacao.total')} em recursos externos para fomento à pesquisa e à "
        f"inovação. Esse valor não inclui os R$ 2,72 milhões obtidos por empresas parceiras em projetos conjuntos com "
        f"docentes da Instituição (Chamada FAPEMIG nº 08/2025 – Compete Minas).</p>"
        f"<p>Os principais financiadores foram a FAPEMIG ({_n('pq_captacao.fapemig')}), o CNPq "
        f"({_n('pq_captacao.cnpq')}) e a FINEP/MCTI ({_n('pq_captacao.finep')} – manutenção de infraestrutura de "
        f"pesquisa). O corpo docente manteve {_n('pq_bolsistas.bolsistas')} bolsistas de produtividade em pesquisa "
        f"do CNPq.</p>"
        f"<p>A produção intelectual somou {_n('pq_artigos.total')} artigos publicados em periódicos ou eventos "
        f"técnico-científicos, e foram feitos {_n('pq_pi.total')} pedidos de propriedade intelectual.</p>"),
    "ensino_graduacao": (
        "<p>Em 2025 foi aprovado o curso de Biotecnologia no Campus Nova Suíça, em Belo Horizonte, com início no "
        "primeiro semestre de 2026.</p>"
        f"<p>O número de alunos matriculados na graduação chegou a {_n('ga_matriculados.graduacao')} em 2025, e a "
        f"ocupação das vagas ofertadas foi de {_n('grad_numeros.ocupacao')}.</p>"
        f"<p>O fomento para discentes de graduação (PET, auxílio discente e monitoria) passou de "
        f"{_n('grad_fomento.total', 'a2022')} em 2022 para {_n('grad_fomento.total')} em 2025, mesmo diante de um "
        f"cenário de restrição orçamentária.</p>"
        "<blockquote>Na planilha usada para o RG 2025, este texto citava 6.197 matriculados em 2023 e 6.832 em 2025, "
        "números diferentes dos publicados no painel. Com os números vivos, isso não acontece mais.</blockquote>"),
    "ensino_tecnico": (
        "<p>Verifica-se que a participação de nossos alunos em eventos com apresentação de trabalhos "
        f"técnico-científicos tem aumentado nos últimos cinco anos: foram {_n('tec_meta.trabalhos')} trabalhos "
        f"apresentados por {_n('tec_meta.alunos')} alunos na META em 2025. Nossos estudantes conquistaram "
        f"{_n('tec_olimpiadas.premiacoes')} premiações em {_n('tec_olimpiadas.olimpiadas')} olimpíadas do "
        f"conhecimento.</p>"),
    "cooperacao_internacional": (
        "<p>Os dados de 2025 indicam a consolidação das ações de internacionalização da Secretaria de Relações "
        f"Internacionais. A mobilidade discente manteve-se em nível elevado, com {_n('ri_mobilidade.saida')} alunos "
        f"enviados e {_n('ri_mobilidade.entrada')} recebidos. O Programa de Dupla Diplomação contou com "
        f"{_n('ri_series.dupla_diplomacao')} alunos, e a mobilidade docente chegou a {_n('ri_series.docentes')} "
        f"professores.</p>"),
}


def _destaques(itens):
    return {"itens": [{"ref": r, "col": c, "rotulo": rot, "legenda": leg} for r, c, rot, leg in itens]}


# Gráficos no formato do RG 2025 publicado (p. 37–38 e 50–61): barras com o valor escrito e, quando o
# RG mostrava os recursos junto, uma linha laranja sobre as barras com eixo próprio ("linha").
def _combo(linha_barras, linha, **extra):
    return {"tipo": "barras", "linhas": [linha_barras], "linha": linha, **extra}


MONTAGEM = {
    "mensagem": [("texto", None, "", None)],
    "gestao_academica": [
        ("destaques", None, "", _destaques([("ga_cursos.total", "", "cursos ofertados", ""),
                                            ("ga_vagas.total", "", "vagas ofertadas", ""),
                                            ("ga_ingressantes.total", "", "ingressantes", ""),
                                            ("ga_matriculados.total", "", "matriculados", ""),
                                            ("ga_concluintes.total", "", "concluintes", "")])),
        ("grafico", "ga_ingressantes", "Alunos ingressantes", {"tipo": "linhas"}),
        ("grafico", "ga_matriculados", "Alunos matriculados", {"tipo": "linhas"}),
        ("grafico", "ga_concluintes", "Alunos concluintes", {"tipo": "linhas"}),
    ],
    "ensino_tecnico": [
        ("destaques", None, "", _destaques([("tec_numeros.cursos", "", "cursos ofertados", ""),
                                            ("tec_numeros.vagas", "", "vagas ofertadas", ""),
                                            ("tec_numeros.ingressantes", "", "ingressantes", ""),
                                            ("tec_numeros.matriculados", "", "matriculados", ""),
                                            ("tec_numeros.concluintes", "", "concluintes", "")])),
        ("texto", None, "", None),
        ("grafico", "tec_auxilio", "Auxílio discente", _combo("alunos", "recursos")),
        ("grafico", "tec_meta", "Mostra Específica de Trabalhos e Aplicações (META)", _combo("trabalhos", "alunos")),
    ],
    "ensino_graduacao": [
        ("destaques", None, "", _destaques([("grad_numeros.cursos", "", "cursos ofertados", ""),
                                            ("grad_numeros.vagas", "", "vagas ofertadas", ""),
                                            ("grad_numeros.ingressantes", "", "ingressantes", ""),
                                            ("grad_numeros.matriculados", "", "matriculados", ""),
                                            ("grad_numeros.concluintes", "", "concluintes", "")])),
        ("texto", None, "", None),
        ("grafico", "grad_pet", "Grupos PET", _combo("alunos", "recursos")),
        ("grafico", "grad_monitoria", "Monitoria", _combo("alunos", "recursos")),
        ("grafico", "grad_auxilio", "Auxílio discente", _combo("alunos", "recursos")),
        ("grafico", "grad_avaliacao", "Cursos avaliados in loco ou ENADE",
         {"tipo": "pizza", "linhas": ["nota5", "nota4", "nota3"]}),
    ],
    "ensino_pos": [
        ("tabela", "pos_numeros", "Pós-graduação stricto sensu em 2025", {}),
        ("grafico", "pos_bolsas", "Bolsas stricto sensu", _combo("bolsas", "recursos")),
        ("grafico", "pos_auxilio", "Auxílio discente", _combo("alunos", "recursos")),
    ],
    "extensao": [
        ("destaques", None, "", _destaques([("ext_numeros.acoes", "", "ações de extensão executadas", ""),
                                            ("ext_numeros.fomento_interno", "", "com fomento interno", ""),
                                            ("ext_numeros.integradas_ppc", "", "integradas com PPC da graduação", ""),
                                            ("ext_numeros.cursos", "", "cursos de extensão", ""),
                                            ("ext_numeros.vulneraveis", "", "destinadas à população vulnerável", ""),
                                            ("ext_numeros.acoes_pdi", "", "com viés de pesquisa, desenvolvimento e inovação", "")])),
        ("grafico", "ext_campus", "Ações de extensão por campus", {"tipo": "barras_horizontais"}),
        ("grafico", "ext_natureza", "Ações de extensão por natureza", {"tipo": "pizza"}),
        ("grafico", "ext_area", "Ações de extensão por área temática", {"tipo": "barras_horizontais"}),
        ("grafico", "ext_categoria", "Ações de extensão por categoria", {"tipo": "pizza"}),
    ],
    "pesquisa_inovacao": [
        ("destaques", None, "", _destaques([("pq_artigos.total", "", "artigos publicados", "periódicos e eventos"),
                                            ("pq_pi.total", "", "pedidos de propriedade intelectual", ""),
                                            ("pq_captacao.total", "", "captados junto às agências de fomento", ""),
                                            ("pq_ic.alunos", "", "alunos na iniciação científica", "")])),
        ("texto", None, "", None),
        ("grafico", "pq_artigos", "Artigos publicados",
         {"tipo": "barras_horizontais", "linhas": ["eventos", "periodicos", "scival"], "recentes_primeiro": True}),
        ("grafico", "pq_pi", "Pedidos de propriedade intelectual", {"tipo": "barras"}),
        ("grafico", "pq_captacao", "Recursos captados junto às agências de fomento à pesquisa",
         {"tipo": "barras_empilhadas", "linha": "pq_bolsistas.bolsistas", "linha_rotulo": "Bolsistas"}),
        ("grafico", "pq_ic", "Iniciação científica", _combo("recursos", "alunos")),
    ],
    "desenvolvimento_estudantil": [
        ("destaques", None, "", _destaques([("de_bolsas.permanencia", "", "bolsas permanência", ""),
                                            ("de_bolsas.complementacao", "", "bolsas complementação educacional", ""),
                                            ("de_bolsas.alimentacao", "", "bolsas alimentação", ""),
                                            ("de_bolsas.emergencial", "", "bolsas emergenciais", ""),
                                            ("de_bolsas.isentos_re", "", "alunos isentos no restaurante", ""),
                                            ("de_restaurantes.refeicoes", "", "refeições servidas", "")])),
        ("grafico", "de_restaurantes", "Alunos atendidos nos restaurantes estudantis",
         _combo("matriculados", "percentual", linha_rotulo="% de alunos atendidos nos RE")),
        ("grafico", "de_custeio", "Custeio e orçamento da assistência estudantil",
         {"tipo": "linhas", "linhas": ["custos", "pnaes"]}),
        ("grafico", "de_restaurantes", "Refeições servidas nos restaurantes estudantis",
         {"tipo": "linhas", "linhas": ["refeicoes"]}),
    ],
    "inclusao": [
        ("grafico", "inc_nee", "Alunos com necessidades educacionais específicas identificados/atendidos",
         {"tipo": "barras"}),
        ("tabela", "inc_acessibilidade", "Acessibilidade por campus", {}),
        ("tabela", "inc_nee_campus", "Alunos com NEE atendidos por campus", {}),
        ("grafico", "inc_cotistas", "Porcentagem de alunos ingressantes cotistas", {"tipo": "linhas"}),
    ],
    "cooperacao_internacional": [
        ("destaques", None, "", _destaques([("ri_numeros.acordos", "", "acordos de mobilidade internacional", ""),
                                            ("ri_numeros.leitorado", "", "participantes do Leitorado Francês", ""),
                                            ("ri_series.ple", "", "participantes de Português como Língua Estrangeira", "")])),
        ("texto", None, "", None),
        ("grafico", "ri_mobilidade", "Alunos em mobilidade acadêmica", {"tipo": "linhas"}),
        ("grafico", "ri_series", "Participantes do Programa de Português como Língua Estrangeira",
         {"tipo": "barras", "linhas": ["ple"]}),
        ("grafico", "ri_series", "Alunos em dupla diplomação", {"tipo": "barras", "linhas": ["dupla_diplomacao"]}),
        ("grafico", "ri_series", "Docentes em mobilidade internacional", {"tipo": "barras", "linhas": ["docentes"]}),
    ],
    "desenvolvimento_carreiras": [
        ("destaques", None, "", _destaques([("car_numeros.concluintes_estagio", "", "concluintes do estágio obrigatório (EPTNM)", ""),
                                            ("car_numeros.vagas_divulgadas", "", "vagas de estágio e emprego divulgadas", ""),
                                            ("car_numeros.acordos_ativos", "", "acordos de cooperação ativos", "")])),
    ],
    "quem_somos": [
        ("grafico", "gp_docentes", "Titulação dos docentes", {"tipo": "pizza", "inverter": True, "colunas": ["a2025"]}),
        ("grafico", "gp_tae", "Titulação dos servidores TAE", {"tipo": "pizza", "inverter": True, "colunas": ["a2025"]}),
        ("grafico", "gp_capacitacao_valor", "Programas de capacitação",
         {"tipo": "barras", "linha": "gp_capacitacao_servidores.*", "linha_rotulo": "Servidores atendidos",
          "barras_rotulo": "Valor investido"}),
        ("grafico", "gp_eds_cursos", "Quantidade de servidores atendidos por curso EDS", {"tipo": "barras"}),
    ],
}
from relatorio.dados_iniciais.rg2025_gestao import MONTAGEM as _MONTAGEM_GESTAO  # noqa: E402

for _ch, _itens in _MONTAGEM_GESTAO.items():
    MONTAGEM[_ch] = MONTAGEM.get(_ch, []) + _itens


def carregar_blocos(ciclo):
    from relatorio.models import Bloco
    quadros = {q.chave: q for q in ciclo.quadros.all()}
    for sch, itens in MONTAGEM.items():
        sec = ciclo.secoes.get(chave=sch)
        for i, (tipo, qch, titulo, cfg) in enumerate(itens, start=1):
            Bloco.objects.create(secao=sec, ordem=i * 10, tipo=tipo, titulo=titulo, quadro=quadros.get(qch),
                                 config=cfg or {}, conteudo=TEXTOS.get(sch, "") if tipo == "texto" else "")
