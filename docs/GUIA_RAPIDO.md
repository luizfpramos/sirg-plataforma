# SiRG — guia rápido: mudar na HML e subir para a PRD

Para quem toca o SiRG sem o Luiz (Wesley, a partir de novembro de 2026). Os detalhes estão em `docs/GIT_E_IMPLANTACAO.md` e `docs/CONTEXTO_DO_PROJETO.md`.

---

## 1. Antes de o Luiz sair (conferir juntos)

| Item | Como conferir |
|---|---|
| Wesley é colaborador do repositório, com permissão de escrita | github.com/luizfpramos/sirg-plataforma › Settings › Collaborators. Wesley precisa conseguir criar ramo e fazer merge. |
| Wesley tem usuário **Master** ou **admin** na PRD | O banco da HML é cópia do da PRD, então o mesmo usuário vale nas duas. Só esses perfis veem o envio para a produção e as instalações em **Sobre**. |
| O implantador do PC está na versão 2.15 | Depois do merge da 2.15, o Luiz roda **uma vez** `instalar_implantador.bat` da pasta `hml\sirg-plataforma`. A chave já está cadastrada: é só dar Enter nas perguntas. Em até 5 min, o **Sobre** da HML passa a mostrar a versão da produção. |
| O botão já foi testado uma vez | O Luiz envia a 2.15 para a produção pelo botão e confere o **Sobre** da PRD. |
| O PC da DGDI fica ligado | Sem suspender nem hibernar. Se possível, configurar a BIOS para religar depois de queda de energia. O SiRG, a HML e o implantador sobem sozinhos quando o Windows inicia. |
| Alguém da DGDI pode ligar ou reiniciar o PC | Deixar combinado quem, porque o Wesley não acessa o PC. |

> **O que só existe no PC da DGDI:** o banco, os backups, o `.env` e os logs (`C:\ProgramData\SiRG\implantador\logs`). Pelo GitHub e pela tela dá para mudar o código, mas não os dados.

---

## 2. Como funciona

```
ramo → pull request → testes (GitHub) → merge na main
   → em até ~20 min a HML se atualiza sozinha        https://hml-sirg.softwares.net.br
   → testar na HML
   → HML › Sobre › "Enviar para a produção"
   → em até 5 min a PRD recebe o mesmo código, com backup antes   https://sirg.softwares.net.br
```

- O PC da DGDI confere o GitHub e o pedido da HML a cada 5 minutos e instala o que mudou.
- A PRD só recebe o código que **está instalado na HML**. Não dá para pular a HML.
- Os ramos `implantar/hml` e `implantar/prd` são do GitHub Actions. **Nunca mexa neles à mão.**

---

## 3. Fazer uma mudança e levar para a HML

```bash
git checkout main && git pull
git checkout -b nome-curto-da-mudanca
#   ... alterar e testar localmente (python manage.py runserver) ...
python manage.py test                 # em série, sem --parallel; todos têm que passar
git add -A && git commit -m "Descrição em português do que mudou"
git push -u origin nome-curto-da-mudanca
```

1. No GitHub, abra o **pull request** para a `main` e espere o check **testes** ficar verde (cerca de 15 min).
2. Faça o **merge**. Uns 15 minutos depois (Action + implantador), a HML está atualizada.
3. Em **Sobre**, na HML, a última instalação tem que ser a do seu merge e aparecer como "instalada".
4. Teste na HML. Lá estão os dados reais copiados da PRD, então não faça nada que avise usuários de verdade.

**Mudou um modelo do banco:** crie a migration (`python manage.py makemigrations`) e faça o commit dela. Sem isso, a Action falha.

**Mudou conteúdo do relatório** (`relatorio/dados_iniciais/rg2026.py`, `ajustar()`): o passo roda uma vez só (marque no `config`) e nunca apaga nem sobrescreve o que um usuário editou.

---

## 4. Levar para a PRD (pelo botão)

