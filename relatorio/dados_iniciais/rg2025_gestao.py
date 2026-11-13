"""
Quadros de números das partes do RG 2025 que NÃO são das áreas finalísticas: valor público,
ouvidoria, governança, autoavaliação (CPA), sustentabilidade, informações orçamentárias,
financeiras, de custos, contábeis e de infraestrutura, e órgãos de controle.

Levantados no pente fino do RG 2025 publicado (p. 24–48 e 72–81). Cada quadro traz o setor que
preenche e, no `fonte`, a página do RG 2025 em que o número aparece. Valores de 2025 são os
publicados; onde o RG só trazia o gráfico (sem os números), o histórico fica em branco e a
descrição avisa.
"""
from relatorio import construtor as K
from relatorio.models import Quadro, Regra

I, D, M, P, T = Quadro.INTEIRO, Quadro.DECIMAL, Quadro.MOEDA, Quadro.PERCENTUAL, Quadro.TEXTO
_ = None
MI = 1_000_000


def lin(chave, rotulo, formula="", tipo="", total=True):
    return {"chave": chave, "rotulo": rotulo, "formula": formula, "tipo_valor": tipo, "soma_no_total": total}


def _mi(*vals):
    return [None if v is None else round(v * MI, 2) for v in vals]


def _q2(*args, valores=None, **kw):
    """Quadro com o ano anterior e o ano do relatório; `valores` traz só o ano anterior (2025, publicado)."""
    return K.quadro(*args, anos=2, valores={k: [None] + list(v) for k, v in (valores or {}).items()} or None, **kw)


def _quadro_por_chave(qualquer, chave):
    return Quadro.objects.get(ciclo=qualquer.ciclo, chave=chave)


