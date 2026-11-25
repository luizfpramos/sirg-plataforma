# SiRG — contexto do projeto

Atualizado em 25/11/2026, versão **2.24**. O código fica no GitHub; ver `docs/GIT_E_IMPLANTACAO.md`.

## 1. O que é

**SiRG — Sistema do Relatório de Gestão.** É a plataforma web em que os setores do CEFET-MG (agora **UFCIMG**, Universidade Federal de Ciência e Inovação de Minas Gerais) montam o **Relatório de Gestão 2026**, que será entregue ao TCU.

- **Responsável:** Luiz Fernando Pinheiro Ramos (DGDI). Ele faz parte da comissão do RG 2026 (Portaria 189/2026, em `referencias/`), junto com Henrique Elias Borges (presidente), Brígida Mattos Ornelas (diagramação), Vinícius Lúcio Ferreira e Wesley Ruas Silva.
- **Prazo do relatório:** 31/03/2027.
- **Situação:** um piloto com usuários reais já está em uso. **Os dados e os usuários de produção precisam ser preservados em toda atualização.**

## 2. Stack e estrutura

- **Base:** Django 5.2, SQLite (dados em `dados/`), waitress e django-simple-history (histórico de tudo).
- **Exportação e gráficos:** python-docx (Word), openpyxl (Excel), matplotlib (gráficos SVG/PNG).
- **Front-end:** Bootstrap 5, JS puro e DOMPurify. Não há etapa de build.
- **Apps:**
  - `contas`: usuários, setores, perfis (Editor-chefe, Diagramação, admin), paletas de cores e a tela "Sobre", com a lista `VERSOES` em `contas/views.py`.
  - `relatorio`: ciclos, seções, quadros (tabelas de números), blocos (trechos de texto, gráficos e tabelas), páginas, campos, fluxo, exportações e conferência.
- **Testes:** `python manage.py test` roda 181 testes, todos passando na 2.14. O modo `--parallel` falha por um problema de pickling, então rode os testes em série.
- **Sem acesso a outros sites:** a plataforma não acessa a internet. A IA (`config_ia/`) é opcional.

### Conceitos centrais

- **Ciclo:** um ano de relatório. Hoje existe só o RG 2026; o 2025 entra apenas como histórico.
- **Seção:** capítulo ou subseção, com um ou mais setores responsáveis.
- **Quadro:** tabela de números, com linhas (itens) e colunas (anos). As colunas dos anos anteriores ficam travadas.
- **Bloco:** um trecho de texto, gráfico ou tabela. Desde a 2.13, o bloco pode ter uma `pagina` e uma posição (`config["caixa"]` com x, y, w, h e css).
- **Pagina (2.13):** cada página do RG 2025.
  - O fundo é a imagem da página sem o texto, em `static/rg2025/pNNN.jpg`.
  - As caixas de texto ficam na mesma posição, fonte, tamanho e cor do PDF.
  - O conteúdo foi gerado por `ferramentas/paginas_rg2025.py` (pdfminer + pypdf + pdftoppm) e salvo em `relatorio/dados_iniciais/paginas_rg2025.json`.
- **Números no texto:**
  - `span.sirg-campo` é um número "xxxxx" a preencher. O valor fica no modelo `CampoTexto`.
  - `span.sirg-num data-ref="quadro.linha"` é um número ligado a uma célula de quadro.
- **Controle de alterações (2.11):**
  - As alterações ficam marcadas com `<ins>`/`<del>` (atributos data-u, data-a, data-d, data-s).
  - `revisao.base()` devolve o texto oficial, sem as alterações pendentes.
  - Os comentários ficam ancorados no trecho.
- **Regras para os setores (2.12):**
  - Só editam o texto base, sempre com rastreio.
  - O servidor recusa o salvamento se `texto_base` mudar.
  - Não criam trechos novos nem inserem imagens.
  - Só o Editor-chefe aceita ou recusa alterações.