1. **Suba a versão** num ramo e faça o merge, como qualquer mudança:
   - `config/settings.py`: `SIRG_VERSAO = "2.16"`;
   - `contas/views.py`: acrescente a 2.16 em `VERSOES`, com o que mudou, em linguagem de usuário;
   - `docs/MANUAL.md`, se mudou algo para o usuário.

   Sem subir a versão, o botão fica desabilitado e explica o motivo.
2. Espere a HML mostrar a 2.16 em **Sobre** e teste.
3. Na HML, em **Sobre › Enviar para a produção**, digite `2.16` e clique em **Enviar a versão 2.16 para a produção**.
4. Em até 5 minutos, o PC faz o backup, guarda a versão anterior e instala. A PRD fica fora do ar por 1 a 2 minutos, então prefira um horário de pouco uso.
5. Recarregue o **Sobre** da HML: a tabela de instalações mostra a linha "produção · por Fulano · instalada". Confira também o **Sobre** da PRD.

> Pela tag `vX.Y` no GitHub também funciona (ver `GIT_E_IMPLANTACAO.md`), mas o botão basta.

---

## 5. Conferir e resolver problemas

| Situação | O que fazer |
|---|---|
| Testes vermelhos no PR | Nada foi instalado. Abra o log da Action, corrija no mesmo ramo e faça push de novo. |
| Merge feito, mas a HML não mudou depois de 30 min | Veja o **Sobre** da HML. Se não há registro novo, o PC pode estar desligado ou sem internet: peça a alguém da DGDI para conferir. |
| **Sobre** mostra "falhou" (HML ou PRD) | O ambiente continua no ar com o código anterior. A mensagem diz em que passo parou. Corrija, faça o merge e tente de novo. |
| Envio para a PRD "recusado" | A mensagem diz o motivo. Por exemplo: a versão já está na PRD, ou a HML mudou entre o clique e a instalação. Resolva e clique de novo. |
| O botão diz que já existe um pedido | O implantador ainda não passou. Espere 5 minutos e recarregue. Se ficar assim por mais de 15 minutos, o PC provavelmente está desligado. |
| Subiu na PRD e quebrou algo | Desfaça pelo Git: `git revert <commit>` num ramo novo → PR → merge → suba a versão (por exemplo, `2.16.1`) → HML → botão. O código volta, e os dados ficam como estão. |
| O site inteiro fora do ar (PRD e HML) | Quase sempre o PC está desligado, sem rede, ou o túnel do Cloudflare caiu. Peça a alguém da DGDI para ligar ou reiniciar o PC: o SiRG sobe sozinho com o Windows. |
| Problema nos dados (algo apagado, banco com erro) | Não se resolve pelo GitHub. Os backups ficam no PC (`producao\sirg-plataforma\dados\backups`) e a restauração precisa de alguém no PC. Anote o que aconteceu e não mexa até resolver. |

---

## 6. Regras que não podem falhar

- **A PRD tem usuários reais.** Tudo passa pela HML antes.
- **Toda mudança no banco vem com migration.** Passos de conteúdo rodam uma vez só e preservam o que foi editado.
- **Nunca** coloque no Git, nem mostre ao Claude: `.env`, `dados/`, `*.sqlite3`, chaves ou senhas. Os dados reais não saem do PC da DGDI.
- Testes: `python manage.py test` (sem `--parallel`). Funcionalidade nova vem com teste.
- `.bat` e `.ps1`: com CRLF, e o `.ps1` só com ASCII (sem acento). A Action confere.
- Commits, textos de tela e documentação em português.
- O Claude Code lê o `CLAUDE.md` (e outros agentes, o `AGENTS.md`) com essas regras. Peça para ele ler também o `docs/CONTEXTO_DO_PROJETO.md` antes de mudar algo.
- **Pausado:** o formulário de preenchimento do RG 2026 (caixas por setor, com cores e limite de caracteres). Nada dele está no repositório.
