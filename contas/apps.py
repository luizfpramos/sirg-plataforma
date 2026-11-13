from django.apps import AppConfig


class ContasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contas"
    verbose_name = "Usuários e setores"

    def ready(self):
        from . import sinais  # noqa: F401
