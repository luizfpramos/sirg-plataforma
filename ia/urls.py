from django.urls import path

from . import views as V

urlpatterns = [
    path("ciclos/<int:ano>/assistente/", V.texto, name="ia_texto"),
    path("assistente/aplicado/<int:pk>/", V.aplicado, name="ia_aplicado"),
    path("assistente/meu-uso/", V.meu_uso, name="ia_meu_uso"),
    path("assistente/uso/", V.painel_uso, name="ia_uso"),
]