def carregar(S):
    """Cria os quadros (S: seções do ciclo-base 2025 por chave)."""
    # ---------------------------------------------------------------- Capítulo 4: orçamento (DPG)
    orc = S["orcamento"]
    ex = K.quadro(orc, "orc_execucao", "Execução orçamentária por grupo de despesa", [
        ("pessoal", "Pessoal e encargos sociais"), ("obrigatorias", "Outras despesas correntes (ODC): obrigatórias"),
        ("discricionarias", "Outras despesas correntes (ODC): discricionárias"), ("investimentos", "Investimentos")],
        modo=Quadro.CATEGORIAS, colunas=[("dotacao", "Dotação atualizada"), ("empenhadas", "Despesas empenhadas"),
                                         ("liquidadas", "Despesas liquidadas"), ("pagas", "Despesas pagas")],
        tipo=M, total=True, rotulo_total="Total", setor_sigla="DPG",
        fonte="Tesouro Gerencial (RG 2025, Gráfico 1 e Tabela 1, p. 73–74)",
        descricao="Valores em reais do ano do relatório. A dotação alimenta o Gráfico 1; dotação e despesas, a Tabela 1. "
                  "Em 2025: dotação R$ 570,87 mi (pessoal), 30,80 mi, 64,68 mi e 3,20 mi.",
        valores={"pessoal": _mi(570.87, 570.09, 569.16, 497.69), "obrigatorias": _mi(30.80, 29.98, 29.50, 26.79),
                 "discricionarias": _mi(64.68, 64.67, 59.57, 58.23), "investimentos": _mi(3.20, 3.20, 0.44, 0.42)})
    K.regra(ex, "Empenhado não pode passar da dotação atualizada", "orc_execucao.total.empenhadas",
            "orc_execucao.total.dotacao", "<=")
    K.regra(ex, "Liquidado não pode passar do empenhado", "orc_execucao.total.liquidadas",
            "orc_execucao.total.empenhadas", "<=")
    K.regra(ex, "Pago não pode passar do liquidado", "orc_execucao.total.pagas", "orc_execucao.total.liquidadas", "<=")
    # as mesmas desigualdades em cada grupo: um erro num grupo, compensado por outro, não passa pelo total
    for g, nome in (("pessoal", "pessoal"), ("obrigatorias", "ODC obrigatórias"), ("discricionarias", "ODC discricionárias"),
                    ("investimentos", "investimentos")):
        for a, b, txt in (("empenhadas", "dotacao", "Empenhado ≤ dotação"), ("liquidadas", "empenhadas", "Liquidado ≤ empenhado"),
                          ("pagas", "liquidadas", "Pago ≤ liquidado")):
            K.regra(ex, f"{txt} ({nome})", f"orc_execucao.{g}.{a}", f"orc_execucao.{g}.{b}", "<=")
    loa = _q2(orc, "orc_lei", "Lei Orçamentária Anual (LOA)", [
        lin("autorizado", "Orçamento autorizado na LOA (inicial)"),
        lin("atualizado", "Dotação atualizada no fim do ano", "orc_execucao.total.dotacao"),   # fonte única: Tabela 1
        lin("acrescimo", "Acréscimo por suplementações (%)", "(atualizado - autorizado) / autorizado * 100", P)],
        tipo=M, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, p. 73)",
        valores={"autorizado": [584.93 * MI], "atualizado": [669.55 * MI]})
    K.regra(loa, "Dotação atualizada da LOA igual ao total da execução orçamentária", "orc_lei.atualizado",
            "orc_execucao.total.dotacao", severidade=Regra.AVISO, tolerancia=1)
    K.quadro(orc, "orc_discricionarias", "Orçamento discricionário (outras despesas correntes e investimentos)", [
        ("tesouro", "OCC: Tesouro"), ("receita", "OCC: Receita própria")],
        anos=12, tipo=M, total=True, rotulo_total="Total discricionário", setor_sigla="DPG",
        fonte="Tesouro Gerencial (RG 2025, Gráfico 2, p. 73)",
        descricao="Dotação atualizada, sem emendas parlamentares. Série de dez anos, como no Gráfico 2.",
        valores={"tesouro": [_] + _mi(77.5, 67.8, 64.0, 59.5, 58.7, 56.7, 44.0, 52.1, 59.5, 59.8, 61.1),
                 "receita": [_] + _mi(5.7, 3.3, 3.9, 5.3, 9.0, 9.5, 3.9, 2.9, 6.8, 5.4, 4.0)})

    dst = S["destaques_orcamentarios"]
    _q2(dst, "orc_destaques", "Dotações recebidas por destaque", [
        ("pessoal", "Despesas de pessoal"), ("correntes", "Despesas correntes"), ("investimento", "Despesas de investimento")],
        tipo=M, total=True, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, p. 74)",
        valores={"pessoal": [1.24 * MI], "correntes": [4.18 * MI], "investimento": [8.07 * MI]})

    exe = S["execucao_orcamentaria"]
    _q2(exe, "orc_maiores_despesas", "Dez maiores despesas discricionárias", [
        ("limpeza", "Limpeza"), ("restaurantes", "Restaurantes"), ("vigilancia", "Vigilância"),
        ("bolsas_assistencia", "Bolsas de assistência estudantil"), ("bolsas_academicas", "Bolsas acadêmicas"),
        ("agua_luz_gas", "Água, luz e gás"), ("reformas", "Reformas"), ("transporte", "Transporte"),
        ("extensao", "Ações de extensão"), ("manutencao", "Manutenção")],
        tipo=M, total=True, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, Gráfico 3, p. 75)",
        descricao="Se as dez maiores despesas de 2026 forem outras, peça ao administrador para trocar os nomes.",
        valores={"limpeza": [14.0 * MI], "restaurantes": [10.2 * MI], "vigilancia": [5.8 * MI],
                 "bolsas_assistencia": [5.6 * MI], "bolsas_academicas": [4.8 * MI], "agua_luz_gas": [4.7 * MI],
                 "reformas": [4.4 * MI], "transporte": [2.2 * MI], "extensao": [1.7 * MI], "manutencao": [1.7 * MI]})
    inv = _q2(exe, "orc_investimentos", "Uso do recurso de investimentos", [
        ("equip_labs", "Equipamentos: laboratórios"), ("obras", "Obras"), ("acervo", "Acervo bibliográfico"),
        ("equip_comuns", "Equipamentos: áreas comuns")],
        tipo=P, total=True, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, Gráfico 4, p. 75)",
        descricao="Percentual do total executado em investimentos.",
        valores={"equip_labs": [46], "obras": [31], "acervo": [15], "equip_comuns": [8]})
    K.regra(inv, "Os percentuais de investimentos somam 100%", "orc_investimentos.total", "100",
            severidade=Regra.AVISO, tolerancia=1)

    rap = _q2(S["restos_a_pagar"], "orc_rap", "Restos a pagar", [
        lin("rpnp_total", "Não processados: total inscrito (R$)", tipo=M, total=False),
        lin("rpnp_cefet", "Não processados: recursos do próprio orçamento (%)", tipo=P, total=False),
        lin("rpnp_mec", "Não processados: descentralizados pelo MEC (%)", tipo=P, total=False),
        lin("rpnp_destaques", "Não processados: destaques de outras instituições (%)", tipo=P, total=False),
        lin("rpnp_a_liquidar", "Não processados: restam a liquidar (R$)", tipo=M, total=False),
        lin("rpnp_a_liquidar_pct", "Não processados: restam a liquidar (% do inscrito e reinscrito)", tipo=P, total=False),
        lin("rpp_total", "Processados: total (R$)", tipo=M, total=False),
        lin("rpp_pessoal", "Processados: pessoal, encargos e benefícios (%)", tipo=P, total=False)],
        tipo=M, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, p. 76)",
        valores={"rpnp_total": [16.39 * MI], "rpnp_cefet": [77.95], "rpnp_mec": [13.76], "rpnp_destaques": [8.29],
                 "rpnp_a_liquidar": [5.94 * MI], "rpnp_a_liquidar_pct": [36.26], "rpp_total": [56.76 * MI],
                 "rpp_pessoal": [91.46]})
    K.regra(rap, "As três origens dos restos a pagar não processados somam 100%",
            "orc_rap.rpnp_cefet + orc_rap.rpnp_mec + orc_rap.rpnp_destaques", "100", severidade=Regra.AVISO,
            tolerancia=0.1)

    _q2(S["receitas"], "orc_receitas", "Receitas próprias (Fonte 1050)", [
        lin("previsto", "Dotação autorizada na LOA"), lin("arrecadado", "Arrecadação efetiva"),
        lin("diferenca", "Superávit (ou déficit) de arrecadação", "arrecadado - previsto")],
        tipo=M, setor_sigla="DPG", fonte="Tesouro Gerencial (RG 2025, p. 76)",
        valores={"previsto": [4.0 * MI], "arrecadado": [5.85 * MI]})

    cus = S["custos"]
    _q2(cus, "custos_operacionais", "Custos das principais despesas operacionais monitoradas", [
        ("limpeza", "Limpeza"), ("vigilancia", "Vigilância"), ("transporte", "Transporte"),
        ("energia", "Energia elétrica"), ("agua", "Água e esgoto"), ("diarias", "Diárias e passagens")],
        tipo=M, setor_sigla="DPG", fonte="DPG (RG 2025, p. 77)",
        descricao="A variação em relação ao ano anterior é calculada sozinha e pode ser citada no texto.",
        valores={"limpeza": [14.0 * MI], "vigilancia": [5.82 * MI], "transporte": [1.95 * MI],
                 "energia": [2.63 * MI], "agua": [2.04 * MI], "diarias": [1.20 * MI]})
    tr = _q2(cus, "custos_transporte", "Custo do transporte de bens e passageiros", [
        ("condutores", "Serviço de condutores"), ("manutencao", "Manutenção dos veículos"),
        ("abastecimento", "Abastecimento")],
        tipo=M, total=True, setor_sigla="DPG", fonte="DPG (RG 2025, p. 77)",
        valores={"condutores": [946000], "manutencao": [597000], "abastecimento": [411000]})
    K.regra(tr, "Custo do transporte igual à soma de condutores, manutenção e abastecimento",
            "custos_transporte.total", "custos_operacionais.transporte", severidade=Regra.AVISO, tolerancia=10000)

    con = S["contabeis"]
    _q2(con, "pat_bens", "Bens incorporados ao patrimônio (tombados)", [
        ("proprios", "Adquiridos com recursos próprios"), ("doacao", "Recebidos por doação")],
        tipo=M, total=True, rotulo_total="Total incorporado", setor_sigla="DPG",
        fonte="SIADS / DPG (RG 2025, p. 78)", valores={"proprios": [1.95 * MI], "doacao": [2.98 * MI]})
    _q2(con, "pat_desfazimento", "Desfazimento de ativos", [
        lin("processos", "Processos de desfazimento executados", tipo=I, total=False),
        lin("catadores", "Doações sustentáveis a associações de catadores (R$)", tipo=M, total=False),
        lin("computadores", "Transferência ao Programa Computadores para Inclusão (R$)", tipo=M, total=False)],
        tipo=M, setor_sigla="DPG", fonte="DPG (RG 2025, p. 78)",
        valores={"processos": [13], "catadores": [18640.48], "computadores": [41910.43]})
    _q2(con, "frota_veiculos", "Frota institucional", [
        ("automoveis", "Automóveis"), ("caminhonetes", "Caminhonetes"), ("caminhoes", "Caminhões"),
        ("microonibus", "Micro-ônibus"), ("onibus", "Ônibus"), ("vans", "Vans")],
        tipo=I, total=True, rotulo_total="Total de veículos", setor_sigla="DPG", fonte="DPG (RG 2025, p. 78)",
        valores={"automoveis": [22], "caminhonetes": [18], "caminhoes": [2], "microonibus": [4], "onibus": [3],
                 "vans": [5]})
    K.quadro(con, "frota_km", "Quilometragem rodada por tipo de veículo", [
        ("automovel", "Automóvel"), ("caminhao", "Caminhão"), ("caminhonete", "Caminhonete"),
        ("microonibus", "Micro-ônibus"), ("onibus", "Ônibus"), ("van", "Van")],
        anos=12, tipo=I, total=True, rotulo_total="Total (km)", setor_sigla="DPG", obrigatorio=False,
        fonte="DPG (RG 2025, Gráfico 5, p. 78)",
        descricao="O RG 2025 publicou só o gráfico (cerca de 412.000 km em 2025 e 350.000 km em 2024), sem os números "
                  "por tipo. O histórico por tipo de veículo precisa ser informado pela DPG ao Master (Corrigir anos "
                  "publicados) para o gráfico sair completo.")
    _q2(con, "infra_numeros", "Infraestrutura física", [
        lin("campi", "Campi", tipo=I, total=False), lin("municipios", "Municípios", tipo=I, total=False),
        lin("area_construida", "Área construída (m²)", tipo=D, total=False),
        lin("area_total", "Área total (m²)", tipo=D, total=False)],
        tipo=D, casas=0, setor_sigla="DPG", fonte="DPG (RG 2025, p. 25 e 78)",
        valores={"campi": [11], "municipios": [9], "area_construida": [200000], "area_total": [500000]})

    # ------------------------------------------------------- Capítulo 1: valor público, TIC, ouvidoria
    _q2(S["valor_publico"], "tic_numeros", "Gestão de TIC", [
        lin("parque", "Parque computacional (equipamentos)", tipo=I, total=False),
        lin("despesas_ti", "Despesas empenhadas em TI (R$)", tipo=M, total=False)],
        tipo=M, setor_sigla="DTI", fonte="DTI (RG 2025, p. 25)",
        valores={"parque": [2500], "despesas_ti": [1689121.41]})

    amb = S["ambiente_externo"]
    K.quadro(amb, "ouv_manifestacoes", "Manifestações recebidas pela Ouvidoria", [
        ("denuncia", "Denúncia"), ("comunicacao", "Comunicação"), ("solicitacao", "Solicitação"),
        ("reclamacao", "Reclamação"), ("elogio", "Elogio"), ("sugestao", "Sugestão"), ("simplifique", "Simplifique!")],
        anos=8, tipo=I, total=True, setor_sigla="GAB", fonte="Fala.BR / Ouvidoria (RG 2025, p. 26)",
        descricao="Desde 2024 a CGU trata a comunicação como denúncia: na linha Comunicação, digite 0.",
        valores={"comunicacao": [_, 42, 37, 21, 43, 92, 0, 0], "denuncia": [_, 23, 12, 9, 31, 42, 290, 198],
                 "solicitacao": [_, 16, 17, 24, 30, 38, 46, 107], "reclamacao": [_, 22, 18, 24, 58, 48, 64, 166],
                 "elogio": [_, 2, 4, 2, 2, 4, 5, 5], "sugestao": [_, 4, 2, 2, 0, 5, 2, 5],
                 "simplifique": [_, _, _, _, _, _, _, 1]})
    _q2(amb, "ouv_resolutividade", "Resolutividade das manifestações (indicada pela Ouvidoria)", [
        lin("sim", "Resolvidas"), lin("nao", "Não resolvidas", "100 - sim")],
        tipo=P, setor_sigla="GAB", fonte="Fala.BR / Ouvidoria (RG 2025, p. 29)",
        descricao="Considera as manifestações com resposta conclusiva pela Ouvidoria.", valores={"sim": [90.36]})
    _q2(amb, "ouv_ranking_assunto", "Manifestações por assunto (ranking da Ouvidoria)", [
        ("acesso_info", "Acesso à informação"), ("ouvidoria", "Ouvidoria"), ("assedio_moral", "Assédio moral"),
        ("beneficios", "Benefícios e serviços"), ("abono", "Abono salarial"),
        ("ept", "Educação Profissional e Tecnológica"), ("superior", "Educação Superior"),
        ("conduta", "Conduta ética e irregularidades de servidores"), ("agente", "Agente Público"),
        ("concursos", "Concursos e processos seletivos")],
        tipo=I, total=False, setor_sigla="GAB", fonte="Fala.BR (RG 2025, p. 27)",
        descricao="Os 10 assuntos com mais manifestações no ano. Se o ranking do ano tiver outros assuntos, peça ao "
                  "Master para trocar os nomes das linhas.",
        valores={"acesso_info": [29], "ouvidoria": [25], "assedio_moral": [22], "beneficios": [20], "abono": [18],
                 "ept": [18], "superior": [17], "conduta": [16], "agente": [13], "concursos": [12]})
    _q2(amb, "ouv_ranking_subassunto", "Manifestações por subassunto (ranking da Ouvidoria)", [
        ("conduta_trabalho", "Conduta imprópria nas relações de trabalho"),
        ("conduta_sexual", "Conduta de natureza sexual"), ("discriminacao", "Discriminação"),
        ("racismo", "Racismo religioso"), ("enfrentamento", "Enfrentamento ao assédio moral, discriminação…"),
        ("assedio_sexual", "Assédio sexual – servidor / discente / funcionário"),
        ("autonomia", "Autonomia universitária"), ("cursos_prof", "Cursos profissionalizantes"),
        ("salario", "Salário e valorização dos professores"),
        ("terceirizado", "Servidor – discente – terceirizado – discriminação")],
        tipo=I, total=False, setor_sigla="GAB", fonte="Fala.BR (RG 2025, p. 27)",
        descricao="Os 10 subassuntos com mais manifestações no ano. Se o ranking do ano tiver outros, peça ao Master "
                  "para trocar os nomes das linhas.",
        valores={"conduta_trabalho": [21], "conduta_sexual": [7], "discriminacao": [6], "racismo": [2],
                 "enfrentamento": [1], "assedio_sexual": [1], "autonomia": [1], "cursos_prof": [1], "salario": [1],
                 "terceirizado": [1]})
    _q2(amb, "ouv_lai", "Pedidos de acesso à informação (LAI)", [
        lin("pedidos", "Total de pedidos", tipo=I, total=False),
        lin("no_prazo", "Respondidos no prazo (%)", tipo=P, total=False),
        lin("tempo_medio", "Tempo médio de resposta (dias)", tipo=D, total=False),
        lin("dias_omissao", "Dias sem omissão na data de referência", tipo=I, total=False),
        lin("recursos", "Concedidos que foram a recurso (%)", tipo=P, total=False)],
        tipo=I, casas=2, setor_sigla="GAB", fonte="Painel da LAI / CGU (RG 2025, p. 29)",
        valores={"pedidos": [170], "no_prazo": [90.48], "tempo_medio": [11.2], "dias_omissao": [7], "recursos": [9.0]})
    _q2(amb, "ouv_lai_respostas", "Distribuição das respostas aos pedidos de acesso à informação", [
        ("concedido", "Acesso concedido"), ("sem_competencia", "Órgão sem competência para responder"),
        ("inexistente", "Informação inexistente"), ("nao_e_pedido", "Não se trata de solicitação de informação"),
        ("duplicada", "Pergunta duplicada/repetida"), ("negado", "Acesso negado"),
        ("parcial", "Acesso parcialmente concedido")],
        tipo=P, total=True, setor_sigla="GAB", fonte="Painel da LAI / CGU (RG 2025, p. 29)",
        valores={"concedido": [59.52], "sem_competencia": [20.24], "inexistente": [9.52], "nao_e_pedido": [7.14],
                 "duplicada": [1.79], "negado": [1.19], "parcial": [0.60]})

    _q2(S["sustentabilidade_ambiental"], "sust_energia", "Eficiência energética (PGEN)", [
        lin("consumo_noturno", "Consumo de energia entre 22h e 6h (% do total)", tipo=P, total=False),
        lin("economia", "Economia anual estimada com medidas de conscientização (R$)", tipo=M, total=False),
        lin("custo_energia", "Gasto com energia elétrica (R$)", "custos_operacionais.energia", M, total=False)],
        tipo=M, setor_sigla="DPG", fonte="PGEN / DPG (RG 2025, p. 36)",
        valores={"consumo_noturno": [25], "economia": [900000]})
    _q2(S["sustentabilidade_social"], "sust_vagas_reservadas", "Ocupação das vagas reservadas (Lei de Cotas)", [
        ("eptnm", "Educação Profissional Técnica de Nível Médio"), ("graduacao", "Graduação"),
        ("pos", "Pós-graduação")],
        tipo=P, setor_sigla="DAE", fonte="SRCA / DAE (RG 2025, p. 30)",
        descricao="Percentual das vagas reservadas para grupos prioritários que foram ocupadas.",
        valores={"eptnm": [45], "graduacao": [33], "pos": [8]})

    # ------------------------------------------------------------- Capítulo 2: governança e CPA
    K.quadro(S["governanca"], "gov_indices", "Índices de governança e gestão do TCU (iESGo)", [
        ("igg", "iGG – Índice integrado de governança e gestão públicas"),
        ("igovpub", "iGovPub – Governança pública organizacional"), ("lid", "Capacidade em liderança"),
        ("estr", "Capacidade em estratégia"), ("cont", "Capacidade em controle"),
        ("igestpessoas", "iGestPessoas – Gestão de pessoas"), ("igestti", "iGestTI – Gestão de TI e segurança da informação"),
        ("igestcontrat", "iGestContrat – Gestão de contratações"), ("igestorcament", "iGestOrcament – Gestão orçamentária"),
        ("iesgo", "iESGo – Índice ESG"), ("ies", "iES – Sustentabilidade ambiental e social")],
        modo=Quadro.CATEGORIAS, colunas=[("anterior", "Levantamento anterior"), ("ultimo", "Último levantamento")],
        tipo=P, setor_sigla="DGDI", obrigatorio=False,
        valores={"igg": [30.25, 57.39], "igestcontrat": [53.14, 57.95], "igestorcament": [36.09, 60.47]}, fonte="TCU – Levantamento iESGo (RG 2025, p. 41–43)",
        descricao="Resultados do levantamento do TCU (o último foi o iESGo 2024). Os gráficos de radar do TCU continuam "
                  "como figura. Em 2024: iGG 57,39%; iGestOrcament 60,47%; iGestContrat 57,95%.")
    ge = S["gestao_estrategica"]
    _q2(ge, "cpa_participacao", "Participação na autoavaliação (CPA)", [
        ("tecnico", "Alunos dos cursos técnicos"), ("pos", "Alunos da pós-graduação"),
        ("grad_s2", "Graduação – 2º semestre do ano anterior"), ("grad_s1", "Graduação – 1º semestre do ano")],
        tipo=P, setor_sigla="CPA", fonte="CPA (RG 2025, p. 46–47)",
        valores={"tecnico": [13], "pos": [31.46], "grad_s2": [21], "grad_s1": [10]})
    cc = _q2(ge, "cpa_cursos", "Conceitos dos cursos de graduação avaliados", [
        lin("avaliados", "Cursos avaliados nos últimos dois anos", total=False),
        lin("conceito5", "Conceito 5", total=False), lin("conceito4", "Conceito 4", total=False),
        lin("conceito3", "Conceito 3", total=False)],
        tipo=I, setor_sigla="CPA", fonte="CPA / INEP (RG 2025, p. 46)",
        valores={"avaliados": [23], "conceito5": [12], "conceito4": [8], "conceito3": [3]})
    K.regra(cc, "Conceitos 5, 4 e 3 somam os cursos avaliados",
            "cpa_cursos.conceito5 + cpa_cursos.conceito4 + cpa_cursos.conceito3", "cpa_cursos.avaliados",
            severidade=Regra.AVISO)
    # o mesmo dado também é informado pela graduação: os dois têm de bater
    for c5, n5 in (("conceito5", "nota5"), ("conceito4", "nota4"), ("conceito3", "nota3")):
        K.regra(cc, f"{c5.replace('conceito', 'Conceito ')} igual ao da Avaliação dos cursos de graduação",
                f"cpa_cursos.{c5}", f"grad_avaliacao.{n5}", severidade=Regra.AVISO)
    K.regra(_quadro_por_chave(cc, "ouv_lai_respostas"), "As respostas aos pedidos da LAI somam 100%",
            "ouv_lai_respostas.total", "100", severidade=Regra.AVISO, tolerancia=0.1)

    ctl = _q2(S["orgaos_controle"], "controle_numeros", "Manifestações dos órgãos de controle em números", [
        lin("recomendacoes_cgu", "Recomendações da CGU no ano", total=False),
        lin("processos_tcu", "Processos no TCU relacionados à instituição", total=False),
        lin("tcu_pessoal", "… relativos a atos de pessoal", total=False),
        lin("tcu_fiscalizacoes", "… referentes a fiscalizações", total=False),
        lin("acordaos_determinacoes", "Acórdãos com determinações à instituição", total=False)],
        tipo=I, setor_sigla="GAB", fonte="AUDIN / GAB (RG 2025, p. 81)",
        valores={"recomendacoes_cgu": [3], "processos_tcu": [26], "tcu_pessoal": [24], "tcu_fiscalizacoes": [2],
                 "acordaos_determinacoes": [3]})
    K.regra(ctl, "Processos no TCU = atos de pessoal + fiscalizações", "controle_numeros.tcu_pessoal + "
            "controle_numeros.tcu_fiscalizacoes", "controle_numeros.processos_tcu", severidade=Regra.AVISO)


