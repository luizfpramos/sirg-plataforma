"""
Configurações da Plataforma SiRG — Sistema do Relatório de Gestão.

Valores sensíveis e específicos de cada máquina ficam no arquivo `.env`
(copie `.env.exemplo` para `.env` e ajuste). Sem `.env`, a plataforma roda
em modo de desenvolvimento local com SQLite.
"""
import ipaddress
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # python-dotenv é opcional
    pass


def env(nome, padrao=None):
    return os.environ.get(nome, padrao)


def env_bool(nome, padrao=False):
    v = os.environ.get(nome)
    if v is None:
        return padrao
    return v.strip().lower() in ("1", "true", "sim", "yes", "on")


def env_lista(nome, padrao=""):
    return [x.strip() for x in env(nome, padrao).split(",") if x.strip()]


DADOS_DIR = Path(env("SIRG_DADOS_DIR", BASE_DIR / "dados"))
DADOS_DIR.mkdir(parents=True, exist_ok=True)

# Chave secreta: do .env ou gerada uma única vez e guardada em dados/
SECRET_KEY = env("SIRG_SECRET_KEY")
if not SECRET_KEY:
    arq = DADOS_DIR / "chave_secreta.txt"
    if not arq.exists():
        arq.write_text(secrets.token_urlsafe(64), encoding="utf-8")
    SECRET_KEY = arq.read_text(encoding="utf-8").strip()

DEBUG = env_bool("SIRG_DEBUG", True)
ALLOWED_HOSTS = env_lista("SIRG_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_lista("SIRG_CSRF_TRUSTED_ORIGINS", "")

# Redes autorizadas a acessar a plataforma (ex.: 200.17.0.0/16,10.0.0.0/8). Vazio = qualquer origem.
SIRG_REDES_PERMITIDAS = [ipaddress.ip_network(r, strict=False) for r in env_lista("SIRG_REDES_PERMITIDAS", "")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "simple_history",
    "contas",
    "relatorio",
    "ia",
]

MIDDLEWARE = [
    "contas.middleware.RedesPermitidasMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "contas.middleware.TrocaDeSenhaMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "contas.contexto.global_sirg",
                "relatorio.contexto.menu",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco de dados: SQLite por padrão; PostgreSQL quando SIRG_DB=postgres (ex.: na AWS)
if env("SIRG_DB", "sqlite").lower() == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("SIRG_DB_NOME", "sirg"),
            "USER": env("SIRG_DB_USUARIO", "sirg"),
            "PASSWORD": env("SIRG_DB_SENHA", ""),
            "HOST": env("SIRG_DB_HOST", "localhost"),
            "PORT": env("SIRG_DB_PORTA", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DADOS_DIR / "sirg.sqlite3",
            "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = DADOS_DIR / "arquivos"
MEDIA_URL = "arquivos/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "painel"
LOGOUT_REDIRECT_URL = "entrar"
SESSION_COOKIE_AGE = 60 * 60 * 10   # 10 horas
SESSION_COOKIE_NAME = "sirg_sessao"  # não conflita com o SiMED na mesma máquina
CSRF_COOKIE_NAME = "sirg_csrftoken"
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000
FILE_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024

# Proteção do login
SIRG_MAX_TENTATIVAS = int(env("SIRG_MAX_TENTATIVAS", "5"))
SIRG_BLOQUEIO_MINUTOS = int(env("SIRG_BLOQUEIO_MINUTOS", "15"))

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SIRG_HTTPS", False)
    CSRF_COOKIE_SECURE = env_bool("SIRG_HTTPS", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SESSION_COOKIE_HTTPONLY = True

SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD = True

# Alguns Windows registram tipos errados para .css/.js no registro do sistema
import mimetypes  # noqa: E402
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/javascript", ".js")

SIRG_URL_BASE = env("SIRG_URL_BASE", "http://127.0.0.1:8001")

# --- Assistente SiRG (IA) -------------------------------------------------
# Configuração editável só no servidor: config_ia/ia.toml e config_ia/prompts/*.md
SIRG_IA_CONFIG = env("SIRG_IA_CONFIG", str(BASE_DIR / "config_ia" / "ia.toml"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "arquivo": {"class": "logging.FileHandler", "filename": str(DADOS_DIR / "sirg.log"), "encoding": "utf-8"},
    },
    "root": {"handlers": ["console", "arquivo"], "level": "WARNING"},
    "loggers": {"sirg": {"handlers": ["console", "arquivo"], "level": "INFO", "propagate": False}},
}

# Versão da plataforma (também força o navegador a buscar CSS/JS novos depois de uma atualização)
SIRG_VERSAO = "2.15"
# "hml" na homologacao (faixa laranja no alto e cookies separados da produção, que roda no mesmo computador)
SIRG_AMBIENTE = env("SIRG_AMBIENTE", "prd").strip().lower()
if SIRG_AMBIENTE == "hml":
    SESSION_COOKIE_NAME = "sirg_hml_sessionid"
    CSRF_COOKIE_NAME = "sirg_hml_csrftoken"
# a quem pedir ajuda (tela de entrada e manual): ex. "DGDI · dgdi@instituicao.br · ramal 1234"
SIRG_CONTATO = os.environ.get("SIRG_CONTATO", "").strip()
