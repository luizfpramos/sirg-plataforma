"""2.24: ajustes no fundo da página (apagar uma área, manter o texto do PDF no fundo) e o texto do PDF no editor
com as mesmas regras do Relatório."""
import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from contas import servicos as CS
from contas.models import Perfil
from relatorio import editor_blocos as E
from relatorio import fundo as FU
from relatorio import importador as I
from relatorio import textos_pdf as TP
from relatorio.construtor import secao
from relatorio.models import Ciclo, Pagina
from relatorio.tests.test_reimportacao import pdf_com

SENHA = "Senha-forte-2026"


class NormalizarTests(SimpleTestCase):
    def test_arredonda_e_corta_na_borda(self):
        a = FU.normalizar([{"tipo": "apagar", "x": -5, "y": 10.04, "w": 30, "h": 20}], 100, 50)
        self.assertEqual(a, [{"tipo": "apagar", "x": 0.0, "y": 10.0, "w": 25.0, "h": 20.0}])

    def test_recusa_tipo_e_area_invalidos(self):
        for ruim in ([{"tipo": "pintar", "x": 1, "y": 1, "w": 9, "h": 9}],
                     [{"tipo": "apagar", "x": 200, "y": 1, "w": 9, "h": 9}],
                     [{"tipo": "manter", "x": "a", "y": 1, "w": 9, "h": 9}], "texto"):
            with self.assertRaises(FU.Invalido):
                FU.normalizar(ruim, 100, 50)

    def test_vazio(self):
        self.assertEqual(FU.normalizar(None, 100, 50), [])

    def test_dentro_de_mantida(self):
        aj = [{"tipo": "manter", "x": 0, "y": 0, "w": 50, "h": 50}, {"tipo": "apagar", "x": 60, "y": 0, "w": 30, "h": 30}]
        self.assertTrue(FU.dentro_de_mantida({"x": 10, "y": 10, "w": 10, "h": 10}, aj))
        self.assertFalse(FU.dentro_de_mantida({"x": 65, "y": 5, "w": 10, "h": 10}, aj))   # apagar não esconde


class AplicarTests(SimpleTestCase):
    """Traço de grifo sobre o papel branco e sobre um quadro verde: apagar cobre com a cor de cada lugar."""

    def test_apaga_o_traco_com_a_cor_em_volta(self):
        im = Image.new("RGB", (200, 100), (255, 255, 255))
        im.paste((220, 235, 220), (100, 0, 200, 100))              # quadro verde-claro à direita
        im.paste((20, 20, 20), (10, 50, 190, 52))                   # traço que atravessa os dois
        pg = Pagina(largura=200, altura=100, fundo="x.jpg", ajustes_fundo=[
            {"tipo": "apagar", "x": 8, "y": 47, "w": 80, "h": 8},
            {"tipo": "apagar", "x": 110, "y": 47, "w": 82, "h": 8}])
        out = FU.aplicar(pg, im)
        self.assertEqual(out.getpixel((50, 51)), (255, 255, 255))
        self.assertEqual(out.getpixel((150, 51)), (220, 235, 220))
        self.assertEqual(im.getpixel((50, 51)), (20, 20, 20))           # a imagem de entrada não muda


