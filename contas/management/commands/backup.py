"""Cópia de segurança do banco SQLite (segura mesmo com a plataforma em uso)."""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copia o banco de dados e os arquivos enviados para a pasta de backup (SIRG_BACKUP_DIR)."

    def add_arguments(self, parser):
        parser.add_argument("--destino", help="Pasta de destino (padrão: SIRG_BACKUP_DIR ou dados/backups)")
        parser.add_argument("--manter", type=int, default=None, help="Quantos backups manter (padrão: 30)")

    def handle(self, *args, **o):
        import os
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("Este comando faz backup só do SQLite. No PostgreSQL use pg_dump.")
        destino = Path(o.get("destino") or os.environ.get("SIRG_BACKUP_DIR") or settings.DADOS_DIR / "backups")
        manter = o.get("manter") or int(os.environ.get("SIRG_BACKUP_MANTER", "30"))
        destino.mkdir(parents=True, exist_ok=True)
        carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        pasta = destino / f"sirg_{carimbo}"
        n = 2
        while pasta.exists():
            pasta = destino / f"sirg_{carimbo}_{n}"
            n += 1
        pasta.mkdir()
        origem = sqlite3.connect(str(db["NAME"]))
        copia = sqlite3.connect(str(pasta / "sirg.sqlite3"))
        with copia:
            origem.backup(copia)          # cópia consistente, mesmo com usuários conectados
        copia.close()
        origem.close()
        arquivos = Path(settings.MEDIA_ROOT)
        if arquivos.exists():
            shutil.copytree(arquivos, pasta / "arquivos")
        chave = settings.DADOS_DIR / "chave_secreta.txt"
        if chave.exists():
            shutil.copy2(chave, pasta / "chave_secreta.txt")
        antigos = sorted(p for p in destino.glob("sirg_*") if p.is_dir())
        for p in antigos[:-manter] if manter > 0 else []:
            shutil.rmtree(p, ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(f"Backup gravado em {pasta}"))
