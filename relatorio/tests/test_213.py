"""2.13: o relatório nas páginas do RG 2025 publicado."""
import json

from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import fluxo as F
from relatorio import paginas as PG
from relatorio.html_seguro import limpar
from relatorio.models import Bloco, Ciclo, Pagina

SENHA = "Senha-forte-2026"


class PaginasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana", setores=[Setor.objects.get(sigla="DIRGRAD")],
                                       senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)

    def test_paginas_iguais_ao_pdf(self):
        self.assertEqual(self.c.paginas.count(), 81)               # o apêndice antigo (p. 82 em diante) saiu
        p = Pagina.objects.get(ciclo=self.c, numero=51)
        self.assertEqual(p.fundo, "rg2025/p051.jpg")
        self.assertIn("CAPÍTULO 2", p.fixos)                       # rodapé fixo
        caixas = list(p.caixas.filter(tipo=Bloco.TEXTO))
        self.assertTrue(caixas and all(b.secao.chave == "ensino_graduacao" for b in caixas))
        cx = caixas[0].config["caixa"]
        self.assertTrue({"x", "y", "w", "css"} <= set(cx))
        self.assertTrue(any("sirg-campo" in b.conteudo or "sirg-num" in b.conteudo for b in caixas))
        # gráficos da plataforma no lugar dos do PDF
        pet = Bloco.objects.get(secao__ciclo=self.c, titulo="Grupos PET")
        self.assertEqual(pet.pagina.numero, 51)
        self.assertGreater(pet.config["caixa"]["w"], 100)
        from relatorio import paineis
        self.assertEqual(len(PG.LUGARES) + len(paineis.GRAFICOS), Bloco.objects.filter(
            secao__ciclo=self.c, pagina__isnull=False).exclude(tipo=Bloco.TEXTO).count())
        # duas seções na mesma página: cada caixa é de quem tem o título acima dela
        self.assertEqual(set(Bloco.objects.filter(pagina__ciclo=self.c, pagina__numero=76).values_list(
            "secao__chave", flat=True)), {"restos_a_pagar", "receitas", "desafios_perspectivas"})
        # sumário: números de página não viram xxxxx
        self.assertFalse(Bloco.objects.filter(pagina__ciclo=self.c, pagina__numero=9, conteudo__contains="sirg-").exists())
        # roda uma vez só, e as execuções seguintes não mexem nas páginas nem nos gráficos no lugar
        n_caixas = Bloco.objects.filter(pagina__ciclo=self.c).count()
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertEqual(self.c.paginas.count(), 81)
        self.assertEqual(Bloco.objects.filter(pagina__ciclo=self.c).count(), n_caixas)
        self.assertEqual(Bloco.objects.get(secao__ciclo=self.c, titulo="Grupos PET").pagina.numero, 51)

    def test_estilo_da_pagina_passa_pela_limpeza(self):
        h = ('<p style="margin-top:3.5px;word-spacing:-0.4px;position:fixed">a <span style="font-size:24px;'
             'font-weight:700;color:#022f77;background:url(x)">2.232</span></p>')
        self.assertEqual(limpar(h), '<p style="margin-top:3.5px;word-spacing:-0.4px">a <span style="font-size:24px;'
                                    'font-weight:700;color:#022f77">2.232</span></p>')

    def test_tela_e_leitura_em_paginas(self):
        self.client.force_login(self.grad)
        h = self.client.get("/ciclos/2026/escrever/?secao=ensino_graduacao").content.decode()
        self.assertIn('id="pg-51"', h)
        self.assertIn("pg-cx pode", h)
        self.assertIn("static/rg2025/p051.jpg", h)
        self.assertIn("sec-card pg-secao pode", h)
        h = self.client.get("/ciclos/2026/ler/").content.decode()
        self.assertIn('class="pg-moldura"', h)
        self.assertNotIn("doc-texto pg-texto editavel", h)

    def test_setor_altera_a_caixa_com_controle_e_preenche(self):
        from relatorio import campos as CT
        b = Bloco.objects.filter(pagina__ciclo=self.c, secao__chave="ensino_graduacao", conteudo__contains="sirg-campo").first()
        F.destravar(self.grad, b)
        novo = b.conteudo.replace("</p>", ' <ins data-s="z1">e mais</ins></p>', 1)
        ok = F.salvar_texto(self.grad, Bloco.objects.get(pk=b.pk), novo)
        self.assertIn("e mais</ins>", ok.conteudo)
        self.assertIn('style="', ok.conteudo)                       # o estilo copiado do PDF continua
        chave = CT.chaves(ok.conteudo)[0]
        F.preencher_campo(self.grad, Bloco.objects.get(pk=b.pk), chave, "33")
        self.assertEqual(CT.valores_do_bloco(Bloco.objects.get(pk=b.pk))[chave], 33)

    def test_ano_seguinte_herda_as_paginas(self):
        from relatorio.servicos import copiar_ciclo
        novo = copiar_ciclo(self.c, 2027, "Relatório de Gestão 2027")
        self.assertEqual(novo.paginas.count(), 81)
        self.assertEqual(Bloco.objects.filter(secao__ciclo=novo, pagina__isnull=False).count(),
                         Bloco.objects.filter(secao__ciclo=self.c, pagina__isnull=False).count())
        self.assertFalse(Bloco.objects.filter(secao__ciclo=novo, pagina__ciclo=self.c).exists())


class PaineisEWordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        PaginasTests.setUpTestData.__func__(cls)
    """2.14: painéis que eram imagem, gráfico atualizado no lugar e Word nas páginas."""

    def test_paineis_editaveis_no_lugar(self):
        pn = Bloco.objects.filter(secao__ciclo=self.c, config__painel__isnull=False)
        self.assertGreaterEqual(pn.count(), 70)
        self.assertTrue(pn.filter(pagina__numero=71, secao__chave="swot", conteudo__contains="FORÇAS").exists() or
                        pn.filter(pagina__numero=71, conteudo__contains="Mapeamento de atividades").exists())
        rank = Bloco.objects.get(secao__ciclo=self.c, config__painel="rank_assunto")
        self.assertEqual((rank.tipo, rank.pagina.numero, rank.quadro.chave), (Bloco.GRAFICO, 27, "ouv_ranking_assunto"))
        custo = pn.get(config__painel="p77_60")
        self.assertIn('data-escala="nmi"', custo.conteudo)
        from relatorio.calculo import Calculadora
        from relatorio.texto import renderizar
        from relatorio.models import Valor
        li = rank.quadro.linhas.get(chave="acesso_info")
        Valor.objects.create(linha=li, coluna=rank.quadro.colunas.get(ano=2026), numero=31)
        self.assertEqual(renderizar('<span class="sirg-num" data-ref="custos_operacionais.limpeza" data-escala="nmi">x'
                                    '</span>', Calculadora(self.c), marcar=False)[0], "xxxxx")
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)          # não duplica
        self.assertEqual(Bloco.objects.filter(secao__ciclo=self.c, config__painel="rank_assunto").count(), 1)

    def test_grafico_volta_no_lugar_ao_atualizar(self):
        import json as J
        self.client.force_login(self.master)
        r = self.client.post("/ciclos/2026/escrever/atualizar/", J.dumps({"quadros": ["grad_pet"]}),
                             content_type="application/json").json()
        pet = Bloco.objects.get(secao__ciclo=self.c, titulo="Grupos PET")
        h = r["blocos"][str(pet.pk)]["html"]
        self.assertIn("pg-obj", h)
        self.assertIn(f'left:{pet.config["caixa"]["x"]}px', h)

    def test_word_com_as_paginas(self):
        import io
        from docx import Document
        self.client.force_login(self.master)
        doc = Document(io.BytesIO(self.client.get("/ciclos/2026/exportar/?formato=docx").content))
        xml = doc.element.xml
        self.assertGreater(xml.count("<wps:txbx"), 1000)            # caixas de texto no lugar
        self.assertGreaterEqual(len(doc.sections), 2)
        self.assertAlmostEqual(doc.sections[0].page_width.pt, 935.4, delta=1)
