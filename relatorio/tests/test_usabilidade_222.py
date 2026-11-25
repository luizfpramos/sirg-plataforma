"""2.22: revisão de usabilidade — a mesma conta do que falta em todas as telas, o que é de outro setor discreto,
o motivo do envio bloqueado escrito, Reabrir no Relatório, acessibilidade dos gráficos e dos xxxxx, nomes."""
import re

from relatorio import pendentes
from relatorio.formato import qtd
from relatorio.models import Bloco, Secao

from .test_documento import Base


def _numero(html, padrao):
    m = re.search(padrao, html, re.S)
    return int(m.group(1)) if m else None


class ContaUnicaTests(Base):
    def _telas(self, login):
        self.entrar(login)
        inicio = self.client.get("/").content.decode()
        relatorio = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        falta = self.client.get(f"/ciclos/{self.c.ano}/pendencias/").content.decode()
        quadros = self.client.get(f"/ciclos/{self.c.ano}/").content.decode()
        return inicio, relatorio, falta, quadros

    def test_setor_ve_o_mesmo_total_em_todas_as_telas(self):
        conta = pendentes.a_preencher(self.grad, self.c)
        self.assertGreater(conta["total"], 0)
        self.assertGreater(conta["numeros"], 0)          # inclui as metas do PDI da DIRGRAD
        inicio, relatorio, falta, quadros = self._telas("grad")
        n = conta["total"]
        self.assertEqual(_numero(inicio, r"Faltam <strong>(\d+)</strong> ite"), n)
        self.assertEqual(_numero(relatorio, r'js-faltam"[^>]*>.*?<span>Faltam (\d+)</span>'), n)
        self.assertEqual(_numero(falta, r'cartao-num[^>]*>\s*(\d+)\s*</div><strong>ite'), n)
        self.assertEqual(_numero(quadros, r"(\d+) a preencher</span>"), n)

    def test_editor_chefe_ve_o_mesmo_total_em_todas_as_telas(self):
        conta = pendentes.a_preencher(self.master, self.c)
        self.assertEqual(conta, pendentes.a_preencher(self.master, self.c, todas=True))
        n = conta["total"]
        inicio, relatorio, falta, quadros = self._telas("master")
        self.assertEqual(_numero(inicio, r'cartao-num">(\d+)</div><div class="mini text-secondary">ite'), n)
        self.assertEqual(_numero(relatorio, r'js-faltam"[^>]*>.*?<span>Faltam (\d+)</span>'), n)
        self.assertEqual(_numero(falta, r'cartao-num[^>]*>\s*(\d+)\s*</div><strong>ite'), n)
        self.assertEqual(_numero(quadros, r"(\d+) a preencher</span>"), n)
        word = self.client.get(f"/ciclos/{self.c.ano}/exportar/").content.decode()
        self.assertEqual(_numero(word, r"A preencher:.*?(\d+) a preencher</span>"), n)

    def test_secoes_do_fluxo_iguais_no_inicio_no_ler_e_no_word(self):
        n = pendentes.secoes_do_fluxo(self.c).count()
        self.assertGreater(n, self.c.secoes.filter(pai__isnull=False).count())   # capítulos com texto contam
        self.entrar("master")
        inicio = self.client.get("/").content.decode()
        self.assertIn(f'/{n}</span></div><div class="mini text-secondary">seções aprovadas', inicio)
        self.assertIn(f"0 de {n} seções aprovadas", self.client.get(f"/ciclos/{self.c.ano}/ler/").content.decode())
        self.assertIn(f"<strong>0 de {n}</strong>", self.client.get(f"/ciclos/{self.c.ano}/exportar/").content.decode())

    def test_recontagem_ao_vivo_usa_a_mesma_conta(self):
        self.entrar("grad")
        metas = self.c.secoes.get(chave="pdi_metas")
        r = self.post(f"/ciclos/{self.c.ano}/escrever/atualizar/", {"secoes": [metas.pk]}).json()
        conta = pendentes.a_preencher(self.grad, self.c)
        self.assertEqual(r["total"], conta["total"])
        self.assertEqual(r["faltam"][str(metas.pk)], conta["por_secao"][metas.pk])