- **Painéis (2.14):** números e textos que no PDF eram imagem ganharam caixas editáveis por cima, definidas em `relatorio/paineis.py` e `dados_iniciais/paineis_rg2025.json`.
- **Gráficos no lugar:** `relatorio/paginas.py` tem o dicionário `LUGARES`, com seção, título, página e área de cada gráfico, conferido página a página.
- **Word (2.14):** `relatorio/exportar_paginas.py` gera páginas do tamanho do RG (935,4 × 566,9 pt). O fundo é uma imagem ancorada e os textos, gráficos e tabelas viram caixas de texto do Word (wps).
- **Apêndice:** a planilha das 41 metas do PDI (quadro `pdi_metas`). Cada linha tem setor próprio (`Linha.setor`; GDG → GAB). O Editor-chefe baixa a planilha preenchida no modelo original.
- **Preparação idempotente:** `python manage.py preparar_rg2026` prepara o banco e pode ser rodado várias vezes. Cada passo de migração de conteúdo roda uma vez só e preserva o que foi editado. Os passos estão em `relatorio/dados_iniciais/rg2026.py` (`ajustar()`).

### Telas principais

- **Relatório** (`/ciclos/2026/escrever/`): é a tela única, com as páginas do RG 2025.
  - Clicar no xxxxx abre o popover de preenchimento.
  - O botão "Dados" (ou clicar no gráfico) abre a gaveta com a tabela.
  - O botão "Faltam N" leva ao próximo item a preencher.
  - Cada seção tem uma faixa com situação e "Enviar ao Editor-chefe".
- **Ver como fica** (`/ler/`): a leitura limpa, que também pode ser impressa.
- **O que falta** (`/pendencias/`).
- **Quadros de números:** só para o Editor-chefe.
- **Cores dos gráficos:** Editor-chefe e diagramação.
- **Menu:** um único menu no alto (não há barra lateral).

## 3. Ambientes e implantação (Windows, PC do Luiz)

| | Pasta | Porta | Tarefa agendada | Endereço (túnel Cloudflare) |
|---|---|---|---|---|
| PRD | `...\Relatório de Gestão\producao\sirg-plataforma` | 8001 | SiRG - Servidor | https://sirg.softwares.net.br |
| HML | `...\Relatório de Gestão\hml\sirg-plataforma` | **8003** (a 8002 está ocupada por outro programa) | SiRG - HML | https://hml-sirg.softwares.net.br |

- **`instalar_hml.bat` e `subir_prd.bat`:** ficam na pasta "Relatório de Gestão". Eles acham o zip `sirg-plataforma-vX.Y.zip` mais novo nessa pasta ou em Downloads, extraem para `%TEMP%` e rodam `implantacao/implantar.ps1`.
- **HML:** copia o banco da produção na primeira vez e depois pergunta se deve copiar de novo. Tem `.env` próprio (`SIRG_AMBIENTE=hml`, com faixa laranja e cookies separados).
- **PRD:** faz backup, guarda a versão anterior em `versoes_anteriores` (mantém 3), atualiza e religa o servidor mesmo se houver erro.
- **Hostname da HML:** usa um nível só (`hml-sirg`). Com dois níveis (`hml.sirg`) o certificado gratuito do Cloudflare não cobre e dá `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`.
- **Cuidados com os scripts:**
  - PowerShell só em ASCII (o PS 5.1 lê o arquivo como ANSI).
  - `.bat` e `.ps1` sempre com quebra de linha CRLF.
  - O script só para processos que sejam o `servir.py` do SiRG; nunca outro programa que esteja usando a porta.
- **Empacotamento:** o zip tem a pasta `sirg-plataforma/` na raiz. Ficam de fora `dados/`, `.env`, `.venv`, `staticfiles`, `__pycache__` e `*.pyc`.

### Implantação pelo Git (desde a 2.14.1)

