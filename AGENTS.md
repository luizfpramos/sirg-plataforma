# SiRG — instruções para agentes de código

As regras do projeto estão em [`CLAUDE.md`](CLAUDE.md) e valem para qualquer agente (Claude, Codex, Copilot etc.). Leia esse arquivo e o [`docs/CONTEXTO_DO_PROJETO.md`](docs/CONTEXTO_DO_PROJETO.md) antes de mudar qualquer coisa.

Para implantar (HML e PRD), veja [`docs/GUIA_RAPIDO.md`](docs/GUIA_RAPIDO.md) e [`docs/GIT_E_IMPLANTACAO.md`](docs/GIT_E_IMPLANTACAO.md).

O mais importante:

- A produção tem usuários reais. Mudanças no banco só com migration, e os passos de conteúdo nunca apagam o que foi editado.
- Nunca leia, imprima nem faça commit de `.env`, `dados/`, `*.sqlite3`, chaves ou senhas.
- Rode `python manage.py test` (sem `--parallel`) antes de abrir um pull request.
- Não altere os ramos `implantar/hml` e `implantar/prd`: são do GitHub Actions.
