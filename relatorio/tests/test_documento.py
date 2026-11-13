"""RG 2026: preparação sem o ciclo 2025, editor de documento, leitura, gráfico ao vivo e tela inicial."""
import json
import re

from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import consistencia
from relatorio.models import Bloco, Ciclo, Coluna, Quadro, Secao, Valor

SENHA = "Senha-forte-2026"


class PreparacaoTests(TestCase):
    def test_instala_so_o_2026_com_historico(self):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertEqual(list(Ciclo.objects.values_list("ano", flat=True)), [2026])
        c = Ciclo.objects.get()
        self.assertEqual(c.situacao, Ciclo.COLETA)
        # histórico 2021-2025 veio do RG 2025 publicado e está travado; 2026 aberto
        mat = Quadro.objects.get(ciclo=c, chave="ga_matriculados")
        self.assertTrue(Coluna.objects.get(quadro=mat, ano=2025).travada)
        self.assertFalse(Coluna.objects.get(quadro=mat, ano=2026).travada)
        self.assertTrue(Valor.objects.filter(linha__quadro=mat, coluna__ano=2025).exists())
        self.assertFalse(Valor.objects.filter(linha__quadro=mat, coluna__ano=2026).exists())
        # nenhuma inconsistência herdada do RG 2025: só o que falta preencher em 2026
        r = consistencia.resumo(consistencia.verificar(c))
        self.assertEqual((r["erros"], r["avisos"]), (0, 0))
        self.assertGreater(r["faltam"], 0)
        # o texto do RG 2025 é a referência da seção e o ponto de partida de 2026
        sec = c.secoes.get(chave="mensagem")
        self.assertIn("Com grande alegria entregamos", sec.referencia)
        self.assertEqual(sec.referencia_fonte, "RG 2025, p. 5–7")
        self.assertEqual(sec.referencia_pagina, 5)
        # desde a 2.13: o texto é o das páginas do RG 2025, caixa por caixa, na mesma posição
        msg = " ".join(Bloco.objects.filter(secao=sec, tipo=Bloco.TEXTO).values_list("conteudo", flat=True))
        self.assertIn("Com grande alegria entregamos", msg)
        self.assertEqual(set(Bloco.objects.filter(secao=sec).values_list("pagina__numero", flat=True)), {5, 6, 7})
        amb = " ".join(Bloco.objects.filter(secao__ciclo=c, secao__chave="ambiente_externo", tipo=Bloco.TEXTO)
                       .values_list("conteudo", flat=True))
        self.assertNotIn('<mark class="atualizar"', amb)        # desde a 2.2: sem destaques prévios
        self.assertIn('data-ref="ouv_manifestacoes.total"', amb)   # número ligado ao dado de 2026
        self.assertNotIn("registrou 482", amb)
        # a estrutura segue o RG 2025: apresentação, áreas finalísticas como subseções, apêndice do PDI
        ordem = [s.chave for s in c.secoes.filter(pai__isnull=True).order_by("ordem")]
        self.assertEqual(ordem, ["apresentacao", "visao_geral", "governanca_desempenho", "riscos_perspectivas",
                                 "orcamento", "apendice"])
        areas = list(c.secoes.filter(nivel=2).order_by("ordem").values_list("chave", flat=True))
        self.assertEqual(areas[:3], ["ensino_tecnico", "ensino_graduacao", "ensino_pos"])
        self.assertEqual(len(areas), 11)
        self.assertTrue(c.secoes.filter(chave="desafios_perspectivas").exists())
        # 2.12: o apêndice é a planilha de metas de 2026 (uma linha por meta, preenchida pela unidade líder)
        metas = Quadro.objects.get(ciclo=c, chave="pdi_metas")
        self.assertEqual(metas.linhas.count(), 41)
        self.assertTrue(metas.colunas.get(chave="od").travada)
        self.assertFalse(metas.colunas.get(chave="situacao").travada)
        self.assertEqual(metas.linhas.get(chave="m4").setor.sigla, "DIRGRAD")
        self.assertEqual(metas.linhas.get(chave="m6").setor.sigla, "GAB")          # GDG = Gabinete
        self.assertFalse(Quadro.objects.filter(ciclo=c, chave="pdi_graduacao_metas").exists())
        self.assertFalse(Quadro.objects.filter(ciclo=c, descricao__contains="RG 2025").exists())
        self.assertTrue(Bloco.objects.filter(secao__ciclo=c, titulo__contains="2026").exists())
        # toda seção tem onde escrever e uma orientação
        for s in c.secoes.filter(pai__isnull=False).exclude(chave__startswith="pdi_"):
            self.assertTrue(s.blocos.filter(tipo=Bloco.TEXTO).exists(), s.chave)
        self.assertTrue(c.secoes.get(chave="pdi_metas").blocos.filter(tipo=Bloco.TABELA).exists())
        self.assertFalse(c.secoes.filter(pai__isnull=False, orientacao="").exists())

    def test_instalacao_antiga_perde_o_2025_e_pode_repetir(self):
        call_command("inicializar", verbosity=0)
        call_command("carregar_rg2025", abrir_2026=True, verbosity=0)
        self.assertEqual(Ciclo.objects.count(), 2)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertEqual(list(Ciclo.objects.values_list("ano", flat=True)), [2026])
        n = Bloco.objects.count()
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertEqual(Bloco.objects.count(), n)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        call_command("criar_admin", login="admin", nome="Admin Geral", senha=SENHA, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana DIRGRAD", setores=[g("DIRGRAD")], senha=SENHA)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo DPPG", setores=[g("DPPG")], senha=SENHA)
        cls.leitor, _ = CS.criar_usuario(login="leitor", nome="Lia Leitora", senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)

    def entrar(self, login):
        self.client.logout()
        self.client.post("/entrar/", {"username": login, "password": SENHA})

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")

    def texto_de(self, chave):
        return Bloco.objects.filter(secao__ciclo=self.c, secao__chave=chave, tipo=Bloco.TEXTO).first()


