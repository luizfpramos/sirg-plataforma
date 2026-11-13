"""Sinais: perfil criado junto com cada usuário e registro de saída na auditoria."""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil


@receiver(post_save, sender=get_user_model())
def criar_perfil(sender, instance, created, **kwargs):
    if created and not Perfil.objects.filter(usuario=instance).exists():
        # superusuário criado pelo terminal já começa como administrador e master
        Perfil.objects.create(usuario=instance, e_admin=instance.is_superuser, e_master=instance.is_superuser,
                              troca_senha=not instance.is_superuser)


@receiver(user_logged_out)
def registrar_saida(sender, request, user, **kwargs):
    if user is not None:
        from .servicos import registrar
        registrar("logout", user, user, request=request)
