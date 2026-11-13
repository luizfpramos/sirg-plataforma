"""2.12: documento único (xxxxx no texto, dados de tabelas e gráficos no lugar), paletas editáveis, homologação."""
import json

from django.core.management import call_command
from django.test import TestCase, override_settings

from contas import servicos as CS
from contas.models import Paleta, Perfil, Setor
from relatorio import campos as CT
from relatorio import fluxo as F
from relatorio import paletas
from relatorio.models import Bloco, CampoTexto, Ciclo, Quadro, Secao

SENHA = "Senha-forte-2026"


class CamposUnidadeTests(TestCase):
    def test_o_que_vira_campo(self):
        h, novos = CT.camposificar(
            "<p>Em 2025 foram 5 competições, Lei nº 11.892/2008, OD-2.1, 27 de março, 1º lugar, p. 12, 12h30, "
            "código 594, R$ 574,00, 45% e 1.844 alunos (seção 3.2.1).</p><h3>Meta 4</h3>"
            "<table><tr><td>25%</td></tr></table>")
        texto, vazios = CT.renderizar(h, {}, marcar=False)
        self.assertEqual(vazios, 4)
        self.assertIn("foram xxxxx competições", texto)
        self.assertIn("R$ xxxxx, xxxxx% e xxxxx alunos", texto)
        for fica in ("2025", "11.892/2008", "OD-2.1", "27 de março", "1º", "p. 12", "12h30", "código 594", "3.2.1",
                     "Meta 4", "25%"):
            self.assertIn(fica, texto)

    def test_formato_igual_ao_original(self):
        self.assertEqual(CT.exibir("R$ 570,87 milhões", 1.5), "R$ 1,50 milhão")
        self.assertEqual(CT.exibir("R$ 574,00", 600), "R$ 600,00")
        self.assertEqual(CT.exibir("90,48%", 91.2), "91,20%")
        self.assertEqual(CT.exibir("1.844", 1900), "1.900")
        self.assertEqual(CT.exibir("45%", None), "xxxxx%")
        self.assertEqual(str(CT.ler("R$ 574,00", "R$ 1.234,5")), "1234.5")


class Base212(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana DIRGRAD", setores=[g("DIRGRAD")], senha=SENHA)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo DPPG", setores=[g("DPPG")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        cls.diag, _ = CS.criar_usuario(login="diag", nome="Brígida", senha=SENHA, e_diagramacao=True)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)
        cls.sec = Secao.objects.get(ciclo=cls.c, chave="ensino_graduacao")

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")

    def bloco_com_campo(self):
        return Bloco.objects.filter(secao=self.sec, tipo=Bloco.TEXTO, conteudo__contains="sirg-campo").first()


class DocumentoUnicoTests(Base212):
    def test_preparacao_cria_campos_uma_vez(self):
        b = self.bloco_com_campo()
        self.assertTrue(b.config.get("campos212"))
        n = len(CT.chaves(b.conteudo))
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        b.refresh_from_db()
        self.assertEqual(len(CT.chaves(b.conteudo)), n)        # roda uma vez só por trecho

    def test_setor_preenche_o_xxxxx_e_vai_para_o_word(self):
        import io

        from docx import Document
        b = self.bloco_com_campo()
        chave = CT.chaves(b.conteudo)[0]
        self.client.force_login(self.dppg)                     # outro setor: não
        r = self.post(f"/ciclos/{self.c.ano}/campos/", {"bloco": b.pk, "chave": chave, "valor": "9"})
        self.assertEqual(r.status_code, 400)
        self.client.force_login(self.grad)
        r = self.post(f"/ciclos/{self.c.ano}/campos/", {"bloco": b.pk, "chave": chave, "valor": "abc"})
        self.assertFalse(r.json()["ok"])
        r = self.post(f"/ciclos/{self.c.ano}/campos/", {"bloco": b.pk, "chave": chave, "valor": "1.234"}).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(CampoTexto.objects.get(bloco=b, chave=chave).numero, 1234)
        self.assertEqual(CampoTexto.objects.get(bloco=b, chave=chave).history.first().history_user, self.grad)
        self.client.force_login(self.master)
        doc = Document(io.BytesIO(self.client.get(f"/ciclos/{self.c.ano}/exportar/?formato=docx").content))
        import re as _re
        texto = "".join(_re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc.element.xml))     # inclui as caixas de texto
        self.assertIn("1.234", texto)
        self.assertIn("xxxxx", texto)                           # os que faltam saem como xxxxx

    def test_tela_unica_com_dados_no_lugar(self):
        self.client.force_login(self.grad)
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/?secao=ensino_graduacao").content.decode()
        self.assertIn("sirg-campo vazio pode", h)
        self.assertIn("js-dados", h)
        self.assertIn("doc-gaveta", h)
        self.assertIn("js/preencher.js", h)
        self.assertNotIn('class="sidebar"', h)
        q = Quadro.objects.get(ciclo=self.c, chave="grad_pet")
        j = self.client.get(f"/ciclos/{self.c.ano}/quadros/{q.pk}/gaveta/").json()
        self.assertIn("cel-input", j["html"])
        col = q.colunas.get(ano=self.c.ano)
        li = q.linhas.get(chave="alunos")
        self.assertTrue(self.post(f"/ciclos/{self.c.ano}/celula/", {"linha": li.pk, "coluna": col.pk, "valor": "152"}).json()["ok"])
        r = self.post(f"/ciclos/{self.c.ano}/escrever/atualizar/", {"quadros": ["grad_pet"]}).json()
        self.assertTrue(any(v["tipo"] == "grafico" and "152" in v["html"] for v in r["blocos"].values()))
        f = self.post(f"/ciclos/{self.c.ano}/escrever/atualizar/", {"secoes": [str(self.sec.pk)]}).json()
        self.assertIn(str(self.sec.pk), f["faltam"])

    def test_setor_so_altera_com_controle_de_alteracoes(self):
        b = Bloco.objects.filter(secao=self.sec, tipo=Bloco.TEXTO).exclude(conteudo="").first()
        with self.assertRaises(F.Recusado):
            F.salvar_texto(self.grad, b, "<p>Texto trocado direto.</p>")
        F.destravar(self.grad, Bloco.objects.get(pk=b.pk))
        ok = F.salvar_texto(self.grad, Bloco.objects.get(pk=b.pk),
                            b.conteudo.replace("</p>", ' <ins data-s="x1">mais</ins></p>', 1))
        self.assertIn("mais</ins>", ok.conteudo)
        with self.assertRaises(F.Recusado):
            F.criar_bloco(self.grad, self.sec, Bloco.TEXTO)

    def test_no_que_falta_aparecem_os_xxxxx(self):
        self.client.force_login(self.grad)
        r = self.client.get(f"/ciclos/{self.c.ano}/pendencias/")
        self.assertTrue(any("como xxxxx" in t["mensagem"] for t in r.context["textos"]))


