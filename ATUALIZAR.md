# Como atualizar uma instalação existente

> **A plataforma já está em uso (usuários e dados reais)?** Siga os passos abaixo: nada do que foi preenchido ou escrito se perde.
> Instalação nova só se não houver dados reais: apague a pasta antiga, descompacte o .zip numa pasta nova e dê dois cliques em `instalar.bat`.

## Desde a versão 2.12: `instalar_hml.bat` e `subir_prd.bat` (sem extrair o .zip)

1. Copie `instalar_hml.bat` e `subir_prd.bat` para a pasta **Relatório de Gestão** (a que tem a pasta `producao`). Isso só precisa ser feito uma vez.
2. Deixe o `sirg-plataforma-vX.Y.zip` nessa mesma pasta (ou na pasta Downloads). **Não extraia.**
3. **Dois cliques em `instalar_hml.bat`**: cria ou atualiza a homologação em `hml\sirg-plataforma` (porta 8003), com uma cópia dos dados da produção. Teste em https://hml-sirg.softwares.net.br.
4. **Dois cliques em `subir_prd.bat`**: backup do banco, cópia da versão atual em `versoes_anteriores`, atualização e servidor ligado de novo.
5. Abra o site e aperte **Ctrl+F5**. A versão aparece em **Sobre**.

O jeito antigo (abaixo) continua funcionando.

## Atualizar à mão (`atualizar.bat`)

Os seus dados ficam na pasta `dados` e as configurações no arquivo `.env`. **Não apague nenhum dos dois.**

**Desde a versão 2.8, o `atualizar.bat` para o servidor, atualiza e liga de novo sozinho.** Ele pede permissão de administrador ao abrir (é preciso para parar a tarefa agendada). Basta:

1. **Faça um backup** (opcional): dois cliques em `backup.bat`.
2. **Copie o conteúdo da pasta `sirg-plataforma` do .zip para dentro da pasta atual**, substituindo os arquivos. A pasta `dados` e o arquivo `.env` não vêm no .zip. Não pode ficar uma `sirg-plataforma` dentro de outra.
3. **Dê dois cliques em `atualizar.bat`** e aceite o pedido de administrador. Ele mostra três etapas: parando o servidor, atualizando, ligando o servidor de novo.
4. Abra o site e aperte **Ctrl+F5**. A versão aparece em **Sobre**.

Se preferir fazer à mão (ou numa versão anterior à 2.8): pare o servidor, **abra o PowerShell na pasta da plataforma** e rode:

   ```
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe manage.py migrate
   .\.venv\Scripts\python.exe manage.py inicializar
   .\.venv\Scripts\python.exe manage.py collectstatic --noinput
   .\.venv\Scripts\python.exe manage.py preparar_rg2026
   ```

   O último comando deixa a plataforma focada no RG 2026 e traz as novidades da versão:
   - se o RG 2026 ainda não existir, ele é criado com o histórico do RG 2025 publicado;
   - o ciclo 2025, se ainda estiver na plataforma, é removido (antes, é feito um backup automático). Os números de 2021 a 2025 continuam no RG 2026, como anos travados;
   - cada seção recebe o texto do RG 2025 publicado, com os trechos a atualizar em amarelo, o texto de 2025 para consulta e uma orientação do que escrever. Textos que alguém já editou não são trocados;
   - o relatório passa a ser as páginas do RG 2025 publicado (versão 2.13, uma vez): cada caixa de texto da página vira um trecho, os gráficos ficam no lugar. Os trechos de texto da versão anterior saem das seções; os que alguém tinha editado ficam guardados em `dados\textos_antes_das_paginas_*.json` e no histórico;
   - o apêndice recebe a planilha das 41 metas do PDI 2023-2027 (versão 2.12; as tabelas antigas por área saem se ninguém as preencheu);
   - os números do texto que mudam de um ano para o outro viram campos **xxxxx** (versão 2.12, uma vez por trecho);
   - **numa instalação que já está em uso**, o RG 2026 recebe os quadros, linhas e gráficos novos (com o histórico publicado) e os gráficos passam ao formato do RG 2025. Os destaques amarelos que vieram prontos na versão 2.1 saem; o texto continua igual. Textos que ninguém editou ainda são refeitos com os gráficos no meio, como no RG.

   Ele pode ser executado de novo sem problema: o que já está pronto não é refeito, e nada que alguém escreveu é apagado.

Depois, inicie de novo com o `servidor.bat`, ou com `schtasks /Run /TN "SiRG - Servidor"`.
