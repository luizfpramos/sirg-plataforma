"""Carrega o RG 2025 publicado como primeiro ciclo (e, opcionalmente, abre o ciclo 2026)."""
from django.core.management.base import BaseCommand

from contas.servicos import criar_setores_iniciais
from relatorio.consistencia import resumo, verificar
from relatorio.models import Ciclo
from relatorio.servicos import copiar_ciclo


class Command(BaseCommand):
    help = "Cria o ciclo 2025 com a estrutura e os números publicados no RG 2025."

    def add_arguments(self, parser):
        parser.add_argument("--abrir-2026", action="store_true",
                            help="Também cria o ciclo 2026 (em preparação) a partir do 2025.")

    def handle(self, *args, **o):
        from relatorio.dados_iniciais import rg2025
        criar_setores_iniciais()
        if Ciclo.objects.filter(ano=2025).exists():
            self.stdout.write("O ciclo 2025 já existe: nada a fazer.")
            c = Ciclo.objects.get(ano=2025)
        else:
            c = rg2025.carregar()
            r = resumo(verificar(c))
            self.stdout.write(self.style.SUCCESS(
                f"Ciclo 2025 carregado: {c.secoes.count()} seções, {c.quadros.count()} quadros. "
                f"Inconsistências do RG publicado apontadas pelas regras: {r['erros']} erro(s), {r['avisos']} aviso(s)."))
        if o["abrir_2026"]:
            if Ciclo.objects.filter(ano=2026).exists():
                self.stdout.write("O ciclo 2026 já existe: nada a fazer.")
                return
            n = copiar_ciclo(c, 2026, "Relatório de Gestão 2026")
            self.stdout.write(self.style.SUCCESS(f"{n.titulo} criado em preparação (anos anteriores travados)."))
