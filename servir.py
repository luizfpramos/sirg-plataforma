"""Servidor de produção simples (waitress) — usado por servidor.bat / servidor.sh."""
import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.conf import settings  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402
from waitress import serve  # noqa: E402

app = get_wsgi_application()


def com_estaticos(app):
    """Serve /static/ a partir de STATIC_ROOT (sem precisar de nginx/IIS)."""
    import mimetypes
    from pathlib import Path

    # alguns Windows registram tipos errados para .css/.js (o navegador recusa o visual)
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("video/webm", ".webm")
    mimetypes.add_type("font/woff2", ".woff2")
    raiz = Path(settings.STATIC_ROOT)
    prefixo = "/" + settings.STATIC_URL.strip("/") + "/"

    def wsgi(environ, start_response):
        caminho = environ.get("PATH_INFO", "")
        if caminho.startswith(prefixo):
            arq = (raiz / caminho[len(prefixo):]).resolve()
            if raiz.resolve() in arq.parents and arq.is_file():
                tipo = mimetypes.guess_type(str(arq))[0] or "application/octet-stream"
                start_response("200 OK", [("Content-Type", tipo), ("Cache-Control", "max-age=86400")])
                return [arq.read_bytes()]
        return app(environ, start_response)
    return wsgi


def gravar_pid():
    """dados/servidor.pid: o atualizar.bat usa para parar exatamente este processo antes de atualizar."""
    import atexit
    from pathlib import Path
    arq = Path(settings.BASE_DIR) / "dados" / "servidor.pid"
    try:
        arq.parent.mkdir(exist_ok=True)
        arq.write_text(str(os.getpid()))
        atexit.register(lambda: arq.unlink(missing_ok=True))
    except OSError:
        pass


if __name__ == "__main__":
    gravar_pid()
    porta = int(os.environ.get("SIRG_PORTA", "8001"))
    print(f"Plataforma SiRG em http://0.0.0.0:{porta}")
    extra = {}
    if os.environ.get("SIRG_TUNEL", "0").strip().lower() in ("1", "true", "sim", "yes"):
        # Acesso pela internet via túnel (Cloudflare Tunnel): o cloudflared, rodando NESTE computador, entrega
        # as requisições em 127.0.0.1. Só dele aceitamos os cabeçalhos com o IP real de quem acessa e o
        # "https" (de qualquer outro endereço, esses cabeçalhos são descartados).
        extra = {"trusted_proxy": "127.0.0.1", "trusted_proxy_count": 1,
                 "trusted_proxy_headers": "x-forwarded-for x-forwarded-proto", "clear_untrusted_proxy_headers": True}
        print("Túnel ativo: aceitando o endereço público via cloudflared em 127.0.0.1.")
    serve(com_estaticos(app), host="0.0.0.0", port=porta, threads=8, **extra)