class EscreverTests(Base):
    def test_cada_um_edita_so_o_seu(self):
        self.entrar("grad")
        r = self.client.get("/escrever/", follow=True)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        meu, alheio = self.texto_de("ensino_graduacao"), self.texto_de("pesquisa_inovacao")
        self.assertRegex(html, rf'class="texto-rg doc-texto[^"]* editavel[^"]*"\s+data-bloco="{meu.pk}"')
        self.assertNotRegex(html, rf'class="texto-rg doc-texto[^"]* editavel[^"]*"\s+data-bloco="{alheio.pk}"')
        self.assertIn("sec-card pg-secao pode", html)   # a seção da pessoa começa com a faixa de ferramentas
        self.assertIn("Enviar ao Master", html)
        self.assertIn('id="so-minhas"', html)           # chave "Só o que eu escrevo" no sumário
        # a seção dos outros é só a página, sem faixa nem botões
        self.assertIn('<span class="pg-ancora doc-sec" id="sec-pesquisa_inovacao"', html)

    def test_leitor_nao_edita_nada(self):
        self.entrar("leitor")
        html = self.client.get("/ciclos/2026/escrever/").content.decode()
        self.assertNotIn("doc-texto editavel", html)
        self.assertNotIn("js-dica-topo", html)

    def test_master_pode_tudo_e_sugerir(self):
        self.entrar("master")
        html = self.client.get("/ciclos/2026/escrever/").content.decode()
        self.assertIn("js-rastreio", html)                  # o Master liga ou desliga o controle de alterações
        self.assertIn("rastreioObrigatorio: false", html)
        self.assertEqual(len(re.findall(r'class="texto-rg doc-texto[^"]* editavel', html)),
                         Bloco.objects.filter(secao__ciclo=self.c, tipo=Bloco.TEXTO).count())

    def test_digitar_salvar_e_a_trava_aparece_para_o_colega(self):
        b = self.texto_de("ensino_graduacao")
        self.entrar("grad")
        r = self.post(f"/ciclos/2026/blocos/{b.pk}/travar/", {"modo": "editar"}).json()
        self.assertTrue(r["ok"])
        # o setor escreve com o controle de alterações: o texto base fica, o novo entra marcado
        r1 = self.post(f"/ciclos/2026/blocos/{b.pk}/texto/", {"html": "<p>Novo texto da graduação.</p>",
                                                            "versao": r["versao"]}).json()
        self.assertFalse(r1["ok"])
        html = b.conteudo.replace("</p>", ' <ins data-s="g1">Novo texto da graduação.</ins></p>', 1)
        r = self.post(f"/ciclos/2026/blocos/{b.pk}/texto/", {"html": html, "versao": r["versao"]}).json()
        self.assertTrue(r["ok"], r)
        b.refresh_from_db()
        self.assertIn('<ins data-s="g1" data-a="Ana DIRGRAD"', b.conteudo)
        self.assertNotIn("modelo", b.config)                 # deixou de ser texto-modelo
        self.entrar("master")
        estado = self.client.get("/ciclos/2026/escrever/estado/").json()["blocos"]
        self.assertEqual(estado[str(b.pk)]["por"], "Ana DIRGRAD")
        self.assertEqual(estado[str(b.pk)]["v"], b.atualizado_em.isoformat())
        h = self.client.get(f"/ciclos/2026/blocos/{b.pk}/html/").json()
        self.assertIn("Novo texto da graduação", h["html"])

    def test_inserir_e_apagar_trecho(self):
        sec = Secao.objects.get(ciclo=self.c, chave="ensino_graduacao")
        self.entrar("grad")              # desde a 2.12, o setor não cria trechos novos
        self.assertFalse(self.post("/ciclos/2026/escrever/inserir/", {"secao": sec.pk}).json()["ok"])
        self.entrar("master")
        r = self.post("/ciclos/2026/escrever/inserir/", {"secao": sec.pk}).json()
        self.assertTrue(r["ok"])
        self.assertIn(f'data-bloco="{r["id"]}"', r["html"])
        self.assertIn("doc-texto editavel", r["html"])
        r2 = self.post(f"/ciclos/2026/blocos/{r['id']}/excluir-texto/", {}).json()
        self.assertTrue(r2["ok"])
        self.assertFalse(Bloco.objects.filter(pk=r["id"]).exists())
        # na seção de outro setor, não
        outra = Secao.objects.get(ciclo=self.c, chave="pesquisa_inovacao")
        self.entrar("grad")
        self.assertEqual(self.post("/ciclos/2026/escrever/inserir/", {"secao": outra.pk}).status_code, 403)
        figura = Bloco.objects.filter(secao=sec).exclude(tipo=Bloco.TEXTO).first()
        self.assertEqual(self.post(f"/ciclos/2026/blocos/{figura.pk}/excluir-texto/", {}).status_code, 400)

    def test_voltar_so_para_dentro_da_plataforma(self):
        sec = Secao.objects.get(ciclo=self.c, chave="ensino_graduacao")
        self.entrar("grad")
        r = self.client.post(f"/ciclos/2026/secoes/{sec.chave}/comentar/",
                             {"texto": "Conferir com a SRCA", "voltar": "/ciclos/2026/escrever/?secao=ensino_graduacao"})
        self.assertEqual(r["Location"], "/ciclos/2026/escrever/?secao=ensino_graduacao")
        r = self.client.post(f"/ciclos/2026/secoes/{sec.chave}/comentar/",
                             {"texto": "outro", "voltar": "https://exemplo.com/roubo"})
        self.assertNotIn("exemplo.com", r["Location"])


