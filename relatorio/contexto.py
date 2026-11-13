from .models import Ciclo


def menu(request):
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    try:
        from .views import ciclo_atual
        return {"CICLO_MENU": ciclo_atual(), "N_CICLOS": Ciclo.objects.count()}
    except Exception:
        return {}