- O código fica num repositório privado no GitHub. O PC da DGDI continua sendo o único servidor.
- O GitHub Actions (`.github/workflows/testes-e-implantacao.yml`) roda os testes:
  - push na `main` atualiza o ramo `implantar/hml`;
  - tag `vX.Y` atualiza `implantar/prd`. A tag precisa bater com `SIRG_VERSAO` e o commit precisa já ter passado pela `main`.
- No PC, a tarefa "SiRG - Implantador" (`C:\ProgramData\SiRG\implantador`, a cada 5 min, conta SYSTEM) lê esses ramos com uma deploy key só de leitura e roda `implantacao/implantar.ps1 -Automatico`.
- A produção só recebe código que já foi instalado na homologação.
- O resultado de cada instalação vai para `dados/implantacao.json` e aparece na tela Sobre para o Editor-chefe e o administrador.
- Os `.bat` manuais continuam funcionando como plano B.

## 4. Histórico recente (resumo)

- **2.10:** correções da auditoria.
- **2.11:** controle de alterações e comentários no estilo Word, inspirado na plataforma CPA (em `referencias/`).
- **2.12:** atendeu ao pedido do Luiz e do Wesley.
  - Uma tela única no lugar de Preencher, Escrever e Ler, sem barra lateral e com menos texto na tela.
  - Números a atualizar viram xxxxx.
  - Os setores só editam o texto base, com rastreio.
  - O apêndice passou a ser a planilha de metas do PDI.
  - Paletas de cores editáveis pela diagramação (importação .ase/.gpl).
  - Ambiente HML e os dois .bat de instalação.
- **2.13:** o relatório passou a ser **as páginas do RG 2025 com a mesma diagramação**: fundo do PDF, caixas de texto posicionadas e gráficos da plataforma no lugar dos gráficos do PDF.
- **2.14:**
  - Correção do gráfico que "se desmanchava" ao salvar os dados.
  - Painéis que eram imagem no PDF ficaram editáveis: Ouvidoria e seus rankings, LAI, PGEN, riscos, integridade, despesas de investimento, custos e SWOT.
  - Word no formato das páginas.
  - Teste completo preenchendo tudo pela tela, como Editor-chefe e como setor, com as correções que ele revelou.

## 4b. Montagem do relatório do ano (2.18)

- **Montar o relatório** (`relatorio/montagem.py`, `views_montagem.py`): passos, seções (lista colada), quadros simples, PDF do relatório anterior (`MEDIA_ROOT/referencia/anterior_ciclo_<pk>.pdf`), ciclo de trabalho (`Ciclo.em_trabalho`; sem marca, vale o de ano mais alto) e excluir ciclo só onde `SIRG_PERMITE_EXCLUIR_CICLO` (padrão: HML).
- **`Ciclo.automatico`:** só o RG 2026 montado a partir do RG 2025. `preparar_rg2026` só mexe nele; não recria um RG 2026 excluído e não apaga ciclos montados pela tela.
- **Importação:** conferência seção → página inicial (`importador.conferencia`, escolhas em `ImportacaoPDF.resumo["inicios"]`, usadas também na reimportação). `conteudo_da_caixa`: parágrafo → bloco vazio com `config["referencia_pdf"]` e mínimo/máximo sugeridos; título, texto curto (< 40 caracteres, `config["rotulo"]`, com `numero_antigo` se tem número) e `Secao.conteudo_fixo` → `config["fixo"]` (só o Editor-chefe altera). No RG 2026 automático, como antes (texto com xxxxx).
- **`Ciclo.exibicao_vazio`:** como o bloco vazio aparece na tela (nada, orientação, lorem, xxx); só exibição.
- **Envio:** `fluxo.blocos_vazios_da_secao` bloqueia o envio com bloco vazio (fora do RG 2026 automático).

## 4c. Grade e guias de diagramação (2.20)