class LerTests(Base):
    def test_todos_leem_sem_ferramentas_de_edicao(self):
        for login in ("leitor", "grad", "master"):
            self.entrar(login)
            r = self.client.get("/ler/", follow=True)
            self.assertEqual(r.status_code, 200)
            html = r.content.decode()
            self.assertIn("Somente leitura", html)
            self.assertNotIn("doc-texto editavel", html)
            self.assertNotIn("doc-sec-cab", html)
            self.assertIn("grafico-svg", html)
            self.assertIn("xxxxx", html)                  # números de 2026 ainda não digitados
            self.assertIn('class="pg-moldura"', html)     # as páginas do RG

    def test_endereco_antigo_do_documento(self):
        self.entrar("leitor")
        self.assertContains(self.client.get("/ciclos/2026/documento/"), "Somente leitura")


class GraficoAoLadoTests(Base):
    def test_grafico_aparece_e_se_atualiza(self):
        self.entrar("grad")
        r = self.client.get("/ciclos/2026/secoes/ensino_graduacao/")
        self.assertContains(r, "Como fica no relatório")
        self.assertContains(r, "Preencher os números")
        q = Quadro.objects.get(ciclo=self.c, chave="grad_pet")
        antes = self.client.get(f"/ciclos/2026/quadros/{q.pk}/graficos/").json()["graficos"]
        self.assertTrue(antes and "<svg" in antes[0]["svg"])
        linha = q.linhas.get(chave="alunos")
        col = q.colunas.get(ano=2026)
        r = self.post("/ciclos/2026/celula/", {"linha": linha.pk, "coluna": col.pk, "valor": "152"})
        self.assertTrue(r.json()["ok"], r.json())
        depois = self.client.get(f"/ciclos/2026/quadros/{q.pk}/graficos/").json()["graficos"]
        self.assertIn("152", depois[0]["svg"])
        self.assertNotEqual(antes[0]["svg"], depois[0]["svg"])


class InicioTests(Base):
    def test_passos_para_quem_tem_setor(self):
        self.entrar("grad")
        r = self.client.get("/")
        self.assertContains(r, "Abrir o relatório")
        self.assertContains(r, "Ensino de Graduação")
        self.assertContains(r, "/ciclos/2026/escrever/?secao=")

    def test_leitor_ve_atalho_de_leitura(self):
        self.entrar("leitor")
        r = self.client.get("/")
        self.assertNotContains(r, "Suas seções")
        self.assertContains(r, "Abrir o relatório")
        self.assertContains(r, "só pode ler o relatório")

    def test_menu_focado_no_2026(self):
        self.entrar("grad")
        html = self.client.get("/").content.decode()
        menu = html.split('<div class="conteudo">')[0]
        self.assertNotIn('class="sidebar"', html)                    # 2.12: um só menu, no alto
        for item in ("Início", "Relatório", "O que falta", "Manual de uso", "Sobre"):
            self.assertIn(item, menu)
        self.assertNotIn("Preencher os números", menu)
        self.assertNotIn("2025", menu)
        self.assertNotIn("Inconsistências", html)

    def test_o_que_falta_comeca_pelo_meu_setor(self):
        self.entrar("grad")
        r = self.client.get("/ciclos/2026/pendencias/")
        self.assertContains(r, "somente as seções do seu setor")
        self.assertNotContains(r, "DPPG</span>")
        r = self.client.get("/ciclos/2026/pendencias/?minhas=0")
        self.assertContains(r, "relatório inteiro")