def _d(itens):
    return {"itens": [{"ref": r, "col": "", "rotulo": rot, "legenda": leg} for r, rot, leg in itens]}


# Tabelas que, como no RG, mostram só o ano do relatório (o ano anterior fica para comparação nos números).
ANO = {"colunas": ["a2025"]}

# Blocos (tabelas, gráficos e painéis) destas seções, na ordem do RG 2025.
MONTAGEM = {
    "orcamento": [
        ("grafico", "orc_execucao", "Gráfico 1 – Principais grupos de despesas do orçamento institucional",
         {"tipo": "rosca", "colunas": ["dotacao"], "inverter": True}),
        ("grafico", "orc_discricionarias", "Gráfico 2 – Evolução orçamentária (despesas discricionárias) na última década",
         {"tipo": "barras_empilhadas"}),
        ("tabela", "orc_lei", "Lei Orçamentária Anual", ANO),
    ],
    "destaques_orcamentarios": [
        ("tabela", "orc_destaques", "Dotações recebidas por destaque", ANO),
    ],
    "execucao_orcamentaria": [
        ("tabela", "orc_execucao", "Tabela 1 – Despesas empenhadas, liquidadas e pagas, por grupo de despesa",
         {"razao": [{"rotulo": "Empenhadas / dotação (%)", "num": "empenhadas", "den": "dotacao"}]}),
        ("grafico", "orc_maiores_despesas", "Gráfico 3 – Dez maiores despesas discricionárias",
         {"tipo": "barras", "colunas": ["a2025"], "inverter": True}),
        ("grafico", "orc_investimentos", "Gráfico 4 – Uso do recurso orçamentário relativo a investimentos",
         {"tipo": "pizza", "colunas": ["a2025"], "inverter": True}),
    ],
    "restos_a_pagar": [("tabela", "orc_rap", "Restos a pagar", ANO)],
    "receitas": [("tabela", "orc_receitas", "Receitas próprias", ANO)],
    "custos": [
        ("destaques", None, "Custos das principais despesas operacionais monitoradas", _d([
            ("custos_operacionais.limpeza", "", "Limpeza"), ("custos_operacionais.vigilancia", "", "Vigilância"),
            ("custos_operacionais.transporte", "", "Transporte"), ("custos_operacionais.energia", "", "Energia elétrica"),
            ("custos_operacionais.agua", "", "Água e esgoto"), ("custos_operacionais.diarias", "", "Diárias e passagens")])),
        ("tabela", "custos_transporte", "Custo do transporte de bens e passageiros", ANO),
    ],
    "contabeis": [
        ("tabela", "pat_bens", "Bens incorporados ao patrimônio", ANO),
        ("tabela", "frota_veiculos", "Frota institucional", ANO),
        ("grafico", "frota_km", "Gráfico 5 – Quilometragem total por ano e tipo de veículo", {"tipo": "barras_empilhadas"}),
    ],
    "orgaos_controle": [("tabela", "controle_numeros", "Manifestações dos órgãos de controle em números", ANO)],
    "valor_publico": [
        ("destaques", None, "Geração de valor público em números", _d([
            ("gp_docentes.total", "", "docentes"), ("gp_tae.total", "", "técnico-administrativos"),
            ("gp_capacitacao_valor.total", "", "destinados à capacitação"),
            ("infra_numeros.campi", "", "campi"), ("infra_numeros.municipios", "", "municípios"),
            ("infra_numeros.area_construida", "", "m² de área construída"),
            ("tic_numeros.parque", "", "equipamentos no parque computacional"),
            ("tic_numeros.despesas_ti", "", "em despesas empenhadas em TI"),
            ("orc_lei.atualizado", "", "de dotação atualizada (LOA)"),
            ("orc_execucao.pessoal.dotacao", "", "para salários, encargos e benefícios"),
            ("orc_discricionarias.total", "", "de orçamento de custeio e capital (Tesouro + receita)"),
            ("ga_matriculados.total", "", "alunos matriculados")])),
    ],
    "ambiente_externo": [
        ("tabela", "ouv_manifestacoes", "Manifestações recebidas pela Ouvidoria", {}),
        ("tabela", "ouv_resolutividade", "Resolutividade das manifestações", ANO),
        ("tabela", "ouv_lai", "Pedidos de acesso à informação (LAI)", ANO),
        ("grafico", "ouv_lai_respostas", "Distribuição das respostas dos pedidos de acesso à informação",
         {"tipo": "barras_horizontais", "colunas": ["a2025"], "inverter": True}),
    ],
    "sustentabilidade_ambiental": [("tabela", "sust_energia", "Eficiência energética", ANO)],
    "sustentabilidade_social": [("tabela", "sust_vagas_reservadas", "Ocupação das vagas reservadas", ANO)],
    "governanca": [("tabela", "gov_indices", "Índices de governança e gestão do TCU", {})],
    "gestao_estrategica": [
        ("tabela", "cpa_participacao", "Participação na autoavaliação institucional", ANO),
        ("tabela", "cpa_cursos", "Conceitos dos cursos de graduação avaliados", ANO),
    ],
}