- **`Ciclo.grade`** (JSON, em pt): margens, colunas e medianiz, editados em Padrão de design (`contas/views.py`, `_salvar_grade`). Vazio: sem grade.
- **`Pagina.guias`** (JSON, `{"v": [...], "h": [...]}` em pt): guias só daquela página, para as exceções. Somam-se à grade.
- **`relatorio/grade.py`:** conferência dos valores, linhas da grade, `fora_da_grade` (bordas esquerda e direita numa linha; dentro das margens de cima e de baixo ou numa guia horizontal da página) e a lista de páginas para copiar ("3, 5-8", "todas").
- **Editor:** ações `guias` e `copiar_guias`; cada bloco traz `fora`. O encaixe é só na tela (JS, tolerância de 6 px na tela); nada move blocos sozinho.

## 4d. Usabilidade e acessibilidade (2.22)

- **Conta única do que falta:** `relatorio/pendentes.py`. `a_preencher(user, ciclo, ...)` soma as pendências "falta" (tabelas e metas do PDI), os xxxxx (`campos_vazios_da_secao`) e os blocos vazios. Escopo: setores da pessoa; Editor-chefe e quem não tem setor veem o relatório inteiro. Usada no Início, no Relatório (e na recontagem ao vivo, `_faltam`), em O que falta, em Quadros de números e em Baixar em Word. Não crie outra conta numa tela nova: use esta.
- **`secoes_do_fluxo(ciclo)`:** subseções e capítulos com blocos ou quadros. É a base de "seções enviadas/aprovadas" no Início, no Ler e no Word.
- **Relatório:** o que é de outro setor fica em cinza (CSS em `#doc-corpo`); motivo do envio bloqueado escrito (`.sec-card-motivo`); Reabrir na faixa; "Enviar pelo setor" para o Editor-chefe.
- **Acessibilidade:** `graficos.descricao()` vira `aria-label` do SVG; xxxxx e números de tabela editáveis com `role="button"`; textos de tela sem "(s)": use `formato.qtd()` no Python e `pluralize` nos modelos.
- Avaliação completa: documento do Projeto `claude/revisao-usabilidade-2026-11-25.md`.

## 4e. Seções com página (2.23)

- **`Secao.pagina_inicio`** (migration 0016): a página prevista no PDF diagramado. `importador.conferencia` usa: escolha gravada → página prevista → página achada; marca `difere`. A reimportação usa a prevista para seções novas.
- **`montagem.ler_lista`** lê a lista sem gravar (prévia na tela); **`adicionar_em_lote`** grava e devolve um dicionário. Título igual (sem acento e caixa) atualiza setores e página. Página: `| p. 51`, `| 51`, `Título ...... 51`, `Título<Tab>51`, `Título, p. 51`, `Título  51` (dois espaços); um espaço só não conta. Com o PDF aplicado, chama `mudar_inicios` na mesma transação.
- **`pendentes.por_setor`**: os itens a preencher de cada setor numa passada (coluna do Início do Editor-chefe).

## 4f. Fundo da página e texto do PDF no editor (2.24)

- **Texto do PDF no editor:** `.ed-pdf-txt` segue as regras de `.pg .pg-texto` (p sem margem, `hyphens: manual`, `font-kerning: none`, sup a 0,6 em). Caixa com `quebra` (cada linha do PDF é um `<p>`) recebe a classe `q` e fica `nowrap`, no texto do PDF e no bloco do editor (`serializar` traz `quebra`). Antes, a margem do `<p>` do Bootstrap (1rem) somava-se a cada linha.
- **`Pagina.ajustes_fundo`** (migration 0017): lista de `{"tipo": "apagar"|"manter", x, y, w, h}` em pt, aplicada na ordem por `relatorio/fundo.py`. `apagar` cobre com a cor mais comum logo fora da área; `manter` cola a mesma área da página original renderizada com texto (`fundo.pdf_original`: `importacoes/<id>/original.pdf` ou `static/referencia/RG2025.pdf`).
- **Imagem ajustada:** `MEDIA_ROOT/fundos/<pk>-<assinatura>.jpg`, gerada no primeiro pedido (`fundo_ajustado`, `arquivos/fundos/<pk>/<assinatura>.jpg`). A assinatura junta fundo, tamanho e ajustes; muda a cada alteração e apaga as versões antigas. `Pagina.fundo_url` e `fundo_caminho` já devolvem a ajustada (Relatório, Ler, Word).
- **Texto mantido no fundo:** `textos_pdf.caixas_da_pagina` deixa de fora as caixas com o centro numa área `manter`. Ação do editor: `fundo` (lista inteira). A cópia do ciclo (`servicos.copiar_ciclo`) leva os ajustes.