class DestaquesTests(Base):
    def test_rascunho_sem_destaques_e_com_numeros_ligados(self):
        from relatorio import rascunho as R
        from relatorio.calculo import Calculadora
        html = R.rascunho("<p>Texto sem número. Foram 14.755 matriculados em 2025.</p><p>{{FIGURA:Mapa}}</p>",
                          Calculadora(self.c), 2025, "5")
        self.assertNotIn("<mark", html)
        self.assertIn('data-ref="ga_matriculados.total"', html)
        self.assertIn("[Figura do RG 2025, p. 5: Mapa.", html)
        self.assertEqual(R.contar_avisos(html), 1)
        # quem quiser, ainda pode pedir os destaques
        self.assertIn('data-orig="Foram 14.755 matriculados em 2025."',
                      R.rascunho("<p>Foram 14.755 matriculados em 2025.</p>", Calculadora(self.c), 2025, destacar=True))

    def test_marca_texto_conta_no_documento_e_no_que_falta(self):
        from relatorio.texto import contar_marcas
        b = self.texto_de("ensino_graduacao")
        self.assertEqual(contar_marcas(b.conteudo), 0)
        b.conteudo = '<p><mark class="atualizar">Trecho a revisar</mark> e o resto.</p>'
        b.save()
        self.entrar("grad")
        html = self.client.get("/ciclos/2026/escrever/?secao=ensino_graduacao").content.decode()
        self.assertIn("1 em amarelo", html)
        self.assertIn("RG 2025, p. 51", html)
        self.assertIn("referencia/RG2025.pdf#page=51", html)
        r = self.client.get("/ciclos/2026/pendencias/")
        self.assertContains(r, "marcado com o marca-texto")
        self.post(f"/ciclos/2026/blocos/{b.pk}/travar/", {"modo": "editar"})
        b.refresh_from_db()
        r = self.post(f"/ciclos/2026/blocos/{b.pk}/texto/", {"html": "<p>Trecho a revisar e o resto.</p>",
                                                           "versao": b.atualizado_em.isoformat()}).json()
        self.assertTrue(r["ok"], r)
        b.refresh_from_db()
        self.assertEqual(contar_marcas(b.conteudo), 0)

    def test_destaque_sobrevive_a_limpeza_e_vai_para_o_word(self):
        import io

        from docx import Document
        from relatorio.html_seguro import limpar
        h = limpar('<p><mark class="atualizar" data-orig="antes" onclick="x">novo</mark> <mark>colado</mark></p>')
        self.assertEqual(h, '<p><mark class="atualizar" data-orig="antes">novo</mark> colado</p>')
        b = self.texto_de("ensino_graduacao")
        b.conteudo = h
        b.save()
        self.entrar("master")
        r = self.client.get("/ciclos/2026/exportar/?formato=docx")
        doc = Document(io.BytesIO(r.content))
        # desde a 2.14 o Word segue as páginas do RG: o texto vai na caixa da página, sem as marcas da tela
        self.assertIn("novo", doc.element.xml)
        self.assertIn("colado", doc.element.xml)

    def test_quadro_calculado_vazio_nao_aparece_como_ok(self):
        self.entrar("grad")
        html = self.client.get("/ciclos/2026/secoes/ensino_graduacao/").content.decode()
        bloco = html.split('id="quadro-grad_numeros"')[1].split('class="card quadro')[0]
        self.assertIn("aguardando dados", bloco)
        self.assertIn("não é preciso digitar", bloco)
        self.assertNotIn("> ok</span>", bloco)


