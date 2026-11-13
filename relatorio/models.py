"""
Estrutura do Relatório de Gestão e quadros de dados.

  Ciclo   — um relatório anual (ex.: RG 2026). Novo ciclo copia a estrutura do anterior
            e herda os valores dos anos passados, que ficam travados.
  Secao   — capítulo ou seção do relatório, com os setores responsáveis.
  Quadro  — tabela de dados de uma seção (ex.: "Matriculados por nível"), com o setor
            dono dos dados. As colunas são anos (série histórica) ou categorias.
  Linha   — uma linha do quadro. Sem fórmula, é preenchida; com fórmula, é calculada
            (pode buscar valores de outros quadros: fonte única do dado).
  Coluna  — um ano ou uma categoria. Colunas de anos anteriores ficam travadas.
  Valor   — o número (ou texto) de uma célula, com histórico completo.
  Regra   — verificação de consistência (ex.: soma dos níveis = total da Gestão Acadêmica).
"""
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.functional import cached_property
from simple_history.models import HistoricalRecords

from contas.models import Setor

CHAVE = RegexValidator(r"^[a-z][a-z0-9_]*$",
                       "Use letras minúsculas, números e _ (sem espaços, acentos ou hífen), começando por letra.")


class Ciclo(models.Model):
    PREPARACAO, COLETA, REVISAO, ENCERRADO = "preparacao", "coleta", "revisao", "encerrado"
    SITUACOES = [
        (PREPARACAO, "Em preparação (estrutura sendo montada)"),
        (COLETA, "Coleta aberta (setores preenchendo)"),
        (REVISAO, "Em revisão (só o Master edita)"),
        (ENCERRADO, "Encerrado (somente leitura)"),
    ]
    ano = models.PositiveSmallIntegerField("ano-base", unique=True)
    titulo = models.CharField("título", max_length=200)
    situacao = models.CharField("situação", max_length=12, choices=SITUACOES, default=PREPARACAO)
    prazo = models.DateField("prazo da coleta", null=True, blank=True)
    anos_serie = models.PositiveSmallIntegerField("anos na série histórica", default=5,
                                                  help_text="Quantos anos os quadros de série histórica mostram.")
    observacao = models.TextField("observação", blank=True, default="")
    origem = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               help_text="Ciclo do qual a estrutura foi copiada.")
    criado_em = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-ano"]

    def __str__(self):
        return self.titulo

    @property
    def anos(self):
        return list(range(self.ano - self.anos_serie + 1, self.ano + 1))


class Secao(models.Model):
    NAO_INICIADA, PREENCHIMENTO, ENVIADA, APROVADA = "nao_iniciada", "preenchimento", "enviada", "aprovada"
    SITUACOES = [
        (NAO_INICIADA, "Não iniciada"),
        (PREENCHIMENTO, "Em preenchimento"),
        (ENVIADA, "Enviada ao Master"),
        (APROVADA, "Aprovada"),
    ]
    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="secoes")
    pai = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="filhas",
                            verbose_name="capítulo")
    ordem = models.PositiveIntegerField(default=0)
    chave = models.CharField(max_length=60, validators=[CHAVE])
    titulo = models.CharField("título", max_length=255)
    orientacao = models.TextField("orientação aos setores", blank=True, default="",
                                  help_text="O que deve ser apresentado nesta seção (aparece para quem preenche).")
    setores = models.ManyToManyField(Setor, blank=True, related_name="secoes", verbose_name="setores responsáveis")
    situacao = models.CharField("situação", max_length=15, choices=SITUACOES, default=NAO_INICIADA)
    nivel = models.PositiveSmallIntegerField("nível", default=1, choices=[(1, "seção"), (2, "subseção")],
                                             help_text="Subseção: aparece dentro da seção anterior (ex.: as áreas "
                                                       "finalísticas dentro de “Desempenho e resultados”).")
    referencia = models.TextField("texto de referência", blank=True, default="",
                                  help_text="Texto desta seção no relatório anterior (só para consulta).")
    referencia_fonte = models.CharField("origem da referência", max_length=120, blank=True, default="",
                                        help_text="Ex.: RG 2025, p. 50–51.")
    history = HistoricalRecords(m2m_fields=[setores])

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "seção"
        verbose_name_plural = "seções"
        constraints = [models.UniqueConstraint(fields=["ciclo", "chave"], name="secao_chave_unica_no_ciclo")]

    def __str__(self):
        return self.titulo

    @property
    def referencia_pagina(self):
        """Primeira página da referência (ex.: "RG 2025, p. 50–51" -> 50), para abrir o PDF no lugar certo."""
        import re
        m = re.search(r"p\. (\d+)", self.referencia_fonte or "")
        return int(m.group(1)) if m else None

    @property
    def e_capitulo(self):
        return self.pai_id is None