class PaletasTests(Base212):
    def test_diagramacao_cria_importa_usa_e_baixa(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.grad)
        self.assertEqual(self.client.get("/graficos/cores/").status_code, 403)
        self.client.force_login(self.diag)
        self.assertEqual(self.client.get("/graficos/cores/").status_code, 200)
        ase = paletas.gerar_ase("Gráficos 2026", ["#123456", "#ABCDEF", "#FF8800"])
        r = self.client.post("/graficos/cores/nova/", {"nome": "Gráficos 2026", "cor": ["#000000", "#FFFFFF"],
                                                       "arquivo": SimpleUploadedFile("a.ase", ase)})
        self.assertContains(r, "#ABCDEF")                       # importou: volta para conferir a ordem
        r = self.client.post("/graficos/cores/nova/", {"nome": "Gráficos 2026", "acao": "salvar",
                                                       "cor": ["#123456", "#ABCDEF", "#FF8800"]})
        p = Paleta.objects.get(nome="Gráficos 2026")
        self.assertEqual(p.cores, ["#123456", "#ABCDEF", "#FF8800"])
        self.client.post("/graficos/cores/", {"acao": "usar", "paleta": p.chave})
        self.assertEqual(paletas.cores()[:2], ["#123456", "#ABCDEF"])
        self.assertEqual(paletas.ler_ase(self.client.get(f"/graficos/cores/{p.chave}/ase/").content),
                         ["#123456", "#ABCDEF", "#FF8800"])
        # em uso não se exclui; as de fábrica voltam ao original
        self.client.post("/graficos/cores/", {"acao": "excluir", "paleta": p.chave})
        self.assertTrue(Paleta.objects.filter(pk=p.pk).exists())
        sobria = Paleta.objects.get(chave="sobria")
        sobria.cores = ["#000000", "#111111"]
        sobria.save()
        self.client.post("/graficos/cores/", {"acao": "restaurar", "paleta": "sobria"})
        self.assertEqual(Paleta.objects.get(chave="sobria").cores, paletas.PALETAS["sobria"]["cores"])

    def test_ler_formatos(self):
        self.assertEqual(paletas.ler_arquivo("x.gpl", b"GIMP Palette\nName: a\n#\n255 0 0 Red\n0 128 255 Blue"),
                         ["#FF0000", "#0080FF"])
        self.assertEqual(paletas.ler_arquivo("x.json", b'{"cores": ["#285c98", "2a9c8e"]}'), ["#285C98", "#2A9C8E"])


class HomologacaoTests(Base212):
    @override_settings(SIRG_AMBIENTE="hml")
    def test_faixa_de_homologacao(self):
        self.client.force_login(self.grad)
        h = self.client.get("/").content.decode()
        self.assertIn("HOMOLOGAÇÃO", h)
        self.assertIn("barra-topo hml", h)

    def test_scripts_de_implantacao_no_pacote(self):
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for nome in ("instalar_hml.bat", "subir_prd.bat", "implantacao/implantar.ps1"):
            self.assertTrue((base / nome).exists(), nome)
        ps = (base / "implantacao/implantar.ps1").read_text(encoding="utf-8")
        self.assertTrue(ps.isascii())                           # PowerShell 5 lê scripts sem BOM como ANSI
        for chave in ("SIRG_AMBIENTE", "SIRG_BACKUP_DIR", "SIRG_DADOS_DIR", "HML_PORTA = 8003", "SiRG - HML", "manage.py\", \"backup"):
            self.assertIn(chave, ps)
        bat = (base / "subir_prd.bat").read_bytes()
        self.assertIn(b"\r\n", bat)
        self.assertIn(b"#INICIO_PS", bat)