class CssDoEditorTests(SimpleTestCase):
    """O texto do PDF no editor tem de seguir as regras do texto do Relatório: sem a margem do <p> do Bootstrap
    (que afastava as linhas de notas, rótulos e títulos) e sem quebrar as linhas que o PDF não quebrou."""

    def test_regras(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sirg.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.ed-pdf-txt p \{ margin: 0; \}")
        self.assertRegex(css, r"\.ed-pdf-caixa\.q \.ed-pdf-txt, \.ed-bloco\.q \.ed-conteudo \{ white-space: nowrap; \}")
        js = (Path(settings.BASE_DIR) / "static" / "js" / "editor_blocos.js").read_text(encoding="utf-8")
        self.assertIn('(c.quebra ? " q" : "")', js)
        self.assertIn('(b.quebra ? " q" : "")', js)


@override_settings(SIRG_IMPORTACAO_SINCRONA=True)
class FundoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media, cls.dados = tempfile.mkdtemp(), tempfile.mkdtemp()
        cls._cfg = override_settings(MEDIA_ROOT=cls.media, DADOS_DIR=Path(cls.dados))
        cls._cfg.enable()
        cls.pdf = pdf_com(paginas=3, extra=True)

    @classmethod
    def tearDownClass(cls):
        cls._cfg.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        shutil.rmtree(cls.dados, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.PREPARACAO)
        cap = secao(cls.c, "cap1", "1. Visão geral", ordem=1)
        cls.apres = secao(cls.c, "apresentacao", "Apresentação", pai=cap, ordem=1, setores=["DIRGRAD"])
        cls.grad = secao(cls.c, "ensino_graduacao", "Ensino de graduação", pai=cap, ordem=2, setores=["DIRGRAD"])
        cls.pesq = secao(cls.c, "pesquisa", "Pesquisa e inovação", pai=cap, ordem=3, setores=["DIRGRAD"])

    def setUp(self):
        self.client.force_login(self.admin)
        arq = SimpleUploadedFile("RG.pdf", self.pdf, content_type="application/pdf")
        self.imp = I.receber(self.c, arq, self.admin)
        I.iniciar(self.imp)
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), {
            "conferido": "1", "exibicao_vazio": "orientacao", "modo_blocos": "manual",
            f"inicio_{self.apres.pk}": "1", f"inicio_{self.grad.pk}": "2", f"inicio_{self.pesq.pk}": "3"})
        self.pg = Pagina.objects.get(ciclo=self.c, numero=2)

    def acao(self, nome, dados):
        return self.client.post(reverse("editor_acao", args=[2030, 2, nome]), json.dumps(dados),
                                content_type="application/json")

    def caixa_do_pdf(self, trecho):
        return next(c for c in TP.caixas_da_pagina(self.pg) if trecho in c["texto"])

    def test_pagina_importada_tem_o_pdf_de_origem(self):
        arq, n = FU.pdf_original(self.pg)
        self.assertTrue(arq.name == "original.pdf" and n == 2)

    def test_apagar_cobre_com_a_cor_em_volta_sem_mudar_o_original(self):
        original = self.pg.fundo_caminho
        antes = Image.open(original).convert("RGB").copy()
        r = self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(len(j["ajustes"]), 1)
        self.pg.refresh_from_db()
        self.assertIn("/arquivos/fundos/", j["fundo_url"])
        self.assertEqual(j["fundo_url"], self.pg.fundo_url)
        novo = Image.open(self.pg.fundo_caminho).convert("RGB")
        self.assertEqual(novo.size, antes.size)
        self.assertEqual(Image.open(original).convert("RGB").tobytes(), antes.tobytes())  # o original não muda
        # a imagem ajustada é servida a quem está logado
        r = self.client.get(j["fundo_url"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")

    def test_manter_poe_o_texto_no_fundo_e_tira_da_lista_do_pdf(self):
        titulo = self.caixa_do_pdf("graduação")
        sem = Image.open(self.pg.fundo_caminho).convert("RGB")
        area = {"tipo": "manter", "x": titulo["x"] - 2, "y": titulo["y"] - 2, "w": titulo["w"] + 4,
                "h": titulo["h"] + 4}
        r = self.acao("fundo", {"ajustes": [area]})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(any(c["i"] == titulo["i"] for c in r.json()["pdf"]))
        self.pg.refresh_from_db()
        self.assertFalse(any(c["i"] == titulo["i"] for c in TP.caixas_da_pagina(self.pg)))
        com = Image.open(self.pg.fundo_caminho).convert("RGB")
        k = com.size[0] / self.pg.largura
        recorte = tuple(round(v * k) for v in (area["x"], area["y"], area["x"] + area["w"], area["y"] + area["h"]))
        escuros = lambda im: sum(1 for p in im.crop(recorte).getdata() if sum(p) < 300)
        self.assertGreater(escuros(com), escuros(sem) + 20)            # as letras voltaram, como imagem

    def test_desfazer_volta_ao_fundo_original(self):
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        r = self.acao("fundo", {"ajustes": []})
        self.pg.refresh_from_db()
        self.assertEqual(self.pg.ajustes_fundo, [])
        self.assertEqual(r.json()["fundo_url"], reverse("importacao_arquivo", args=[self.imp.pk, "p002.jpg"]))

    def test_versao_antiga_da_imagem_e_apagada(self):
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 80, "h": 30}]})
        self.assertEqual(len(list(FU.pasta().glob(f"{self.pg.pk}-*.jpg"))), 1)

    def test_endereco_antigo_redireciona(self):
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        r = self.client.get(reverse("fundo_ajustado", args=[self.pg.pk, "0" * 12]))
        self.pg.refresh_from_db()
        self.assertRedirects(r, self.pg.fundo_url, fetch_redirect_response=False)

    def test_recusa_ajuste_invalido(self):
        r = self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 5000, "y": 40, "w": 60, "h": 30}]})
        self.assertEqual(r.status_code, 400)
        self.pg.refresh_from_db()
        self.assertEqual(self.pg.ajustes_fundo, [])

    def test_manter_sem_pdf_de_origem_e_recusado(self):
        self.pg.fundo = "outro/p002.jpg"
        self.pg.save(update_fields=["fundo"])
        with self.assertRaises(E.Recusado):
            E.definir_fundo(self.admin, self.pg, {"ajustes": [{"tipo": "manter", "x": 1, "y": 1, "w": 9, "h": 9}]})

    def test_editor_traz_os_dados_do_fundo(self):
        r = self.client.get(reverse("editor_pagina", args=[2030, 2]))
        d = r.context["dados"]
        self.assertEqual(d["ajustes"], [])
        self.assertTrue(d["pdf_original"])
        self.assertContains(r, 'id="ed-modo-fundo"')
        self.assertContains(r, 'id="ed-ajustes"')

    def test_bloco_serializado_traz_a_quebra(self):
        titulo = self.caixa_do_pdf("graduação")
        E.criar(self.admin, self.pg, {"tipo": "texto", "secao": self.grad.pk, "pdf": [titulo["i"]], "texto": "fixo",
                                      "x": titulo["x"], "y": titulo["y"], "w": titulo["w"], "h": titulo["h"]})
        b = E.blocos_da_pagina(self.pg)[0]
        self.assertEqual(b["quebra"], titulo["quebra"])

    def test_relatorio_usa_o_fundo_ajustado(self):
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        self.pg.refresh_from_db()
        r = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(r, self.pg.fundo_url)

    def test_ciclo_novo_copia_os_ajustes(self):
        from relatorio import servicos as S
        self.acao("fundo", {"ajustes": [{"tipo": "apagar", "x": 40, "y": 40, "w": 60, "h": 30}]})
        novo = S.copiar_ciclo(self.c, 2031, "RG 2031")
        self.assertEqual(novo.paginas.get(numero=2).ajustes_fundo, Pagina.objects.get(pk=self.pg.pk).ajustes_fundo)
