"""Middlewares de segurança da Plataforma SiRG."""
import ipaddress

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse


class RedesPermitidasMiddleware:
    """Recusa acessos de fora das redes listadas em SIRG_REDES_PERMITIDAS (vazio = sem restrição)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        redes = settings.SIRG_REDES_PERMITIDAS
        if redes:
            try:
                ip = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
            except ValueError:
                ip = None
            if ip is None or not (ip.is_loopback or any(ip in r for r in redes)):
                return HttpResponseForbidden(
                    "<h1>Acesso não permitido</h1><p>A Plataforma SiRG só pode ser acessada pela rede interna "
                    "da instituição.</p>", content_type="text/html; charset=utf-8")
        return self.get_response(request)


class TrocaDeSenhaMiddleware:
    """Quem está com senha provisória só consegue trocar a senha ou sair."""

    LIVRES = ("senha", "sair", "identidade")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        if request.path.startswith("/" + settings.STATIC_URL.strip("/") + "/"):
            return None
        rm = request.resolver_match
        if rm and rm.url_name in self.LIVRES:
            return None
        from .permissoes import perfil
        p = perfil(user)
        if p and p.troca_senha:
            return redirect(reverse("senha"))
        return None