class Quadro(models.Model):
    INTEIRO, DECIMAL, MOEDA, PERCENTUAL, TEXTO, SIM_NAO = "inteiro", "decimal", "moeda", "percentual", "texto", "sim_nao"
    TIPOS = [
        (INTEIRO, "Número inteiro"),
        (DECIMAL, "Número com casas decimais"),
        (MOEDA, "Valor em R$"),
        (PERCENTUAL, "Percentual (%)"),
        (TEXTO, "Texto curto"),
        (SIM_NAO, "Sim / Não"),
    ]
    ANOS, CATEGORIAS = "anos", "categorias"
    MODOS = [(ANOS, "Anos (série histórica)"), (CATEGORIAS, "Categorias (colunas livres)")]

    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="quadros")
    secao = models.ForeignKey(Secao, on_delete=models.CASCADE, related_name="quadros", verbose_name="seção")
    ordem = models.PositiveIntegerField(default=0)
    chave = models.CharField(max_length=60, validators=[CHAVE],
                             help_text="Identificador usado nas fórmulas e regras (ex.: matriculados).")
    titulo = models.CharField("título", max_length=255)
    descricao = models.TextField("definição / orientação", blank=True, default="",
                                 help_text="O que deve ser informado e como contar (ex.: conceito da Plataforma Nilo Peçanha).")
    fonte = models.CharField(max_length=255, blank=True, default="", help_text="Ex.: SRCA / Sistema Acadêmico.")
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, null=True, blank=True, related_name="quadros",
                              verbose_name="setor responsável pelos dados",
                              help_text="Vazio = os setores responsáveis pela seção.")
    tipo_valor = models.CharField("tipo dos valores", max_length=12, choices=TIPOS, default=INTEIRO)
    casas_decimais = models.PositiveSmallIntegerField(default=2)
    modo_colunas = models.CharField("colunas", max_length=12, choices=MODOS, default=ANOS)
    anos_exibidos = models.PositiveSmallIntegerField(
        "anos exibidos", default=5, help_text="Para colunas por ano: quantos anos (1 = só o ano-base).")
    linha_total = models.BooleanField("mostrar linha de total", default=False)
    coluna_total = models.BooleanField("mostrar coluna de total", default=False)
    rotulo_total = models.CharField("rótulo do total", max_length=60, default="Total")
    obrigatorio = models.BooleanField("preenchimento obrigatório", default=True,
                                      help_text="Todas as células editáveis (não travadas) precisam ser preenchidas.")
    variacao_alerta = models.DecimalField(
        "alerta de variação (%)", max_digits=6, decimal_places=1, null=True, blank=True,
        help_text="Variação em relação ao ano anterior acima deste percentual exige justificativa. Vazio = sem alerta.")
    history = HistoricalRecords()

    class Meta:
        ordering = ["secao__ordem", "ordem", "id"]
        constraints = [models.UniqueConstraint(fields=["ciclo", "chave"], name="quadro_chave_unica_no_ciclo")]

    def __str__(self):
        return self.titulo

    def setores_responsaveis(self):
        if self.setor_id:
            return [self.setor]
        return list(self.secao.setores.all())


