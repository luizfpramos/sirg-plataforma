"""Django Admin: só para emergências (superusuário). O dia a dia é pelas telas da plataforma."""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import EventoAuditoria, Instituicao, Perfil, Setor, VinculoSetor


@admin.register(Setor)
class SetorAdmin(SimpleHistoryAdmin):
    list_display = ("sigla", "nome", "ativo", "ordem")
    search_fields = ("sigla", "nome")


@admin.register(Perfil)
class PerfilAdmin(SimpleHistoryAdmin):
    list_display = ("usuario", "e_admin", "e_master", "troca_senha", "bloqueado_ate")


@admin.register(VinculoSetor)
class VinculoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "setor", "inicio", "fim")
    list_filter = ("setor",)


@admin.register(EventoAuditoria)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("quando", "acao", "ator", "usuario_alvo", "setor", "ip")
    list_filter = ("acao",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Instituicao, SimpleHistoryAdmin)
admin.site.site_header = "SiRG — administração técnica"
