"""2.23: lista de seções com a página do sumário, conferência antes de gravar, título repetido atualiza em vez de
duplicar, e a página prevista usada na importação do PDF."""
from django.urls import reverse

from relatorio import importador as I
from relatorio import montagem as M
from relatorio.models import Pagina, Secao
from relatorio.tests import test_blocos_manuais as TBM
from relatorio.tests.test_montagem import BaseMontagem

SENHA = "Senha-forte-2026"


class LerListaTests(BaseMontagem):
    def test_formas_de_escrever_a_pagina(self):
        lista = ("Apresentação ........ 3\n"
                 "- Mensagem da dirigente | GAB | p. 5\n"
                 "- Sobre o relatório, p. 8\n"
                 "- Expediente\t9\n"
                 "- Dirigentes  10 | GAB\n"
                 "- Metas do PDI para 2026\n"            # o ano faz parte do título: não é página
                 "- Objetivo 4 | DGDI\n"
                 "Visão geral … 12\n"
                 "- Quem somos | SEGEP | pág. 13\n")
        itens = M.ler_lista(self.c, lista)
        got = [(it["titulo"], it["pagina"]) for it in itens]
        self.assertEqual(got, [("Apresentação", 3), ("Mensagem da dirigente", 5), ("Sobre o relatório", 8),
                               ("Expediente", 9), ("Dirigentes", 10), ("Metas do PDI para 2026", None),
                               ("Objetivo 4", None), ("Visão geral", 12), ("Quem somos", 13)])
        self.assertEqual([x.sigla for x in itens[4]["setores"]], ["GAB"])
        self.assertTrue(all(it["acao"] == "criar" for it in itens))
        self.assertFalse(Secao.objects.filter(ciclo=self.c).exists())       # só leu, não gravou

    def test_pagina_fora_de_ordem_avisa(self):
        itens = M.ler_lista(self.c, "Cap | p. 10\n- A | p. 12\n- B | p. 11\n")
        self.assertTrue(any("Confira a ordem" in a for a in itens[2]["avisos"]))

    def test_titulo_que_existe_atualiza_e_nao_duplica(self):
        M.adicionar_em_lote(self.c, "Apresentação\n- Mensagem da dirigente | GAB\n")
        itens = M.ler_lista(self.c, "apresentacao\n- MENSAGEM  da dirigente | GAB | p. 5\n- Nova seção\n")
        self.assertEqual([it["acao"] for it in itens], ["igual", "atualizar", "criar"])
        r = M.adicionar_em_lote(self.c, "apresentacao\n- MENSAGEM  da dirigente | GAB | p. 5\n- Nova seção\n")
        self.assertEqual((r["capitulos"], r["secoes"], r["atualizadas"]), (0, 1, 1))
        self.assertEqual(Secao.objects.filter(ciclo=self.c).count(), 3)
        self.assertEqual(Secao.objects.get(ciclo=self.c, titulo="Mensagem da dirigente").pagina_inicio, 5)
        nova = Secao.objects.get(ciclo=self.c, titulo="Nova seção")
        self.assertEqual(nova.pai.titulo, "Apresentação")

    def test_tela_confere_antes_de_gravar(self):
        self.client.login(username="adm", password=SENHA)
        url = reverse("secoes_lista", args=[2030])
        r = self.client.post(url, {"lista": "Cap ..... 3\n- Seção | DGDI | p. 4", "acao": "conferir"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confira antes de gravar")
        self.assertContains(r, "criar capítulo")
        self.assertContains(r, "p. 4")
        self.assertFalse(Secao.objects.filter(ciclo=self.c).exists())
        r = self.client.post(url, {"lista": "Cap ..... 3\n- Seção | DGDI | p. 4", "acao": "gravar"}, follow=True)
        self.assertContains(r, "1 capítulo criado, 1 seção criada.")
        self.assertEqual(Secao.objects.get(ciclo=self.c, titulo="Seção").pagina_inicio, 4)
        self.assertContains(r, "começa na p. 4")

    def test_paginas_previstas_antes_do_pdf(self):
        self.client.login(username="adm", password=SENHA)
        M.adicionar_em_lote(self.c, "Cap\n- A\n- B")
        a, b = Secao.objects.get(ciclo=self.c, titulo="A"), Secao.objects.get(ciclo=self.c, titulo="B")
        r = self.client.get(reverse("secoes_lista", args=[2030]))
        self.assertContains(r, "Salvar as páginas previstas")
        self.client.post(reverse("secoes_paginas", args=[2030]), {f"inicio_{a.pk}": "4", f"inicio_{b.pk}": "7"})
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.pagina_inicio, b.pagina_inicio), (4, 7))


class PaginaPrevistaNaImportacaoTests(TBM.BlocosManuaisTests):
    """Reaproveita o PDF de 3 páginas e as seções de BlocosManuaisTests (só os testes abaixo rodam aqui)."""

    def test_conferencia_usa_a_pagina_prevista(self):
        Secao.objects.filter(pk=self.pesq.pk).update(pagina_inicio=2)
        linhas = {l["s"].pk: l for l in I.conferencia(self.imp)}
        self.assertEqual(linhas[self.pesq.pk]["pagina"], 2)
        self.assertEqual(linhas[self.pesq.pk]["prevista"], 2)
        if linhas[self.pesq.pk]["achada"] and linhas[self.pesq.pk]["achada"] != 2:
            self.assertTrue(linhas[self.pesq.pk]["difere"])
        r = self.client.get(reverse("importacao_ver", args=[2030, self.imp.pk]))
        self.assertContains(r, "prevista: p. 2")

    def test_lista_com_pagina_depois_de_aplicar_move_as_paginas(self):
        self.aplicar(modo_blocos="sugeridos")
        self.assertEqual(Pagina.objects.get(ciclo=self.c, numero=2).secao, self.grad)
        r = M.adicionar_em_lote(self.c, "1. Visão geral\n- Pesquisa e inovação | p. 2\n")
        self.assertEqual(r["atualizadas"], 1)
        self.assertEqual(Pagina.objects.get(ciclo=self.c, numero=2).secao, self.pesq)

    def test_pagina_impossivel_nao_grava_nada(self):
        self.aplicar()
        n = Secao.objects.filter(ciclo=self.c).count()
        with self.assertRaises(M.Recusado):
            M.adicionar_em_lote(self.c, "1. Visão geral\n- Pesquisa e inovação | p. 9\n- Seção nova\n")
        self.assertEqual(Secao.objects.filter(ciclo=self.c).count(), n)
        self.assertIsNone(Secao.objects.get(pk=self.pesq.pk).pagina_inicio)


# Só os testes desta classe; os herdados já rodam em test_blocos_manuais.
for _nome in [n for n in dir(TBM.BlocosManuaisTests) if n.startswith("test_")]:
    if _nome not in PaginaPrevistaNaImportacaoTests.__dict__:
        setattr(PaginaPrevistaNaImportacaoTests, _nome, None)