class GraficosRGTests(Base):
    def test_graficos_seguem_o_rg2025(self):
        from relatorio import graficos
        from relatorio.calculo import Calculadora
        calc = Calculadora(self.c)
        cfg = {b.titulo: (b.quadro.chave, b.config) for b in Bloco.objects.filter(
            secao__ciclo=self.c, tipo=Bloco.GRAFICO).select_related("quadro")}
        # barras + linha de recursos, como no RG
        self.assertEqual(cfg["Grupos PET"][1].get("linha"), "recursos")
        self.assertEqual(cfg["Grupos PET"][1].get("linhas"), ["alunos"])
        for t in ("Monitoria", "Bolsas stricto sensu", "Iniciação científica", "Programas de capacitação",
                  "Ações de extensão por natureza", "Ações de extensão por categoria",
                  "Quantidade de servidores atendidos por curso EDS", "Refeições servidas nos restaurantes estudantis",
                  "Alunos em dupla diplomação", "Docentes em mobilidade internacional", "Titulação dos docentes"):
            self.assertIn(t, cfg)
        self.assertEqual(cfg["Ações de extensão por área temática"][1]["tipo"], "barras_horizontais")
        q = calc.quadros["grad_pet"]
        nome, vals, tipo, _ = graficos.serie_linha(calc, q, cfg["Grupos PET"][1])
        self.assertEqual(nome, "Recursos utilizados")
        self.assertEqual(vals[:4], [472003.38, 620341.2, 666890.0, 671406.99])
        svg, avisos = graficos.desenhar(calc, q, cfg["Grupos PET"][1])
        self.assertTrue(svg.startswith("<svg"), avisos)
        self.assertIn("R$ 671.406,99", svg)          # valor completo escrito no ponto, como no RG
        # linha vinda de outro quadro, alinhada pelas linhas (capacitação: valor x servidores)
        q = calc.quadros["gp_capacitacao_valor"]
        _, vals, _, _ = graficos.serie_linha(calc, q, cfg["Programas de capacitação"][1])
        self.assertEqual(len(vals), len(calc.linhas_de(q)))
        # o gráfico entra no meio do texto, onde o RG o mostrava
        tipos = list(Bloco.objects.filter(secao__ciclo=self.c, secao__chave="quem_somos").order_by("ordem")
                     .values_list("tipo", flat=True))
        self.assertEqual(tipos[:3], ["texto", "grafico", "grafico"])
        self.assertIn("texto", tipos[3:])

    def test_tela_de_configuracao_oferece_linha_sobre_as_barras(self):
        b = Bloco.objects.get(secao__ciclo=self.c, titulo="Grupos PET")
        self.entrar("grad")
        html = self.client.get(f"/ciclos/2026/blocos/{b.pk}/configurar/").content.decode()
        self.assertIn("Linha sobre as barras", html)
        self.assertIn('value="recursos" selected', html)


class NumeroOrigemTests(Base):
    def test_numero_mostra_de_onde_vem(self):
        from relatorio.calculo import Calculadora
        from relatorio.texto import renderizar
        html, _ = renderizar('<p><span class="sirg-num" data-ref="tec_auxilio.alunos">1</span></p>', Calculadora(self.c))
        self.assertIn(">xxxxx<", html)
        self.assertIn('data-setor="DEPT"', html)
        self.assertIn("Auxílio discente no ensino técnico › Alunos atendidos (2026)", html)
        self.assertIn("/ciclos/2026/secoes/ensino_tecnico/?aba=dados#quadro-tec_auxilio", html)
        self.assertIn("ainda não foi preenchido", html)


class ImagensTests(Base):
    def _png(self):
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (300, 120), (23, 55, 94)).save(buf, "PNG")
        buf.seek(0)
        buf.name = "mapa-estrategico.png"
        return buf

    def test_envia_insere_mostra_e_exporta(self):
        import io
        import tempfile
        import zipfile

        from django.test import override_settings
        from docx import Document
        with tempfile.TemporaryDirectory() as pasta, override_settings(MEDIA_ROOT=pasta):
            b = self.texto_de("ensino_graduacao")
            self.entrar("grad")              # 2.12: imagens novas são do Master
            self.assertEqual(self.client.post("/ciclos/2026/imagens/enviar/", {"arquivo": self._png(),
                                                                              "secao": b.secao.pk}).status_code, 403)
            self.entrar("master")
            r = self.client.post("/ciclos/2026/imagens/enviar/", {"arquivo": self._png(), "secao": b.secao.pk}).json()
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["nome"], "mapa-estrategico")
            self.assertEqual(self.client.get(r["url"]).status_code, 200)
            # setor de outra seção não envia para esta
            self.entrar("dppg")
            r2 = self.client.post("/ciclos/2026/imagens/enviar/", {"arquivo": self._png(), "secao": b.secao.pk})
            self.assertEqual(r2.status_code, 403)
            # arquivo que não é imagem
            self.entrar("master")
            falso = io.BytesIO(b"nao sou imagem")
            falso.name = "x.png"
            r3 = self.client.post("/ciclos/2026/imagens/enviar/", {"arquivo": falso, "secao": b.secao.pk})
            self.assertEqual(r3.status_code, 400)
            # a imagem passa pela limpeza e vai para o Word e para o pacote
            self.post(f"/ciclos/2026/blocos/{b.pk}/travar/", {"modo": "editar"})
            b.refresh_from_db()
            html = f'<p>Figura:</p><p><img src="{r["url"]}" alt="Mapa" onerror="x"></p>'
            j = self.post(f"/ciclos/2026/blocos/{b.pk}/texto/", {"html": html, "versao": b.atualizado_em.isoformat()}).json()
            self.assertTrue(j["ok"], j)
            b.refresh_from_db()
            self.assertIn(f'<img src="{r["url"]}" alt="Mapa">', b.conteudo)
            doc = Document(io.BytesIO(self.client.get("/ciclos/2026/exportar/?formato=docx").content))
            self.assertTrue(doc.inline_shapes)
            z = zipfile.ZipFile(io.BytesIO(self.client.get("/ciclos/2026/exportar/?formato=pacote").content))
            self.assertTrue(any(n.startswith("imagens/") for n in z.namelist()))

    def test_imagem_de_fora_e_removida(self):
        from relatorio.html_seguro import limpar
        self.assertEqual(limpar('<p>a<img src="https://exemplo.com/x.png">b</p>'), "<p>ab</p>")


