"""2.14.1: registro das instalações automáticas na tela Sobre."""
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from contas import servicos as CS
from contas.models import Perfil


class ImplantacaoNaTelaSobreTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "implantacao.json").write_text(json.dumps([
            {"quando": "13/11/2026 08:00", "alvo": "hml", "versao": "2.14.1", "commit": "abcdef1234567", "ok": True, "erro": ""},
            {"quando": "13/11/2026 09:00", "alvo": "hml", "versao": "2.15", "commit": "1234567abcdef", "ok": False,
             "erro": "ERRO: falha ao migrar"}]), encoding="utf-8-sig")
        self.master, _ = CS.criar_usuario(login="m", nome="Mara", e_master=True, senha="Senha-forte-2026")
        self.leitor, _ = CS.criar_usuario(login="l", nome="Leo", senha="Senha-forte-2026")
        Perfil.objects.update(troca_senha=False)

    def test_master_ve_e_leitor_nao(self):
        with override_settings(DADOS_DIR=self.tmp):
            self.client.force_login(self.master)
            h = self.client.get("/sobre/").content.decode()
            self.assertIn("Últimas instalações automáticas", h)
            self.assertIn("falha ao migrar", h)
            self.assertIn("1234567a", h)                 # a mais recente primeiro
            self.client.force_login(self.leitor)
            self.assertNotIn("Últimas instalações", self.client.get("/sobre/").content.decode())

    def test_sem_arquivo_nao_quebra(self):
        with override_settings(DADOS_DIR=self.tmp / "nada"):
            self.client.force_login(self.master)
            self.assertEqual(self.client.get("/sobre/").status_code, 200)


class ScriptsDoImplantadorTests(TestCase):
    def test_scripts_ascii_crlf(self):
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for nome in ("implantacao/git/implantador.ps1", "implantacao/git/instalar_implantador.ps1",
                     "instalar_implantador.bat", "implantacao/implantar.ps1"):
            b = (base / nome).read_bytes()
            self.assertNotIn(b"\n", b.replace(b"\r\n", b""), nome)
            if nome.endswith(".ps1"):
                self.assertTrue(b.isascii(), nome)
        ps = (base / "implantacao/implantar.ps1").read_text()
        self.assertIn("[switch]$Automatico", ps)
        imp = (base / "implantacao/git/implantador.ps1").read_text()
        self.assertIn("merge-base --is-ancestor", imp)          # PRD só com código que passou pela HML
        self.assertTrue((base / ".github/workflows/testes-e-implantacao.yml").exists())
        gi = (base / ".gitignore").read_text()
        for x in (".env", "dados/", "*.sqlite3"):
            self.assertIn(x, gi)
