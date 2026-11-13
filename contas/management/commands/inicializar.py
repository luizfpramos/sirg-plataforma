"""Prepara o banco: setores de 2025, registro da instituição e perfis dos usuários existentes."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from contas.models import Instituicao, Perfil
from contas.servicos import criar_setores_iniciais


class Command(BaseCommand):
    help = "Cria os setores iniciais (estrutura de 2025), o registro da instituição e os perfis que faltarem."

    def handle(self, *args, **opts):
        n = criar_setores_iniciais()
        Instituicao.atual()
        criados = 0
        for u in get_user_model().objects.all():
            _, c = Perfil.objects.get_or_create(usuario=u, defaults={
                "e_admin": u.is_superuser, "e_master": u.is_superuser, "troca_senha": False})
            criados += int(c)
        self.stdout.write(self.style.SUCCESS(
            f"Setores criados: {n}. Perfis criados: {criados}. Instituição: ok."))