class FiltrosTests(Base):
    def test_telas_tem_filtros(self):
        self.entrar("grad")
        for url in ("/ciclos/2026/?minhas=0", "/ciclos/2026/pendencias/?minhas=0"):
            html = self.client.get(url).content.decode()
            self.assertIn('class="filtros"', html, url)
            self.assertIn('data-campo="setor"', html)
            self.assertIn('data-campo="cap"', html)
            self.assertIn("data-item", html)
            self.assertIn("js/filtros.js", html)
        html = self.client.get("/ciclos/2026/pendencias/?minhas=0").content.decode()
        self.assertIn('data-campo="secao"', html)
        self.assertIn('data-f-setor="DIRGRAD ', html)


class MetasPDINoTextoTests(Base):
    def test_metas_sao_preenchidas_no_documento_e_nao_em_numeros(self):
        self.entrar("grad")
        html = self.client.get("/ciclos/2026/escrever/?secao=pdi_metas").content.decode()
        self.assertIn("metas-2026", html)
        self.assertIn("<option>Em andamento</option>", html)
        q = Quadro.objects.get(ciclo=self.c, chave="pdi_metas")
        li = q.linhas.get(chave="m4")               # meta da DIRGRAD
        col = q.colunas.get(chave="situacao")
        r = self.post("/ciclos/2026/celula/", {"linha": li.pk, "coluna": col.pk, "valor": "Em andamento",
                                               "anterior": ""}).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(Valor.objects.get(linha=li, coluna=col).texto, "Em andamento")
        # a meta de outra unidade (DEPT) não
        outra = q.linhas.get(chave="m1")
        r = self.post("/ciclos/2026/celula/", {"linha": outra.pk, "coluna": col.pk, "valor": "Concluído", "anterior": ""})
        self.assertFalse(r.json()["ok"])
        # em andamento sem evidência: falta a evidência
        from relatorio import consistencia
        msgs = [p.mensagem for p in consistencia.verificar(self.c, quadros=[q]) if p.linha and p.linha.pk == li.pk]
        self.assertIn("Meta 4: em andamento — informe a evidência", msgs)
        # a planilha sai no formato da DGDI, com o que foi preenchido
        import io

        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(self.client.get("/ciclos/2026/pdi/planilha/").content))
        ws = wb["Dados"]
        linha = next(r for r in range(3, ws.max_row + 1) if str(ws.cell(r, 1).value) == "4")
        self.assertEqual(ws.cell(linha, 7).value, "Em andamento")
        # Preencher os números: só números (a seção de metas não aparece)
        lista = self.client.get("/ciclos/2026/").content.decode()
        self.assertNotIn("Área: Ensino de Graduação", lista)
        self.assertIn("Ensino de Graduação", lista)
        # no O que falta, as metas levam para o documento
        pend = self.client.get("/ciclos/2026/pendencias/").content.decode()
        self.assertIn("/escrever/?secao=pdi_metas", pend)


class AtualizacaoDeInstalacaoTests(TestCase):
    def test_instalacao_anterior_recebe_estrutura_nova_sem_perder_dados(self):
        """Simula um RG 2026 criado pela versão 2.1: destaques prontos, sem os quadros e gráficos novos
        (e ainda sem as páginas do RG, que só vêm na 2.13)."""
        import re
        from unittest import mock
        sem_paginas = mock.patch("relatorio.paginas.paginas_pdf", return_value={})
        sem_paginas.start()
        self.addCleanup(sem_paginas.stop)
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        c = Ciclo.objects.get(ano=2026)
        # como na 2.1: texto com destaques prontos, sem a marca de "já tratado", gráfico antigo, quadro a menos
        b = c.secoes.get(chave="ensino_graduacao").blocos.filter(tipo=Bloco.TEXTO).first()
        Bloco.objects.filter(pk=b.pk).update(
            conteudo='<p><mark class="atualizar" data-orig="x">Em 2025 foram 5 competições.</mark></p>'
                     '<p><mark class="atualizar" data-orig="figura">[Figura do RG 2025]</mark></p>',
            config={"rascunho_rg": 2025})
        g = Bloco.objects.get(secao__ciclo=c, tipo=Bloco.GRAFICO, titulo="Grupos PET")
        Bloco.objects.filter(pk=g.pk).update(titulo="Programa de Educação Tutorial", config={"tipo": "barras"})
        Quadro.objects.filter(ciclo=c, chave="ext_natureza").delete()
        pet = Quadro.objects.get(ciclo=c, chave="grad_pet")
        v = Valor.objects.create(linha=pet.linhas.get(chave="alunos"), coluna=pet.colunas.get(ano=2026), numero=150)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        b.refresh_from_db()
        self.assertNotIn("<mark", b.conteudo)
        from relatorio import campos as CT
        self.assertIn("Em 2025 foram xxxxx competições.", CT.renderizar(b.conteudo, {}, marcar=False)[0])
        self.assertIn("<em>[Figura do RG 2025]</em>", b.conteudo)
        self.assertTrue(Quadro.objects.filter(ciclo=c, chave="ext_natureza").exists())
        self.assertTrue(Bloco.objects.filter(secao__ciclo=c, titulo="Grupos PET", config__linha="recursos").exists())
        self.assertFalse(Bloco.objects.filter(secao__ciclo=c, titulo="Programa de Educação Tutorial").exists())
        self.assertTrue(Valor.objects.filter(pk=v.pk, numero=150).exists())
        self.assertEqual(list(Ciclo.objects.values_list("ano", flat=True)), [2026])
        # um destaque feito depois com o marca-texto não é tirado numa nova execução
        Bloco.objects.filter(pk=b.pk).update(conteudo='<p><mark class="atualizar">revisar</mark></p>')
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        b.refresh_from_db()
        self.assertEqual(len(re.findall("<mark", b.conteudo)), 1)