class RelatorioSetorTests(Base):
    def test_xxxxx_do_setor_tem_papel_de_botao_e_os_dos_outros_nao(self):
        self.entrar("grad")
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        meus = re.findall(r'<span class="sirg-campo vazio pode"[^>]*>', h)
        self.assertTrue(meus)
        self.assertTrue(all('role="button"' in s and 'aria-label="Preencher número.' in s for s in meus))
        alheios = re.findall(r'<span class="sirg-campo vazio"[^>]*>', h)
        self.assertTrue(alheios)
        self.assertFalse(any('role="button"' in s for s in alheios))

    def test_envio_bloqueado_diz_o_motivo_na_tela(self):
        self.entrar("grad")
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        self.assertRegex(h, r'class="sec-card-motivo"[^>]*><i class="bi bi-info-circle"></i> Para enviar: \d+ itens a preencher')
        self.assertIn('aria-describedby="motivo-envio-', h)
        self.assertNotIn("item(ns)", h)

    def test_concluir_reabre_com_reabrir_o_trecho(self):
        self.entrar("grad")
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        self.assertIn("Reabrir o trecho", h)


class EditorChefeTests(Base):
    def test_reabrir_secao_aprovada_no_relatorio(self):
        sec = self.c.secoes.get(chave="ensino_graduacao")
        Secao.objects.filter(pk=sec.pk).update(situacao=Secao.APROVADA)
        self.entrar("master")
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        self.assertIn('name="acao" value="reabrir"', h)
        r = self.client.post(f"/ciclos/{self.c.ano}/secoes/{sec.chave}/acao/", {"acao": "reabrir"})
        self.assertEqual(r.status_code, 302)
        sec.refresh_from_db()
        self.assertNotEqual(sec.situacao, Secao.APROVADA)

    def test_editor_chefe_envia_pelo_setor(self):
        self.entrar("master")
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        self.assertIn("Enviar pelo setor", h)
        self.assertNotIn("Enviar ao Editor-chefe</button>", h)

    def test_nomes_das_telas_iguais_ao_menu(self):
        self.entrar("master")
        self.assertContains(self.client.get(f"/ciclos/{self.c.ano}/"), "<title>SiRG · Quadros de números")
        word = self.client.get(f"/ciclos/{self.c.ano}/exportar/")
        self.assertContains(word, "<title>SiRG · Baixar em Word")
        self.assertContains(word, "mesma diagramação da tela")          # o Word atual, no formato das páginas
        self.assertContains(word, "Pacote para a diagramação")
        self.assertContains(self.client.get(f"/ciclos/{self.c.ano}/pendencias/"), "Conferência dos números (Excel)")


class GraficoAcessivelTests(Base):
    def test_grafico_tem_texto_alternativo_com_os_valores(self):
        from relatorio import graficos
        from relatorio.calculo import Calculadora
        calc = Calculadora(self.c)
        svg = None
        for b in Bloco.objects.filter(secao__ciclo=self.c, tipo=Bloco.GRAFICO, quadro__isnull=False):
            q = calc.quadro_por_id[b.quadro_id]
            svg, _ = graficos.desenhar(calc, q, b.config)
            if svg:
                break
        self.assertIsNotNone(svg)
        self.assertRegex(svg, r'<svg class="grafico-svg" role="img" aria-label="Gráfico: [^"]+\d{4}: ')
        svg2, _ = graficos.desenhar(calc, q, b.config)          # do cache: o rótulo continua
        self.assertEqual(svg, svg2)


class TextosTests(Base):
    def test_qtd(self):
        self.assertEqual(qtd(1, "bloco", "blocos"), "1 bloco")
        self.assertEqual(qtd(0, "bloco", "blocos"), "0 blocos")
        self.assertEqual(qtd(3, "seção", "seções"), "3 seções")

    def test_montagem_sem_plural_entre_parenteses_e_com_relatorio(self):
        self.entrar("admin")
        h = self.client.get(f"/ciclos/{self.c.ano}/montar/").content.decode()
        self.assertNotRegex(h, r"\w\((s|es|ões|ns)\)")
        self.assertIn("Situação e prazo", h)
        self.assertNotIn("Hoje vale o que vem no sistema", h)
        anos = self.client.get("/ciclos/").content.decode()
        self.assertIn("Relatórios (anos)", anos)
        self.assertNotIn("Novo ciclo", anos)
        self.assertIn("Criar o relatório", self.client.get("/ciclos/novo/").content.decode())
