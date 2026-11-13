"""Registro de cada uso do Assistente SiRG (para controle de consumo por usuário)."""
from django.conf import settings
from django.db import models


class UsoIA(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uso_ia")
    acao = models.CharField("ação", max_length=20)
    provedor = models.CharField(max_length=40)
    modelo = models.CharField(max_length=100)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_saida = models.PositiveIntegerField(default=0)
    duracao_ms = models.PositiveIntegerField(default=0)
    sucesso = models.BooleanField(default=True)
    erro = models.CharField(max_length=300, blank=True, default="")
    bloco = models.ForeignKey("relatorio.Bloco", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    aplicado = models.BooleanField("sugestão aplicada pelo usuário", default=False)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "uso do assistente"
        verbose_name_plural = "uso do assistente"

    @property
    def tokens_total(self):
        return self.tokens_entrada + self.tokens_saida