class NomePaletaEmNumerosTests(Base):
    def test_nome_novo_da_instituicao_e_secao_em_numeros(self):
        from contas.models import Instituicao
        from relatorio.dados_iniciais import rg2026
        inst = Instituicao.atual()
        self.assertEqual((inst.nome, inst.sigla), (rg2026.NOME_NOVO, "UFCIMG"))
        # nas páginas, cada menção ao CEFET-MG fica marcada para quem escreve escolher (e o nome por extenso com a
        # sigla, num parágrafo, já vem trocado)
        dirig = " ".join(Bloco.objects.filter(secao__ciclo=self.c, secao__chave="dirigentes").values_list("conteudo", flat=True))
        self.assertIn('class="nome-inst"', dirig)
        visao = " ".join(Bloco.objects.filter(secao__ciclo=self.c, secao__chave="visao_geral").values_list("conteudo", flat=True))
        self.assertIn("Universidade Federal de Ciência e Inovação de Minas Gerais – UFCIMG", visao)
        self.assertEqual(rg2026.trocar_nome_no_texto("<p>O Centro Federal de Educação Tecnológica de Minas Gerais – "
                                                     "CEFET-MG é uma autarquia</p>"),
                         "<p>A Universidade Federal de Ciência e Inovação de Minas Gerais – UFCIMG é uma autarquia</p>")
        # menção histórica, sem a sigla junto, fica
        h = "<p>Em 1978, transformada em Centro Federal de Educação Tecnológica de Minas Gerais, pela Lei</p>"
        self.assertEqual(rg2026.trocar_nome_no_texto(h), h)
        s = Secao.objects.get(ciclo=self.c, chave="em_numeros")
        self.assertEqual(s.titulo, "UFCIMG em números")
        irmas = list(s.pai.filhas.order_by("ordem").values_list("chave", flat=True))
        self.assertEqual(irmas[irmas.index("mensagem") + 1], "em_numeros")
        txt = self.texto_de("em_numeros").conteudo
        self.assertIn("OBJETIVO ESTRATÉGICO 14", txt)
        self.assertIn("OE-14 – Otimizar a gestão orçamentária", txt)
        self.assertEqual(rg2026.secao_em_numeros(self.c), 0)      # não duplica

    def test_master_escolhe_a_paleta_dos_graficos(self):
        from contas.models import Instituicao
        from relatorio import graficos
        from relatorio.calculo import Calculadora
        self.entrar("grad")
        self.assertEqual(self.client.get("/graficos/cores/").status_code, 403)
        self.entrar("master")
        r = self.client.get("/graficos/cores/")
        self.assertContains(r, "Acessível (daltonismo)")
        calc = Calculadora(self.c)
        q = calc.quadros["grad_pet"]
        cfg = {"tipo": "barras", "linhas": ["alunos"], "linha": "recursos"}
        antes, _ = graficos.desenhar(calc, q, cfg)
        self.client.post("/graficos/cores/", {"paleta": "acessivel"})
        self.assertEqual(Instituicao.atual().paleta_graficos, "acessivel")
        depois, _ = graficos.desenhar(calc, q, cfg)
        self.assertIn("#2971c6", depois.lower())
        self.assertNotEqual(antes, depois)


