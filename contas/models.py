"""
Usuários, setores e perfis de acesso da Plataforma SiRG.

Perfis (podem ser combinados):
  - Administrador da plataforma: cria usuários e setores, vincula usuários a setores,
    configura a instituição e (nas próximas etapas) ciclos e estrutura do relatório.
  - Master: edita qualquer parte do relatório e pode sugerir alterações aos setores.
  - Editor: quem tem ao menos um vínculo ATIVO com um setor ATIVO edita o que é do setor.
  - Leitor: quem não tem nenhum dos anteriores; vê o relatório inteiro, sem editar.

O vínculo usuário-setor nunca é apagado: quando a pessoa sai do setor, o vínculo é
encerrado (data de fim). Assim o histórico mostra em que setor ela estava quando
fez cada alteração.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class Instituicao(models.Model):
    """Dados da instituição usados nas telas e no relatório (registro único)."""
    nome = models.CharField("nome da instituição", max_length=255,
                            default="Universidade Federal de Ciência e Inovação de Minas Gerais")
    sigla = models.CharField(max_length=40, default="UFCIMG")
    cargo_dirigente = models.CharField("cargo da dirigente máxima", max_length=80, default="Diretora-Geral",
                                       help_text="Ex.: Reitora, Diretora-Geral.")
    nome_dirigente = models.CharField("nome da dirigente máxima", max_length=200, blank=True, default="")
    unidade_gestora = models.CharField("unidade responsável pela plataforma", max_length=255,
                                       default="Diretoria de Governança e Desenvolvimento Institucional")
    unidade_gestora_sigla = models.CharField("sigla da unidade responsável", max_length=40, default="DGDI")
    logo = models.FileField("logotipo da instituição", upload_to="identidade/", blank=True,
                            help_text="PNG, JPG ou SVG. Vazio = logotipo padrão.")
    faixa_unidade = models.FileField("assinatura da unidade (faixa)", upload_to="identidade/", blank=True,
                                     help_text="Imagem horizontal da unidade, mostrada no login e no menu. "
                                               "Vazio = assinatura padrão da DGDI.")
    paleta_graficos = models.CharField("cores dos gráficos", max_length=40, default="ufcimg",
                                       help_text="Paleta usada em todos os gráficos (tela, Word e diagramação).")
    atualizado_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "instituição"
        verbose_name_plural = "instituição"

    def __str__(self):
        return self.sigla

    @classmethod
    def atual(cls):
        obj = cls.objects.order_by("pk").first()
        return obj or cls.objects.create()


class Setor(models.Model):
    sigla = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=255)
    descricao = models.TextField("descrição", blank=True, default="")
    ativo = models.BooleanField(default=True, help_text="Setores inativos não recebem novos vínculos e "
                                                        "seus membros deixam de editar.")
    ordem = models.PositiveIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["ordem", "sigla"]
        verbose_name = "setor"
        verbose_name_plural = "setores"

    def __str__(self):
        return self.sigla

    @property
    def rotulo(self):
        return f"{self.sigla} — {self.nome}"

    def membros_ativos(self):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.filter(
            vinculos_setor__setor=self, vinculos_setor__fim__isnull=True).distinct().order_by("first_name", "username")


class Perfil(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_sirg")
    e_admin = models.BooleanField("administrador da plataforma", default=False)
    e_master = models.BooleanField("master", default=False)
    e_diagramacao = models.BooleanField("diagramação", default=False,
                                        help_text="Cuida das cores dos gráficos e baixa o Word e o pacote da diagramação.")
    troca_senha = models.BooleanField("deve trocar a senha no próximo acesso", default=True)
    tentativas_falhas = models.PositiveSmallIntegerField(default=0)
    bloqueado_ate = models.DateTimeField(null=True, blank=True)
    limite_tokens_dia = models.PositiveIntegerField(
        "limite diário de tokens de IA", null=True, blank=True,
        help_text="Vazio = limite padrão da configuração da IA. 0 = sem limite.")
    observacao = models.CharField("observação", max_length=300, blank=True, default="")
    atualizado_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords(excluded_fields=["tentativas_falhas", "atualizado_em"])

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self):
        return f"Perfil de {self.usuario}"

    @property
    def bloqueado(self):
        return bool(self.bloqueado_ate and self.bloqueado_ate > timezone.now())


class VinculoSetor(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vinculos_setor")
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name="vinculos")
    inicio = models.DateTimeField("início", default=timezone.now)
    fim = models.DateTimeField(null=True, blank=True)
    incluido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    encerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+")

    class Meta:
        ordering = ["-inicio"]
        verbose_name = "vínculo com setor"
        verbose_name_plural = "vínculos com setores"
        constraints = [
            models.UniqueConstraint(fields=["usuario", "setor"], condition=models.Q(fim__isnull=True),
                                    name="um_vinculo_ativo_por_setor"),
        ]

    def __str__(self):
        return f"{self.usuario} em {self.setor}"

    @property
    def ativo(self):
        return self.fim is None


class EventoAuditoria(models.Model):
    """Trilha de auditoria: acessos e alterações de usuários, setores e configurações."""
    ACOES = [
        ("login", "Entrou na plataforma"),
        ("login_falha", "Tentativa de login com senha incorreta"),
        ("bloqueio", "Acesso bloqueado por excesso de tentativas"),
        ("desbloqueio", "Acesso desbloqueado"),
        ("logout", "Saiu da plataforma"),
        ("senha_trocada", "Trocou a própria senha"),
        ("senha_redefinida", "Senha redefinida pelo administrador"),
        ("usuario_criado", "Usuário criado"),
        ("usuario_alterado", "Usuário alterado"),
        ("usuario_desativado", "Usuário desativado"),
        ("usuario_reativado", "Usuário reativado"),
        ("setor_vinculado", "Usuário vinculado a setor"),
        ("setor_desvinculado", "Usuário desvinculado de setor"),
        ("setor_criado", "Setor criado"),
        ("setor_alterado", "Setor alterado"),
        ("instituicao_alterada", "Dados da instituição alterados"),
        ("acesso_negado", "Acesso negado"),
    ]
    quando = models.DateTimeField(default=timezone.now, db_index=True)
    ator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="eventos_feitos")
    acao = models.CharField(max_length=30, choices=ACOES, db_index=True)
    usuario_alvo = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="eventos_recebidos")
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    descricao = models.CharField("descrição", max_length=500, blank=True, default="")
    dados = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-quando", "-id"]
        verbose_name = "evento de auditoria"
        verbose_name_plural = "eventos de auditoria"

    def __str__(self):
        from django.utils import timezone
        return f"{timezone.localtime(self.quando):%d/%m/%Y %H:%M} {self.get_acao_display()}"


class Paleta(models.Model):
    """Paleta de cores dos gráficos (criada e editada pela diagramação ou pelo Master).
    A ordem importa: a 1ª cor é a das barras; a 2ª, a da linha sobre as barras; as seguintes, as outras séries."""
    chave = models.SlugField(max_length=40, unique=True)
    nome = models.CharField(max_length=80)
    descricao = models.CharField("descrição", max_length=300, blank=True, default="")
    cores = models.JSONField(default=list)
    sistema = models.BooleanField(default=False, help_text="Paleta que vem com a plataforma (pode ser editada e restaurada).")
    ordem = models.PositiveIntegerField(default=100)
    atualizada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    atualizada_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome
