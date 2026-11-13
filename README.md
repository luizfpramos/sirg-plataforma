# Plataforma SiRG — Sistema do Relatório de Gestão

Plataforma web em que cada setor preenche os dados e os textos da sua parte do Relatório de Gestão. Tabelas, gráficos e textos saem de **uma única fonte de dados**, e o Word final é gerado pela própria plataforma.

> **Versão 2.14**: painéis que eram imagem no PDF editáveis no lugar (`relatorio/paineis.py`, `paineis_rg2025.json`); Word no formato das páginas (`relatorio/exportar_paginas.py`); gráficos atualizados no lugar.
>
> **Versão 2.13**: o relatório são as páginas do RG 2025 publicado, com a mesma diagramação (fundo de cada página em `static/rg2025/`, caixas de texto em `relatorio/dados_iniciais/paginas_rg2025.json`, gerados do PDF por `ferramentas/paginas_rg2025.py`). Números a atualizar como **xxxxx**; gráficos da plataforma no lugar dos do PDF (`relatorio/paginas.py`, `LUGARES`).
>
> **Versão 2.12**: uma tela só (o relatório igual ao RG 2025, com os números a atualizar como **xxxxx**; tabelas e gráficos preenchidos ao lado do texto, no botão **Dados**); menu único no alto; setores só alteram o texto base, com controle de alterações sempre ligado (o Master aceita); apêndice com a planilha das 41 metas do PDI 2023-2027; paletas editáveis pela diagramação (.ase); ambiente de **homologação** e os instaladores `instalar_hml.bat` / `subir_prd.bat`.
>
> **Versão 2.11**: controle de alterações e comentários como no Word, no Escrever: o que se digita ou apaga fica marcado, com nome e hora, e cada alteração é aceita ou recusada no texto ou no painel de revisão; comentários presos a um trecho, com respostas e resolver. Leitura e Word levam só o que foi aceito.
>
> **Versão 2.10**: correções da auditoria independente de dados e lógica (atualizar preserva os ajustes do Master, total sem soma parcial, divergência impede o envio, regras de mobilidade no ano certo, conferências por grupo de despesa, números em milhões ligados aos quadros).
>
> **Versão 2.9**: correções do diagnóstico de usabilidade (tabelas duplicadas no texto, Tabela 1 visível em Execução orçamentária, prazo e seções paradas para o Master, células inválidas marcadas, aviso de variação, envio só sem pendências, O que falta agrupado, menu recolhido no celular, primeiro acesso mais simples).
>
> **Versão 2.8**: o `atualizar.bat` para o servidor, atualiza e liga de novo sozinho.
>
> **Versão 2.7**: nova tela de entrada (marca UFCIMG à esquerda, formulário à direita) e botão para mostrar a senha.
>
> **Versão 2.6** (segunda rodada do piloto): mensagem da dirigente em branco; correção do Excel; “Terminei” confere de novo e leva ao painel do fim; prévia do gráfico sempre visível na tela de números; gráficos com acabamento de publicação; tela de números mais limpa; planilha **Conferir as conexões** (em O que falta) com todas as ligações entre números e relatório; números de normas não são mais ligados por engano.
>
> **Versão 2.5** acrescenta a **nova identidade visual da UFCIMG**: marca na tela de entrada, no menu e na capa do Word; cores das telas no azul-marinho (#142C46) e verde-água (#67BFB5) da marca; paleta de gráficos “UFCIMG” como padrão; “CEFET-MG” passa a “UFCIMG” nos títulos de seções, quadros e gráficos; nos textos, cada menção ao CEFET-MG fica em amarelo para quem escreve escolher entre CEFET-MG (histórico) e UFCIMG.
>
> **Versão 2.4** (ajustes do piloto) acrescenta:
> - **Preencher os números por setor:** a lista e cada seção mostram só o que é do seu setor; “Quem somos” ficou só com a SEGEP.
> - **Pente fino dos números:** cerca de 25 quadros novos (execução orçamentária, LOA, discricionárias, maiores despesas, investimentos, restos a pagar, receitas, custos, patrimônio, frota, infraestrutura, TI, ouvidoria e LAI, sustentabilidade, CPA, governança e controle), com os valores do RG 2025 e o setor responsável.
> - **Onde o número aparece:** cada quadro diz em que tabela/gráfico e seção ele sai (selo “outra seção”); cada gráfico do Escrever diz de qual quadro e setor vêm os números.
> - **Fim da seção:** barra fixa com a contagem e o painel “Terminei: o que faço agora?” (o que falta, revisar o texto, Enviar ao Master).
> - **Gráficos e tabelas:** barras empilhadas com valores abreviados e total em cima; tabelas com muitos anos abrem na coluna do ano; fotos das obras em cartões.
> - Em instalações já em uso, `atualizar.bat` acrescenta os quadros novos, passa a dotação já digitada para a nova Tabela 1, corrige os setores de “Quem somos” e refaz os textos que ninguém alterou. Nada que foi digitado é apagado.
>
> **Versão 2.3** acrescenta:
> - **Nome novo:** “Centro Federal de Educação Tecnológica de Minas Gerais – CEFET-MG” passa a “Universidade Federal de Ciência e Inovação de Minas Gerais – UFCIMG” nos dados da instituição (capa, telas, Word) e nos textos em que o nome aparece junto com a sigla. Menções históricas ficam como estão.
> - **“UFCIMG em números”:** nova seção da Apresentação com os 14 objetivos estratégicos.
> - **Cores dos gráficos:** quatro paletas padronizadas; o Master escolhe a que vale para todos os gráficos.
> - **`atualizar.bat`:** atualização com dois cliques.
>
> **Versão 2.2** acrescenta:
> - **Interface mais simples:** sem o cabeçalho com logotipos; o botão do usuário fica no alto do menu; o SiRG se identifica na aba do navegador (sigla e símbolo); novo item **Sobre** (desenvolvimento, versão e histórico).
> - **Escrever o relatório:** cada seção da pessoa é um bloco único (cabeçalho ligado ao texto), o texto editável tem cor de destaque permanente, as seções dos outros aparecem como texto corrido e o sumário tem a chave **Só o que eu escrevo**.
> - **Sem destaques prévios:** o texto do RG 2025 vem sem trechos em amarelo (o marca-texto continua disponível). Em instalações já em uso, os destaques que vieram prontos saem e o texto fica igual.
> - **Só números em Preencher os números:** as metas do PDI (status e justificativa) são preenchidas no próprio texto.
> - **Assistente de IA retirado.**
> - **Gráficos no formato do RG 2025:** barras com o valor escrito e a linha de recursos sobre as barras (PET, monitoria, auxílio discente, bolsas, iniciação científica, META, restaurantes, programas de capacitação), pizzas com valor e percentual, e os gráficos que faltavam (extensão por natureza e por categoria, cursos da EDS, PLE, dupla diplomação, docentes em mobilidade, refeições servidas, titulação).
> - **Fonte única com valor digitado:** linhas que vêm de outra tabela mostram o valor automático e aceitam um valor digitado; se forem diferentes, a plataforma aponta e oferece corrigir ou ignorar.
> - **De onde vem o número:** ao passar o mouse ou clicar num número do texto (ou num [a preencher]), aparecem a tabela, o setor e um link para ela.
> - **Imagens no texto** (botão, colar ou arrastar), que vão para o Word e para o pacote da diagramação.
> - **Ctrl+Z / Ctrl+Y** no editor, que funcionam também depois de salvar e de usar as ferramentas.
> - **Filtros** por setor, capítulo, seção, situação, tipo e busca em **O que falta** e **Preencher os números**.
>
> **Versão 2.1 — RG 2026 com base no RG 2025 publicado.** Inclui:
> - **Mesma estrutura do RG 2025:** apresentação (dirigentes, expediente, mensagem, sobre o relatório), os quatro capítulos com seus textos de abertura, as 11 áreas finalísticas como subseções de “Desempenho e resultados” e o apêndice com as metas do PDI por área.
> - **Texto do RG 2025 como ponto de partida:** frases com números, datas e anos destacadas em amarelo para atualizar (com a frase antiga guardada no destaque); números ligados às tabelas de 2026; texto publicado de cada seção para consulta, com link para a página do PDF.
> - **Só o RG 2026 na plataforma:** os números de 2021 a 2025 entram como histórico travado.
> - **Tela inicial em 3 passos**, **gráfico ao lado das tabelas**, **documento editável como no Word**, **leitura do texto final** e **O que falta** em linguagem simples.
> - **Tabelas calculadas** mostram “aguardando dados” enquanto a origem não é preenchida (nunca “ok” com a tabela vazia).
> - **Base:** usuários, setores, perfis, auditoria, backup, exportação para Word (com os destaques em amarelo) e pacote para a diagramadora.

## Homologação e produção (`instalar_hml.bat` e `subir_prd.bat`)

Os dois arquivos ficam na pasta **Relatório de Gestão** (a que contém `producao`), junto com o pacote `sirg-plataforma-vX.Y.zip` (ou com o pacote na pasta Downloads). Eles leem o .zip direto: não é preciso extrair nada. Pedem permissão de administrador ao abrir.

| | Pasta | Porta | Tarefa agendada | Endereço |
|---|---|---|---|---|
| **Homologação (HML)** | `Relatório de Gestão\hml\sirg-plataforma` | 8003 | SiRG - HML | https://hml-sirg.softwares.net.br |
| **Produção (PRD)** | `Relatório de Gestão\producao\sirg-plataforma` | 8001 | SiRG - Servidor | https://sirg.softwares.net.br |

- **`instalar_hml.bat`**: na primeira vez cria a HML com uma cópia do banco e dos arquivos da produção, o `.env` próprio (faixa laranja “HOMOLOGAÇÃO”, cookies separados, backups dentro da pasta da HML) e a tarefa agendada. Nas vezes seguintes atualiza o código e pergunta se deve copiar de novo os dados da produção.
- **`subir_prd.bat`**: avisa se a versão do pacote não é a que está na HML, faz o **backup** do banco, guarda a versão atual em `Relatório de Gestão\versoes_anteriores` (as 3 últimas), para o servidor, atualiza (código, dependências, banco) e liga de novo. Se algo falhar no meio, o servidor é ligado assim mesmo e a mensagem mostra o erro.
- No Cloudflare, o hostname `hml-sirg.softwares.net.br` aponta para `http://127.0.0.1:8003` no mesmo túnel da produção.

## Instalação (Windows)

1. O Python 3.11 ou mais novo precisa estar instalado. O mesmo do SiMED serve.
2. Descompacte a pasta, por exemplo, em `C:\Users\luiz.ramos\Desktop\luiz.ramos\DGDI\sirg-plataforma`.
3. Dê dois cliques em **`instalar.bat`**. O script:
   - cria o ambiente;
   - instala as dependências;
   - cria o banco;
   - cadastra os setores de 2025;
   - prepara o **RG 2026** com a estrutura e o texto do RG 2025 publicado, o histórico de números e a coleta aberta;
   - pede o **login e a senha do administrador**.
4. Abra o arquivo **`.env`** (criado na instalação) no Bloco de Notas e confira o endereço da máquina em `SIRG_ALLOWED_HOSTS`, `SIRG_CSRF_TRUSTED_ORIGINS` e `SIRG_URL_BASE`.
5. Teste com **`servidor.bat`** e acesse `http://200.17.146.126:8001` de outro computador.
6. Para o SiRG iniciar sozinho com o Windows, ter backup duas vezes por dia e ter a porta liberada no firewall, clique com o botão direito em **`agendar_tarefas.bat`** e escolha **Executar como administrador**.

O SiRG usa a **porta 8001** e roda ao lado do SiMED (porta 8000) sem interferir nele.

## Perfis

| Perfil | O que faz |
|---|---|
| **Administrador da plataforma** | Cria usuários e setores, vincula e muda as pessoas de setor, configura a instituição e vê a auditoria |
| **Master** | Edita qualquer parte do relatório e sugere alterações aos setores |
| **Editor** | Quem está vinculado a um setor; edita só o que é de responsabilidade do setor |
| **Leitor** | Quem não tem setor nem perfil; vê o relatório inteiro, sem editar |

Os perfis podem ser combinados, e uma pessoa pode estar em mais de um setor. Quando alguém muda de setor, o vínculo antigo é **encerrado**, não apagado. O histórico mostra em que setor a pessoa estava em cada momento.

## Como funciona o relatório

- **Ciclo:** um relatório por ano-base. A plataforma trabalha com um relatório por vez (hoje, o RG 2026).
  - O próximo ciclo (RG 2027) é criado a partir do atual, em **Administração › Relatórios (anos)**, e copia a estrutura.
  - Nos quadros por ano, os anos passados vêm preenchidos e **travados**. Só o Master os altera, pelo botão “Corrigir anos publicados”, sempre com justificativa.
  - Situações do ciclo:
    - **em preparação:** só administradores e Master;
    - **coleta:** cada setor preenche o que é seu;
    - **revisão:** só o Master;
    - **encerrado:** somente leitura.
- **Seções:** organizadas em capítulos, cada uma com seus setores responsáveis.
- **Quadros de dados:** tabelas configuradas pelo administrador (ícone ⚙ no quadro):
  - **Linhas preenchidas ou calculadas.** Exemplos de fórmula: `atendidos / matriculados * 100` e `ga_matriculados.total`. A segunda busca o dado em outro quadro: é a **fonte única**.
  - **Colunas por ano ou por categoria.**
  - **Regras de consistência.** Exemplo: os ingressantes da pós na Gestão Acadêmica precisam ser iguais aos do painel da Pós.
  - **Alerta de variação** em relação ao ano anterior, com pedido de justificativa.
- **Grade:**
  - salva cada célula ao sair dela;
  - recalcula totais e números de outras áreas na hora;
  - avisa se outra pessoa alterou a mesma célula ao mesmo tempo;
  - aceita colar do Excel;
  - guarda o histórico de cada valor;
  - mostra **ao lado** os gráficos que usam aquele quadro, redesenhados a cada valor salvo.
- **O que falta:** lista o que está **a preencher**, o que está **para corrigir** (regras violadas, fórmulas com problema, valores fora da faixa) e o que está **para conferir** (variação sem justificativa). Só as colunas abertas (2026) entram; anos já publicados não geram pendência.
- **Excel:**
  - baixe os quadros do seu setor;
  - preencha as células amarelas;
  - envie de volta;
  - confira a prévia e grave.

## Texto do relatório

**Escrever o relatório** mostra o relatório inteiro como um documento (folha branca, sumário à esquerda e barra de ferramentas fixa no alto).

- **Edição direta:** a pessoa clica no texto de uma seção que pode alterar e digita. Seções de outros setores aparecem com cadeado.
- **Uma pessoa por vez em cada trecho:** ao clicar, o trecho é reservado; os colegas veem “Fulano está escrevendo aqui agora”. A reserva cai sozinha ao sair do trecho ou depois de 10 minutos sem atividade.
- **Salvamento automático** 1,5 segundo depois que a pessoa para de digitar e ao sair do trecho, com rascunho no navegador contra queda de rede ou energia.
- **Atualização automática:** a cada 20 segundos o documento busca o que os colegas mudaram nos outros trechos.
- **Números vivos:** “Inserir número” liga o número a uma tabela; “[a preencher]” aparece até o dado ser digitado.
- **Tabelas, gráficos e destaques** vêm dos números e não são editados no texto. Na tela da seção, aba **Texto, tabelas e gráficos**, eles são incluídos, movidos e configurados.
- **Master:** modo **Editar** (direto) ou **Sugerir** (o setor aceita ou recusa); aprova e devolve seções no alto de cada seção.
- **Controle de alterações e comentários** como no Word: inserções e remoções marcadas com nome e hora, aceitas ou recusadas uma a uma; comentários presos a um trecho, com respostas.
- **Versões** de cada trecho, com comparação palavra a palavra e volta a uma versão anterior.
- **Orientação por seção:** a frase “O que escrever aqui” (campo da seção) aparece para quem escreve. Textos-modelo de 2026 servem de ponto de partida.

Fluxo da seção:
- **em preenchimento → enviada ao Master → aprovada**, ou **devolvida** com comentário.
- O envio é bloqueado se os números da seção tiverem algo a preencher ou para corrigir.
- Depois de enviada, o setor não altera mais a seção até ela ser devolvida.

**Ler o relatório:** o texto final, somente leitura, para todos, com sumário e impressão.

## Exportação para a diagramação

Menu **Exportar** (ou o botão “Exportar para Word” no Documento):
- **Word (.docx):** capa, sumário automático, capítulos e seções como títulos, textos com os números já preenchidos, tabelas e gráficos numerados com legenda e fonte, números em destaque e paginação. Ao abrir no Word, aceite **atualizar os campos** para montar o sumário.
- **Pacote para a diagramadora (.zip):**
  - o .docx;
  - cada gráfico em PNG (alta resolução) e SVG (vetorial, editável);
  - `graficos/dados-dos-graficos.xlsx`, com os dados de cada gráfico, para refazê-los no estilo do relatório sem redigitar números;
  - `dados/todos-os-quadros.xlsx`;
  - `LEIA-ME.txt`, que avisa se ainda há dados a preencher ou com erro.
- Enquanto o ciclo não está **encerrado**, a capa sai marcada como **VERSÃO PRELIMINAR**.

## Manual de uso

O manual fica em `docs/MANUAL.md` e aparece dentro da plataforma, no menu **Suporte › Manual de uso**. Para ajustá-lo, edite o arquivo e recarregue a página; não é preciso reiniciar o servidor.

## Acesso pela internet (Cloudflare Tunnel)

O computador que roda o SiRG abre uma conexão de saída para a Cloudflare, e o endereço público
(ex.: `https://sigr.softwares.net.br`) chega por ela. Não é preciso abrir porta no firewall nem ter IP fixo.

1. Domínio na Cloudflare (servidores DNS do Registro.br apontando para a Cloudflare).
2. Painel da Cloudflare › **Networking › Tunnels › Create a tunnel** (tipo Cloudflared), nome `sirg`.
   Escolha **Windows**, instale o cloudflared e rode, num Prompt de Comando **como administrador**, o comando
   `cloudflared.exe service install <token>` mostrado no painel. Ele vira um serviço do Windows e sobe junto com o computador.
3. No túnel, aba **Routes › Add route › Published application**: subdomínio `sigr`, domínio `softwares.net.br`,
   **Service URL** `http://127.0.0.1:8001` (use 127.0.0.1, não `localhost`).
4. No `.env` do SiRG:
   ```
   SIRG_DEBUG=0
   SIRG_ALLOWED_HOSTS=localhost,127.0.0.1,200.17.146.126,sigr.softwares.net.br
   SIRG_CSRF_TRUSTED_ORIGINS=https://sigr.softwares.net.br,http://200.17.146.126:8001
   SIRG_URL_BASE=https://sigr.softwares.net.br
   SIRG_HTTPS=1
   SIRG_TUNEL=1
   ```
   Com `SIRG_HTTPS=1`, o login passa a funcionar **só pelo endereço https** (também de dentro da rede).
   `SIRG_TUNEL=1` faz a auditoria registrar o IP real de quem acessa.
5. Reinicie o SiRG (`servidor.bat` ou a tarefa agendada). O computador precisa ficar ligado, sem suspender.

Recomendado: na Cloudflare, ative **SSL/TLS › Edge Certificates › Always Use HTTPS** e, para uma camada a
mais, **Zero Trust › Access** com código por e-mail só para endereços da instituição.

## Segurança

- **Senha provisória** gerada pela plataforma, com troca obrigatória no primeiro acesso. Ninguém, nem o administrador, conhece a senha pessoal.
- **Bloqueio** por 15 minutos após 5 senhas erradas seguidas. O administrador pode desbloquear antes.
- **Trilha de auditoria** de acessos, criação e alteração de usuários, mudanças de setor e configurações. Os registros não podem ser apagados.
- **Restrição por rede (opcional):** `SIRG_REDES_PERMITIDAS` no `.env`.

## Backup

`backup.bat`, ou `python manage.py backup`, copia o banco, os arquivos enviados e a chave secreta para `dados\backups`, ou para a pasta definida em `SIRG_BACKUP_DIR`. São mantidos os 30 mais recentes. **Recomendação:** aponte `SIRG_BACKUP_DIR` para uma pasta de rede ou outro disco.

Para restaurar:
1. Pare o servidor.
2. Copie `sirg.sqlite3` do backup para a pasta `dados`.
3. Inicie de novo.

## Estrutura do código

```
config/        configurações (lidas do .env)
contas/        usuários, setores, perfis, permissões, auditoria e backup
relatorio/     ciclos, seções, quadros, fórmulas, consistência, Excel, texto e gráficos
ia/            assistente de IA (desativado desde a versão 2.2; mantido só para não perder o histórico de uso)
docs/          manual de uso (aparece na plataforma)
  calculo.py     motor de fórmulas (seguro: só aritmética e chaves)
  consistencia.py  relatório de inconsistências
  dados_iniciais/rg2025.py  carga do RG 2025 publicado
  exportar_docx.py  Word e pacote para a diagramação
  permissoes.py  ÚNICO lugar que decide quem pode o quê
  servicos.py    operações com registro na auditoria
templates/     telas gerais (base, login, erros)
static/        estilo e identidade visual
dados/         banco, arquivos enviados e chave secreta (faça backup; não vai no .zip)
```

## Comandos úteis

```bat
.venv\Scripts\activate
python manage.py criar_admin          (cria ou promove um administrador)
python manage.py backup
python manage.py preparar_rg2026        (cria ou ajusta o RG 2026; pode repetir)
python manage.py test                 (testes automáticos)
```
