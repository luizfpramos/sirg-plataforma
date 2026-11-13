# SiRG — instruções para agentes de código

Leia `docs/CONTEXTO_DO_PROJETO.md` antes de mudar qualquer coisa. Resumo do que não pode falhar:

- **A produção está em uso por usuários reais.** Toda mudança no banco precisa de migration. Passos de conteúdo em `relatorio/dados_iniciais/rg2026.py` (`ajustar()`) rodam uma vez só (marque no `config` do objeto) e nunca apagam nem sobrescrevem o que um usuário editou.
- **Segurança:** nunca leia, imprima ou faça commit de `.env`, `dados/`, `*.sqlite3`, chaves ou senhas. Os dados reais não saem do PC da DGDI.
- **Testes:** `python manage.py test` (sem `--parallel`). Todos precisam passar; o GitHub Actions bloqueia a homologação se algum falhar. Funcionalidade nova vem com teste.
- **Scripts do Windows:** `.bat` e `.ps1` com CRLF (o `.gitattributes` garante), e `.ps1` só com ASCII (o PowerShell 5 lê o arquivo como ANSI).
- **Fechar uma versão:** subir `SIRG_VERSAO` em `config/settings.py`, acrescentar a versão em `VERSOES` (`contas/views.py`) e atualizar o `docs/MANUAL.md` se mudou algo para o usuário. A produção só aceita uma versão que ainda não esteja lá; a tag `vX.Y`, se usada, tem que ser igual a `SIRG_VERSAO`.
- **Fluxo:** ramo de trabalho → pull request → merge na `main` (vai para a homologação em até 5 min) → testar em https://hml-sirg.softwares.net.br → na HML, **Sobre › Enviar para a produção** (ou tag `vX.Y`). Passo a passo em `docs/GUIA_RAPIDO.md`.
- Escreva mensagens de commit, textos de tela e documentação em português.