## 5. Limitações conhecidas e próximos passos possíveis

- **Fundo das páginas:** fotos, ícones, o logo do CEFET-MG na capa e os organogramas fazem parte da imagem de fundo. Desde a 2.24 dá para apagar áreas e manter o texto do PDF no fundo (botão Fundo do editor), mas não trocar uma imagem por outra. A troca de marca para UFCIMG (arquivos em `referencias/`) ainda não foi aplicada nas imagens das páginas.
- **Fontes:** a plataforma usa Carlito, que tem as mesmas medidas da Calibri. Os textos pequenos dos painéis usam uma fonte parecida com a original, não idêntica. Alguns parágrafos de letra muito pequena (p. 19–23) podem quebrar diferente do PDF.
- **Números históricos:** alguns números do texto que se referem a anos anteriores também viraram xxxxx. O botão "Manter" resolve.
- **Anos no texto:** expressões como "Em 2025, foram…" não mudam sozinhas.
- **Word:** usa caixas de texto sobre a imagem da página. Serve para conferir e fazer ajustes pontuais, mas não é confortável para reescrever trechos longos.
- **Gráfico 5 (frota):** o RG 2025 não trouxe os anos anteriores, então o gráfico fica com uma barra só.
- **Conferência ponto a ponto:** Luiz e Vinícius ainda precisam conferir uma a uma as ligações entre números do texto e tabelas.
- **Feedback de usabilidade:** a avaliação heurística (09/11) e as sugestões do Wesley (23/10) estão em `feedback/`. Parte foi atendida na 2.12–2.14; vale revisar o que falta.

## 6. Regras de segurança (manter)

- Nunca abrir, imprimir nem pedir o `.env` de produção, a pasta `dados/` (banco, chave secreta) ou a `.venv`.
- Zips entregues nunca levam `dados/`, `.env`, `.venv`, `__pycache__` nem `staticfiles`.
- O token do túnel cloudflared nunca deve ser compartilhado.
- Não colocar senhas de usuários reais em prompts. Usuários de teste devem ser apagados ou ter a senha trocada depois dos testes.

## 7. Ambiente de desenvolvimento usado até aqui (para reproduzir)

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
export SIRG_DADOS_DIR=$PWD/dados
python manage.py migrate
python manage.py inicializar
python manage.py preparar_rg2026 --sem-backup
python manage.py createsuperuser   # ou crie usuários pelo admin
python servir.py   # ou: python manage.py runserver 8001
```

- **Usuários de teste usados no desenvolvimento:** mara.master (Editor-chefe), ana.dirgrad (setor DIRGRAD), carlos.dpg, paulo.dppg e luiz.ramos. Eles foram criados à mão no ambiente de desenvolvimento e não existem no zip.
- **Testes de navegador:** foram feitos com Playwright (Chromium).
- **Regenerar as páginas a partir do PDF** (só se o PDF de referência mudar): `python3 ferramentas/paginas_rg2025.py static/referencia/RG2025.pdf`. Precisa de pdfminer.six, pypdf, fontTools e poppler-utils, além das fontes Carlito e Liberation instaladas.
