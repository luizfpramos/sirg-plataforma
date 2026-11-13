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


class EnviarParaProducaoTests(TestCase):
    """2.15: botão "Enviar para a produção" na tela Sobre da homologação."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.commit = "94aa7d4c0ffee0000000000000000000000000aa"
        (self.tmp / "implantacao.json").write_text(json.dumps([
            {"quando": "13/11/2026 10:00", "alvo": "hml", "versao": "2.15", "commit": self.commit, "ok": True,
             "erro": ""}]), encoding="utf-8-sig")
        (self.tmp / "producao.json").write_text(json.dumps(
            {"versao": "2.14.1", "commit": "5e578ba", "quando": "13/11/2026 10:05"}), encoding="utf-8-sig")
        self.master, _ = CS.criar_usuario(login="m", nome="Mara", e_master=True, senha="Senha-forte-2026")
        self.leitor, _ = CS.criar_usuario(login="l", nome="Leo", senha="Senha-forte-2026")
        Perfil.objects.update(troca_senha=False)

    def cfg(self, **kw):
        base = {"DADOS_DIR": self.tmp, "SIRG_AMBIENTE": "hml", "SIRG_VERSAO": "2.15"}
        base.update(kw)
        return override_settings(**base)

    def test_master_envia_com_confirmacao(self):
        with self.cfg():
            self.client.force_login(self.master)
            h = self.client.get("/sobre/").content.decode()
            self.assertIn("Enviar a versão 2.15 para a produção", h)
            self.assertIn("versão 2.14.1", h)
            r = self.client.post("/sobre/enviar-producao/", {"confirmacao": "2.1"})
            self.assertFalse((self.tmp / "pedido_prd.json").exists())          # confirmação errada
            r = self.client.post("/sobre/enviar-producao/", {"confirmacao": "2.15"}, follow=True)
            pedido = json.loads((self.tmp / "pedido_prd.json").read_text(encoding="utf-8"))
            self.assertEqual(pedido["commit"], self.commit)
            self.assertEqual(pedido["versao"], "2.15")
            self.assertEqual(pedido["quem"], "Mara")
            h = r.content.decode()
            self.assertIn("Pedido enviado", h)
            self.assertNotIn("Enviar a versão 2.15 para a produção", h)        # um pedido por vez

    def test_leitor_nao_envia(self):
        with self.cfg():
            self.client.force_login(self.leitor)
            self.assertNotIn("/sobre/enviar-producao/", self.client.get("/sobre/").content.decode())
            self.assertEqual(self.client.post("/sobre/enviar-producao/", {"confirmacao": "2.15"}).status_code, 403)
            self.assertFalse((self.tmp / "pedido_prd.json").exists())

    def test_so_na_homologacao(self):
        with self.cfg(SIRG_AMBIENTE="prd"):
            self.client.force_login(self.master)
            self.assertNotIn("/sobre/enviar-producao/", self.client.get("/sobre/").content.decode())
            self.assertEqual(self.client.post("/sobre/enviar-producao/", {"confirmacao": "2.15"}).status_code, 404)

    def test_mesma_versao_da_producao_e_recusada(self):
        with self.cfg(SIRG_VERSAO="2.14.1"):
            (self.tmp / "implantacao.json").write_text(json.dumps([
                {"alvo": "hml", "versao": "2.14.1", "commit": self.commit, "ok": True}]), encoding="utf-8")
            self.client.force_login(self.master)
            self.assertIn("suba a SIRG_VERSAO", self.client.get("/sobre/").content.decode())
            self.client.post("/sobre/enviar-producao/", {"confirmacao": "2.14.1"})
            self.assertFalse((self.tmp / "pedido_prd.json").exists())

    def test_producao_ja_com_o_codigo(self):
        with self.cfg():
            (self.tmp / "producao.json").write_text(json.dumps({"versao": "2.15", "commit": self.commit}),
                                                    encoding="utf-8")
            self.client.force_login(self.master)
            self.assertIn("já está com este código", self.client.get("/sobre/").content.decode())

    def test_implantador_atende_o_pedido(self):
        from django.conf import settings
        imp = (Path(settings.BASE_DIR) / "implantacao/git/implantador.ps1").read_text()
        self.assertIn("pedido_prd.json", imp)
        self.assertIn("producao.json", imp)
        self.assertIn('$commit -ne $estado["hml"]', imp)       # só o código que está na homologação
