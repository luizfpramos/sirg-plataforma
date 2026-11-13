"""Deixa a plataforma pronta para o Relatório de Gestão 2026.

- Cria o RG 2026 com a estrutura do RG 2025 publicado. Os números de 2021 a 2025 entram
  como histórico (colunas travadas) e os textos de 2025 entram como ponto de partida.
- Não mantém o ciclo 2025 na plataforma: o foco é só 2026. Se uma instalação antiga ainda
  tiver o ciclo 2025 (ou outro anterior), ele é removido depois de um backup automático.

Pode ser executado mais de uma vez: o que já está pronto não é refeito.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from contas.servicos import criar_setores_iniciais
from relatorio.models import Ciclo
from relatorio.servicos import copiar_ciclo

ANO = 2026


class Command(BaseCommand):
    help = "Cria o RG 2026 (com o histórico do RG 2025 publicado) e remove ciclos anteriores."

    def add_arguments(self, parser):
        parser.add_argument("--sem-backup", action="store_true",
                            help="Não faz backup antes de remover ciclos anteriores (uso em testes).")

    def dizer(self, msg):
        if self.verbosidade:
            self.stdout.write(msg)

    def handle(self, *args, **o):
        self.verbosidade = o.get("verbosity", 1)
        from relatorio.dados_iniciais import rg2025
        criar_setores_iniciais()
        antigos = Ciclo.objects.filter(ano__lt=ANO)
        if antigos.exists() and Ciclo.objects.filter(ano=ANO).exists() and not o["sem_backup"]:
            self._backup()
        temporario = None   # ciclo 2025 carregado só para servir de base (não conta como "removido")
        with transaction.atomic():
            if not Ciclo.objects.filter(ano=ANO).exists():
                base = Ciclo.objects.filter(ano=2025).first()
                if base is None:
                    base = rg2025.carregar()
                    temporario = base.pk
                elif not o["sem_backup"]:
                    self._backup()
                novo = copiar_ciclo(base, ANO, f"Relatório de Gestão {ANO}")
                novo.situacao = Ciclo.COLETA
                novo.save(update_fields=["situacao"])
                self.dizer(self.style.SUCCESS(
                    f"{novo.titulo} criado: {novo.secoes.count()} seções e {novo.quadros.count()} quadros. "
                    f"Os números de anos anteriores vieram do RG 2025 publicado e estão travados."))
                self.dizer("Os setores já podem preencher (situação: coleta).")
            else:
                from relatorio.dados_iniciais import rg2026
                self.dizer(f"O Relatório de Gestão {ANO} já existe: o que foi preenchido e escrito fica como está.")
                e = rg2026.sincronizar_estrutura(Ciclo.objects.get(ano=ANO))
                if any(e.values()):
                    self.dizer(f"Atualização da estrutura: {e['quadros']} quadro(s) e {e['linhas']} linha(s) novos, "
                               f"{e['regras']} regra(s) de conferência e gráficos no formato do RG 2025 em "
                               f"{e['secoes_graficos']} seção(ões).")
                if e.get("preservadas"):
                    self.dizer(f"Mantidos como o Master deixou: nome ou fórmula de {len(e['preservadas'])} linha(s).")
                if e.get("secoes_preservadas"):
                    self.dizer(f"Mantidas como o Master deixou: tabelas e gráficos de {len(e['secoes_preservadas'])} "
                               f"seção(ões).")
            from relatorio.dados_iniciais import rg2026
            r = rg2026.ajustar(Ciclo.objects.get(ano=ANO))
            if r["em_numeros"]:
                self.dizer("Seção “em números” (objetivos estratégicos) criada na Apresentação.")
            if r.get("duplicados_tirados", "numeros_ligados"):
                self.dizer(f"{r['duplicados_tirados']} tabela(s) ou gráfico(s) do RG 2025 colados no texto saíram, porque o "
                           f"sistema já monta o mesmo objeto sozinho.")
            if r.get("campos"):
                self.dizer(f"{r['campos']} número(s) do texto viraram campos “xxxxx”, para preencher com o valor de "
                           f"{ANO} clicando no número.")
            if r.get("metas_2026"):
                self.dizer(f"Apêndice: a planilha de metas do PDI de {ANO} ({r['metas_2026']} metas, cada uma da "
                           f"sua unidade líder).")
            pg = r.get("paginas") or {}
            if pg.get("paginas"):
                self.dizer(f"O relatório agora tem as {pg['paginas']} páginas do RG {ANO - 1} publicado, com a mesma "
                           f"diagramação: {pg['caixas']} caixas de texto, {pg['objetos']} gráficos e tabelas no lugar, "
                           f"{pg['campos']} números como xxxxx e {pg['ligados']} ligados às tabelas.")
                if pg.get("antigos"):
                    self.dizer(f"{pg['antigos']} trecho(s) de texto da versão anterior saíram das seções (o histórico "
                               f"fica guardado).")
                if pg.get("antigos_editados"):
                    self.dizer(f"Os {pg['antigos_editados']} trecho(s) que alguém tinha editado estão copiados na pasta "
                               f"de dados (textos_antes_das_paginas_*.json), para consulta.")
            if r.get("paineis"):
                self.dizer(f"{r['paineis']} número(s), texto(s) e gráfico(s) de painéis que no PDF eram imagem passaram "
                           f"a ser editáveis, no mesmo lugar da página.")
            if r.get("numeros_ligados"):
                self.dizer(f"{r['numeros_ligados']} número(s) do texto (ex.: “R$ 570,87 milhões”) passaram a vir dos "
                           f"quadros: aparecem como [a preencher] até o número de {ANO} ser digitado.")
            if r.get("ligacoes_desfeitas"):
                self.dizer(f"{r['ligacoes_desfeitas']} número(s) de norma ou processo (ex.: nº 198/2022) deixaram de "
                           f"estar ligados a quadros por engano.")
            if r.get("mensagem_em_branco"):
                self.dizer("Mensagem da dirigente máxima: o rascunho do ano anterior saiu; o texto começa em branco.")
            if r["nome_trocado"]:
                self.dizer(f"Menções ao CEFET-MG marcadas em amarelo em {r['nome_trocado']} trecho(s) de texto: "
                           f"quem escreve escolhe, em cada uma, CEFET-MG ou {rg2026.SIGLA_NOVA}.")
            if r["destaques_retirados"]:
                self.dizer(f"{r['destaques_retirados']} destaque(s) amarelo(s) que vinham prontos foram retirados "
                           f"(o texto continua igual).")
            if any(v for k, v in r.items() if k not in ("destaques_retirados", "em_numeros", "nome_trocado", "ligacoes_desfeitas", "mensagem_em_branco", "duplicados_tirados", "numeros_ligados", "campos", "metas_2026", "paginas", "paineis")):
                self.dizer(f"Ajustes para 2026: {r['rascunhos']} rascunho(s) de texto a partir do RG 2025, "
                           f"{r['referencias']} texto(s) de referência, "
                           f"{r['metas_pdi']} meta(s) do PDI no apêndice, {r['trechos_novos']} trecho(s) de texto "
                           f"criados, {r['titulos']} título(s) de figura, {r['descricoes']} descrição(ões) de quadro e "
                           f"{r['orientacoes']} orientação(ões) de seção.")
            n = 0
            for c in Ciclo.objects.filter(ano__lt=ANO):
                Ciclo.objects.filter(origem=c).update(origem=None)
                if c.pk != temporario:
                    n += 1
                c.delete()
            if n:
                self.dizer(self.style.SUCCESS(
                    f"{n} ciclo(s) anterior(es) removido(s) da plataforma. O histórico de números continua no "
                    f"RG {ANO}."))

    def _backup(self):
        self.dizer("Fazendo backup antes de alterar os ciclos...")
        try:
            call_command("backup", verbosity=0)
        except Exception as ex:  # pragma: no cover - depende do disco do servidor
            self.dizer(self.style.WARNING(f"Backup não realizado ({ex}). Continuando."))
