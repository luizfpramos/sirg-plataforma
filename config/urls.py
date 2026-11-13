from django.contrib import admin
from django.urls import include, path

handler403 = "contas.views.erro_403"
handler404 = "contas.views.erro_404"

urlpatterns = [
    path("django-admin/", admin.site.urls),   # só superusuário (emergências)
    path("", include("contas.urls")),
    path("", include("relatorio.urls")),
]