class Linha(models.Model):
    quadro = models.ForeignKey(Quadro, on_delete=models.CASCADE, related_name="linhas")
    ordem = models.PositiveIntegerField(default=0)
    chave = models.CharField(max_length=60, validators=[CHAVE])
    rotulo = models.CharField("rótulo", max_length=600)
    formula = models.CharField(
        "fórmula", max_length=500, blank=True, default="",
        help_text="Vazio = preenchida pelo setor. Ex.: tecnico + graduacao · atendidos / matriculados * 100 · "
                  "gestao_matriculados.total")
    tipo_valor = models.CharField("tipo (se diferente do quadro)", max_length=12, choices=Quadro.TIPOS, blank=True,
                                  default="")
    minimo = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    maximo = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    soma_no_total = models.BooleanField("entra na linha de total", default=True)
    # quem preenche esta linha, quando é diferente do setor do quadro (ex.: metas do PDI, uma unidade por meta)
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                              verbose_name="setor desta linha")
    history = HistoricalRecords()

    class Meta:
        ordering = ["ordem", "id"]
        constraints = [models.UniqueConstraint(fields=["quadro", "chave"], name="linha_chave_unica_no_quadro")]

    def __str__(self):
        return self.rotulo

    @property
    def calculada(self):
        return bool(self.formula.strip())

    @cached_property
    def importada(self):
        """Calculada a partir de OUTRO quadro (fonte única, ex.: ga_matriculados.tecnico). Além do valor
        automático, aceita um valor digitado; se os dois forem diferentes, a plataforma aponta a divergência."""
        import re
        return bool(self.formula and re.search(r"\b[a-z][a-z0-9_]*\.[a-z]", self.formula))

    @property
    def tipo(self):
        return self.tipo_valor or self.quadro.tipo_valor


class Coluna(models.Model):
    quadro = models.ForeignKey(Quadro, on_delete=models.CASCADE, related_name="colunas")
    ordem = models.PositiveIntegerField(default=0)
    chave = models.CharField(max_length=60, validators=[CHAVE])
    rotulo = models.CharField("rótulo", max_length=120)
    ano = models.PositiveSmallIntegerField(null=True, blank=True)
    travada = models.BooleanField(default=False, help_text="Ano anterior já publicado: só o Master altera, com justificativa.")
    history = HistoricalRecords()

    class Meta:
        ordering = ["ordem", "id"]
        constraints = [models.UniqueConstraint(fields=["quadro", "chave"], name="coluna_chave_unica_no_quadro")]

    def __str__(self):
        return self.rotulo


class Valor(models.Model):
    linha = models.ForeignKey(Linha, on_delete=models.CASCADE, related_name="valores")
    coluna = models.ForeignKey(Coluna, on_delete=models.CASCADE, related_name="valores")
    numero = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    texto = models.TextField(blank=True, default="")
    justificativa = models.TextField(blank=True, default="",
                                     help_text="Explicação para variação atípica ou alteração de ano travado.")
    auto_aceito = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
        help_text="Linha de fonte única: valor automático que estava diferente do digitado quando alguém escolheu "
                  "manter o digitado (ignorar a divergência). Se o automático mudar, a divergência volta a aparecer.")
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    atualizado_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["linha", "coluna"], name="valor_unico_por_celula")]

    def __str__(self):
        return f"{self.linha} / {self.coluna}"

    @property
    def vazio(self):
        return self.numero is None and not self.texto