class MencoesAoCefetTests(Base):
    """Menções ao CEFET-MG nos textos ficam em amarelo para quem escreve escolher CEFET-MG ou UFCIMG (v2.5)."""

    def test_marca_com_artigo_e_ignora_links_e_outros_cefets(self):
        from relatorio import nome_inst
        h, n = nome_inst.marcar('<p>Em 2025, o CEFET-MG captou; DO Cefet MG; os CEFETs, o CEFET-RJ e '
                                '<a href="https://www.cefetmg.br">CEFET-MG</a>. O Centro Federal de Educação '
                                'Tecnológica de Minas Gerais foi criado em 1978.</p>')
        self.assertEqual(n, 3)
        self.assertIn('data-antes="o CEFET-MG" data-depois="a UFCIMG"', h)
        self.assertIn('data-antes="DO Cefet MG" data-depois="DA UFCIMG"', h)
        self.assertIn('data-depois="A Universidade Federal de Ciência e Inovação de Minas Gerais"', h)
        self.assertIn("CEFET-RJ", h)
        self.assertEqual(nome_inst.marcar(h), (h, 0))         # rodar de novo não marca outra vez
        self.assertEqual(nome_inst.contar(h), 3)

    def test_marca_passa_pela_limpeza(self):
        from relatorio import nome_inst
        from relatorio.html_seguro import limpar
        h, _ = nome_inst.marcar("<p>Do CEFET-MG.</p>")
        self.assertEqual(limpar(h), h)

    def test_escolha_manter_nao_volta_a_ser_marcada(self):
        from relatorio import nome_inst
        from relatorio.dados_iniciais import rg2026
        b = Bloco.objects.filter(secao__ciclo=self.c, tipo=Bloco.TEXTO, conteudo__contains="nome-inst").first()
        self.assertIsNotNone(b)
        b.conteudo = re.sub(r'<mark class="nome-inst"[^>]*>(.*?)</mark>', r"\1", b.conteudo)   # "manter"
        b.save()
        rg2026.renomear_instituicao(self.c)
        b.refresh_from_db()
        self.assertEqual(nome_inst.contar(b.conteudo), 0)


class PilotoWesleyTests(Base):
    """Ajustes da segunda rodada do piloto (v2.6)."""

    def test_mensagem_da_dirigente_fica_na_pagina(self):
        # desde a 2.13 a mensagem é a das páginas do RG 2025, para a dirigente atualizar (antes começava em branco)
        msg = " ".join(Bloco.objects.filter(secao__ciclo=self.c, secao__chave="mensagem").values_list("conteudo", flat=True))
        self.assertIn("MENSAGEM DA DIRIGENTE", msg)
        self.assertTrue(Secao.objects.get(ciclo=self.c, chave="mensagem").referencia)   # o de 2025 fica para consulta

    def test_numero_de_norma_nao_e_ligado_a_quadro(self):
        from relatorio.rascunho import _ligar_numeros, desligar_identificadores
        idx = {"198": "ouv_manifestacoes.denuncia"}
        h = _ligar_numeros("Decisão Normativa TCU nº 198/2022 e 198 denúncias.", idx)
        self.assertEqual(h.count("sirg-num"), 1)
        self.assertIn('nº 198/2022', h)
        errado = 'Decisão Normativa TCU nº <span class="sirg-num" data-ref="ouv_manifestacoes.denuncia">198</span>/2022'
        self.assertEqual(desligar_identificadores(errado), ("Decisão Normativa TCU nº 198/2022", 1))

    def test_planilha_de_conferencia_e_nomes_de_abas(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from relatorio.planilhas import _nome_aba
        usados = set()
        nomes = [_nome_aba("Custo do transporte de bens e passageiros", usados), _nome_aba("History", usados)]
        self.assertEqual(nomes, ["Custo do transporte de bens", "Quadro History"])
        self.entrar("grad")
        r = self.client.get("/ciclos/2026/conferencia/")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(BytesIO(r.content))
        self.assertEqual(wb.sheetnames[1:], ["1. Números no texto", "2. Tabelas e gráficos", "3. Quadros",
                                             "4. Números não ligados"])
        self.assertGreater(wb["3. Quadros"].max_row, 100)


class AuditoriaTests(Base):
    """Achados da auditoria independente de dados e lógica (v2.10)."""

    def test_regra_de_mobilidade_usa_o_ano_do_relatorio(self):
        from relatorio.models import Regra
        self.assertFalse(Regra.objects.filter(ciclo=self.c, direita__contains=f".a{self.c.ano - 1}").exists())
        self.assertTrue(Regra.objects.filter(ciclo=self.c, direita="ri_mobilidade.entrada.atual").exists())

    def test_regras_por_grupo_na_execucao(self):
        from relatorio.models import Regra
        self.assertEqual(Regra.objects.filter(ciclo=self.c, quadro__chave="orc_execucao",
                                              esquerda="orc_execucao.pessoal.pagas").count(), 1)

    def test_numero_em_milhoes_e_ligado_e_mostrado_na_escala(self):
        from decimal import Decimal

        from relatorio.calculo import Calculadora
        from relatorio.rascunho import _ligar_numeros
        from relatorio.texto import em_escala, renderizar
        h = _ligar_numeros("dotação de R$ 570,87 milhões", {"R$ 570,87 milhões": "orc_execucao.pessoal"})
        self.assertIn('data-escala="mi"', h)
        self.assertEqual(em_escala(Decimal("600000000"), "mi"), "R$ 600 milhões")
        self.assertEqual(em_escala(Decimal("1500000"), "mi"), "R$ 1,50 milhão")
        out, _ = renderizar(h, Calculadora(self.c))
        self.assertIn('data-escala="mi"', out)

    def test_divergencia_de_fonte_unica_e_erro(self):
        import inspect

        from relatorio import consistencia
        self.assertIn('"erro", "divergencia"', inspect.getsource(consistencia.verificar))
