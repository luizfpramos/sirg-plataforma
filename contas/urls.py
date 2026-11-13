from django.contrib.auth import views as auth_views
from django.urls import path

from . import views as V

urlpatterns = [
    path("", V.painel, name="painel"),
    path("entrar/", V.Entrar.as_view(), name="entrar"),
    path("sair/", auth_views.LogoutView.as_view(), name="sair"),
    path("senha/", V.TrocarSenha.as_view(), name="senha"),
    path("identidade/<str:qual>/", V.identidade, name="identidade"),
    path("minha-conta/", V.conta, name="conta"),
    path("usuarios/", V.usuarios, name="usuarios"),
    path("usuarios/novo/", V.usuario_novo, name="usuario_novo"),
    path("usuarios/<int:pk>/", V.usuario, name="usuario"),
    path("usuarios/<int:pk>/<str:acao>/", V.usuario_acao, name="usuario_acao"),
    path("setores/", V.setores, name="setores"),
    path("setores/novo/", V.setor_novo, name="setor_novo"),
    path("setores/<int:pk>/", V.setor, name="setor"),
    path("instituicao/", V.instituicao, name="instituicao"),
    path("auditoria/", V.auditoria, name="auditoria"),
    path("ajuda/", V.ajuda, name="ajuda"),
    path("sobre/", V.sobre, name="sobre"),
    path("graficos/cores/", V.cores_graficos, name="cores_graficos"),
    path("graficos/cores/nova/", V.paleta_editar, name="paleta_nova"),
    path("graficos/cores/<slug:chave>/editar/", V.paleta_editar, name="paleta_editar"),
    path("graficos/cores/<slug:chave>/ase/", V.paleta_ase, name="paleta_ase"),
]