class Regra(models.Model):
    OPERADORES = [("==", "igual a"), ("<=", "menor ou igual a"), (">=", "maior ou igual a"),
                  ("<", "menor que"), (">", "maior que"), ("!=", "diferente de")]
    ERRO, AVISO = "erro", "aviso"
    SEVERIDADES = [(ERRO, "Erro (impede o envio)"), (AVISO, "Aviso")]
    ATUAL, TODAS = "atual", "todas"
    ESCOPOS = [(ATUAL, "Só o ano-base"), (TODAS, "Todas as colunas")]

    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="regras")
    quadro = models.ForeignKey(Quadro, on_delete=models.CASCADE, related_name="regras",
                               help_text="Quadro em que a regra aparece (a coluna de referência vem dele).")
    descricao = models.CharField("descrição", max_length=300)
    esquerda = models.CharField("expressão", max_length=500)
    operador = models.CharField(max_length=2, choices=OPERADORES, default="==")
    direita = models.CharField("comparar com", max_length=500)
    tolerancia = models.DecimalField("tolerância", max_digits=12, decimal_places=4, default=0)
    escopo = models.CharField(max_length=6, choices=ESCOPOS, default=ATUAL)
    severidade = models.CharField(max_length=6, choices=SEVERIDADES, default=ERRO)
    ativa = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["quadro__ordem", "id"]

    def __str__(self):
        return self.descricao


class Pagina(models.Model):
    """Uma página do relatório, igual à do RG publicado no ano anterior: o fundo (formas, cores e fotos, sem texto)
    e, por cima, as caixas de texto (Bloco com `pagina`) e os gráficos e tabelas, cada um no seu lugar."""
    ciclo = models.ForeignKey(Ciclo, on_delete=models.CASCADE, related_name="paginas")
    numero = models.PositiveIntegerField("página do RG")
    largura = models.FloatField(default=935.4)
    altura = models.FloatField(default=566.9)
    fundo = models.CharField("imagem de fundo (em static)", max_length=120, blank=True, default="")
    secao = models.ForeignKey(Secao, on_delete=models.SET_NULL, null=True, blank=True, related_name="paginas",
                              help_text="Seção que começa ou ocupa a página (para o sumário).")
    fixos = models.TextField("textos fixos (rodapé, número da página)", blank=True, default="")

    class Meta:
        ordering = ["numero"]
        unique_together = [("ciclo", "numero")]

    def __str__(self):
        return f"Página {self.numero} de {self.ciclo}"


class Bloco(models.Model):
    """Um pedaço do texto do relatório, dentro de uma seção, na ordem em que aparece no documento.
    Com `pagina`, é uma caixa de texto (ou gráfico/tabela) daquela página, na posição de config["caixa"]."""
    TEXTO, TABELA, GRAFICO, DESTAQUES = "texto", "tabela", "grafico", "destaques"
    TIPOS = [(TEXTO, "Texto"), (TABELA, "Tabela de um quadro"), (GRAFICO, "Gráfico de um quadro"),
             (DESTAQUES, "Números em destaque")]
    secao = models.ForeignKey(Secao, on_delete=models.CASCADE, related_name="blocos")
    ordem = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=10, choices=TIPOS, default=TEXTO)
    titulo = models.CharField("título / legenda", max_length=255, blank=True, default="")
    conteudo = models.TextField("texto", blank=True, default="")
    quadro = models.ForeignKey(Quadro, on_delete=models.SET_NULL, null=True, blank=True, related_name="blocos")
    config = models.JSONField(default=dict, blank=True)
    pagina = models.ForeignKey(Pagina, on_delete=models.SET_NULL, null=True, blank=True, related_name="caixas")
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    atualizado_em = models.DateTimeField(auto_now=True)
    editando_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    editando_desde = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords(excluded_fields=["editando_por", "editando_desde", "atualizado_em"])

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.get_tipo_display()} em {self.secao}"


