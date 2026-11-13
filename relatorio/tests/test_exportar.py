"""Exportação para Word e pacote para a diagramação."""
import io
import zipfile

from docx import Document
from openpyxl import load_workbook

from relatorio.models import Bloco, Ciclo

from .test_texto import Base


class ExportarTests(Base):
    def test_pagina_de_exportacao(self):
        self.entrar("dae")
        r = self.client.get("/ciclos/2025/exportar/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "formato=docx")
        self.assertContains(r, "formato=pacote")

    def test_exige_login(self):
        r = self.client.get("/ciclos/2025/exportar/?formato=docx")
        self.assertEqual(r.status_code, 302)

    def test_docx_tem_estrutura_numeros_e_graficos(self):
        self.entrar("dae")
        r = self.client.get("/ciclos/2025/exportar/?formato=docx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Relatorio-de-Gestao-2025.docx", r["Content-Disposition"])
        doc = Document(io.BytesIO(r.content))
        textos = "\n".join(p.text for p in doc.paragraphs)
        estilos = {p.style.name for p in doc.paragraphs}
        self.assertIn("Heading 1", estilos)
        self.assertIn("Heading 2", estilos)
        self.assertIn("14.755", textos)                       # número vivo resolvido
        self.assertNotIn("sirg-num", textos)
        self.assertNotIn("{{", textos)
        self.assertIn("Tabela 1 –", textos)
        self.assertIn("Gráfico 1 –", textos)
        imagens = [x for x in doc.part.package.parts if x.partname.startswith("/word/media/")]
        n_graficos = Bloco.objects.filter(secao__ciclo__ano=2025, tipo=Bloco.GRAFICO).exclude(
            quadro__chave="frota_km").count()          # o RG 2025 não publicou os números do Gráfico 5
        self.assertGreaterEqual(len(imagens), n_graficos)
        self.assertGreater(len(doc.tables), 5)
        self.assertNotIn("PRELIMINAR", textos)                 # 2025 está encerrado

    def test_ciclo_aberto_sai_como_preliminar(self):
        self.entrar("dppg")
        r = self.client.get("/ciclos/2026/exportar/?formato=docx")
        doc = Document(io.BytesIO(r.content))
        self.assertIn("PRELIMINAR", "\n".join(p.text for p in doc.paragraphs))

    def test_pacote_para_diagramacao(self):
        self.entrar("dppg")
        r = self.client.get("/ciclos/2025/exportar/?formato=pacote")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nomes = z.namelist()
        self.assertIn("Relatorio-de-Gestao-2025.docx", nomes)
        self.assertIn("LEIA-ME.txt", nomes)
        self.assertIn("dados/todos-os-quadros.xlsx", nomes)
        self.assertIn("graficos/dados-dos-graficos.xlsx", nomes)
        pngs = [n for n in nomes if n.startswith("graficos/") and n.endswith(".png")]
        svgs = [n for n in nomes if n.startswith("graficos/") and n.endswith(".svg")]
        self.assertTrue(pngs)
        self.assertEqual(len(pngs), len(svgs))
        self.assertTrue(z.read(pngs[0]).startswith(b"\x89PNG"))
        wb = load_workbook(io.BytesIO(z.read("graficos/dados-dos-graficos.xlsx")))
        self.assertEqual(len(wb.sheetnames), 1 + len(pngs))     # índice + uma aba por gráfico
        leia = z.read("LEIA-ME.txt").decode("utf-8")
        self.assertIn("2025", leia)

    def test_ciclo_inexistente(self):
        self.entrar("dppg")
        self.assertEqual(self.client.get("/ciclos/1999/exportar/?formato=docx").status_code, 404)
        self.assertTrue(Ciclo.objects.filter(ano=2025).exists())
