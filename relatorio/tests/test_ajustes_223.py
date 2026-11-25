"""2.23: itens a preencher por setor no Início do Editor-chefe (mesma conta de a_preencher)."""
from contas.models import Setor
from relatorio import pendentes

from .test_documento import Base


class FaltaPorSetorTests(Base):
    def test_por_setor_igual_a_conta_de_cada_setor(self):
        por = pendentes.por_setor(self.c)
        for sg in ("DIRGRAD", "DPPG", "SRCA", "DGDI"):
            self.assertEqual(por.get(sg, 0), pendentes.a_preencher(None, self.c, setor=sg)["total"], sg)
        # o setor vê no Início o mesmo número que o Editor-chefe vê na linha dele
        self.assertEqual(por["DIRGRAD"], pendentes.a_preencher(self.grad, self.c)["total"])

    def test_inicio_do_editor_chefe_tem_a_coluna(self):
        self.entrar("master")
        h = self.client.get("/").content.decode()
        self.assertIn(">A preencher</th>", h)
        n = pendentes.por_setor(self.c)["DIRGRAD"]
        self.assertIn(f'setor=DIRGRAD" title="Ver o que falta para DIRGRAD">{n}</a>', h)
        self.assertTrue(Setor.objects.filter(sigla="DIRGRAD").exists())