class Sugestao(models.Model):
    """Alteração de texto proposta pelo Master, que o setor aceita ou recusa."""
    PENDENTE, ACEITA, RECUSADA, RETIRADA = "pendente", "aceita", "recusada", "retirada"
    SITUACOES = [(PENDENTE, "Aguardando o setor"), (ACEITA, "Aceita"), (RECUSADA, "Recusada"),
                 (RETIRADA, "Retirada pelo autor")]
    bloco = models.ForeignKey(Bloco, on_delete=models.CASCADE, related_name="sugestoes")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    original = models.TextField(blank=True, default="", help_text="Texto do bloco quando a sugestão foi feita.")
    proposto = models.TextField(blank=True, default="")
    comentario = models.TextField("comentário", blank=True, default="")
    situacao = models.CharField("situação", max_length=10, choices=SITUACOES, default=PENDENTE)
    respondida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    respondida_em = models.DateTimeField(null=True, blank=True)
    resposta = models.TextField(blank=True, default="")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "sugestão"
        verbose_name_plural = "sugestões"


class Comentario(models.Model):
    secao = models.ForeignKey(Secao, on_delete=models.CASCADE, related_name="comentarios")
    bloco = models.ForeignKey(Bloco, on_delete=models.CASCADE, null=True, blank=True, related_name="comentarios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    texto = models.TextField()
    # comentário preso a um trecho do texto (como no Word): o trecho selecionado e um pouco do que vem antes,
    # para achar o lugar de novo mesmo que o texto em volta mude
    trecho = models.TextField(blank=True, default="")
    antes = models.CharField(max_length=120, blank=True, default="")
    pai = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="respostas",
                            verbose_name="resposta a")
    criado_em = models.DateTimeField(auto_now_add=True)
    resolvido = models.BooleanField(default=False)
    resolvido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+")

    class Meta:
        ordering = ["criado_em", "id"]
        verbose_name = "comentário"


class MovimentoSecao(models.Model):
    """Cada mudança de situação da seção (enviada, devolvida, aprovada...)."""
    secao = models.ForeignKey(Secao, on_delete=models.CASCADE, related_name="movimentos")
    de = models.CharField(max_length=15, choices=Secao.SITUACOES)
    para = models.CharField(max_length=15, choices=Secao.SITUACOES)
    por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    quando = models.DateTimeField(auto_now_add=True)
    comentario = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-quando", "-id"]


class Imagem(models.Model):
    """Imagem inserida no texto do relatório (figura, mapa, foto). Fica em dados/arquivos/imagens."""
    # SET_NULL: o texto copiado para o relatório do ano seguinte continua mostrando a imagem
    ciclo = models.ForeignKey(Ciclo, on_delete=models.SET_NULL, null=True, blank=True, related_name="imagens")
    secao = models.ForeignKey(Secao, on_delete=models.SET_NULL, null=True, blank=True, related_name="imagens")
    arquivo = models.FileField(upload_to="imagens/%Y/")
    nome = models.CharField(max_length=200, blank=True, default="")
    largura = models.PositiveIntegerField(default=0)
    altura = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=20, default="image/png")
    enviada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    enviada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviada_em"]
        verbose_name = "imagem"
        verbose_name_plural = "imagens"

    def __str__(self):
        return self.nome or f"imagem {self.pk}"

    @property
    def url(self):
        return f"/ciclos/{self.ciclo.ano}/imagens/{self.pk}/"


class CampoTexto(models.Model):
    """Número do texto que muda todo ano (“xxxxx” até alguém preencher). No texto fica a marcação
    <span class="sirg-campo" data-c="chave" data-orig="R$ 574,00">; o valor do ano fica aqui."""
    bloco = models.ForeignKey(Bloco, on_delete=models.CASCADE, related_name="campos")
    chave = models.CharField(max_length=24)
    numero = models.DecimalField(max_digits=22, decimal_places=6, null=True, blank=True)
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    atualizado_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "número do texto"
        verbose_name_plural = "números do texto"
        constraints = [models.UniqueConstraint(fields=["bloco", "chave"], name="campo_texto_unico")]

    def __str__(self):
        return f"{self.bloco_id}:{self.chave}={self.numero}"
