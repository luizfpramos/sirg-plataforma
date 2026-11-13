# Git e implantação do SiRG

O código do SiRG fica num repositório privado no GitHub. O SiRG continua rodando só no PC da DGDI, no CEFET-MG. Nesse PC, um **implantador automático** busca o código no GitHub e instala sozinho:

| Quando | O que acontece | Onde aparece |
|---|---|---|
| Código entra na `main` e os testes passam | A **homologação** é atualizada em até 5 min | https://hml-sirg.softwares.net.br |
| Na homologação, o Master ou o admin clica em **Sobre › Enviar para a produção** (2.15) | A **produção** recebe exatamente o código da homologação em até 5 min, com backup antes | https://sirg.softwares.net.br |
| Ou: uma tag `vX.Y` é criada e os testes passam | A **produção** é atualizada em até 5 min, com backup antes | https://sirg.softwares.net.br |

- Ninguém precisa acessar o PC da DGDI. O PC só **lê** o GitHub, com uma chave só de leitura.
- Os dados (banco, arquivos enviados, `.env`) nunca vão para o GitHub.
- A produção só recebe código que já passou pela homologação.
- O resultado de cada instalação aparece em **Sobre** (para o Master e o administrador) e no log do PC (`C:\ProgramData\SiRG\implantador\logs`).

---

## Parte 1 — Luiz: preparar (uma vez só)

### 1. Criar o repositório no GitHub
1. Entre em https://github.com (crie uma conta, se ainda não tiver) e clique em **New repository**.
2. Nome: `sirg-plataforma`. Marque **Private**. **Não** marque README, .gitignore nem licença: o repositório tem que começar vazio. Clique em **Create repository**.
3. Em **Settings › Collaborators**, clique em **Add people** e convide o Wesley com a conta dele no GitHub.

### 2. Enviar o código
1. Instale o **Git for Windows** (https://git-scm.com/download/win) com as opções padrão.
2. Extraia o `sirg-repositorio-inicial.zip` numa pasta de trabalho, por exemplo `C:\Users\luiz.ramos\Documents\sirg-plataforma`. **Não** use a pasta da produção.
3. Nessa pasta, clique com o botão direito, escolha **Open Git Bash here** e rode, trocando `USUARIO` pelo seu usuário do GitHub:
   ```
   git remote add origin https://github.com/USUARIO/sirg-plataforma.git
   git push -u origin main
   ```
   Na primeira vez, o Git abre uma janela para entrar no GitHub.
4. No GitHub, a aba **Actions** mostra os testes rodando (cerca de 15 min). No fim aparece o ramo `implantar/hml`.

### 3. Subir a 2.14.1 do jeito de sempre
Antes de ligar o implantador, instale esta versão pelo caminho manual: `sirg-plataforma-v2.14.1.zip` → `instalar_hml.bat` → testar → `subir_prd.bat`. Isso garante que a homologação e a produção estão com o mesmo código que agora está no GitHub.

### 4. Instalar o implantador
1. Na pasta da produção (`Relatório de Gestão\producao\sirg-plataforma`), clique duas vezes em **`instalar_implantador.bat`** e aceite o pedido de administrador.
2. Quando ele pedir, informe o endereço **SSH** do repositório: no GitHub, botão **Code › SSH**, algo como `git@github.com:USUARIO/sirg-plataforma.git`.
3. Ele mostra uma linha que começa com `ssh-ed25519 …`. No GitHub, abra **Settings › Deploy keys › Add deploy key** e cadastre:
   - **Title:** `SiRG implantador (PC da DGDI)`;
   - **Key:** a linha;
   - **não marque** "Allow write access".

   Depois volte à janela e aperte Enter.
4. Quando ele perguntar se a homologação e a produção já estão com o código atual, responda **S**. Como você instalou a 2.14.1 no passo 3, nada é reinstalado agora.
5. Pronto: a tarefa **SiRG - Implantador** passa a rodar a cada 5 minutos.

**Pausar:** Agendador de Tarefas › SiRG - Implantador › Desabilitar.
**Plano B:** os `instalar_hml.bat` e `subir_prd.bat` continuam funcionando com um zip, como antes.

### 5. (Recomendado) Proteger a `main`
Em repositório privado, essa opção depende do plano do GitHub (Pro, Team ou o plano de educação da instituição). Se não aparecer, combinem de sempre usar pull request.

Em **Settings › Branches › Add branch ruleset**, crie uma regra para `main` com **Require a pull request before merging** e **Require status checks to pass** (marque "testes"). Assim nada entra na homologação sem passar pelos testes e por um pull request.

---

## Parte 2 — Wesley: trabalhar no SiRG

### Montar o ambiente (uma vez)
Instale o Python 3.12 e o Git. Depois:
```
git clone https://github.com/USUARIO/sirg-plataforma.git
cd sirg-plataforma
python -m venv .venv
.venv\Scripts\activate            (no Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py inicializar
python manage.py preparar_rg2026 --sem-backup
python manage.py createsuperuser
python manage.py runserver
```
Abra http://127.0.0.1:8000. O banco local é **só de teste**: tem a estrutura e os textos do RG 2025, mas nenhum dado real.

### Fazer uma alteração
```
git checkout main && git pull
git checkout -b ajuste-grafico-ouvidoria        (um nome curto para o que vai fazer)
... edita, testa ...
python manage.py test
git add -A && git commit -m "Ouvidoria: gráfico de manifestações com a cor da paleta"
git push -u origin ajuste-grafico-ouvidoria
```
No GitHub, abra um **pull request** para a `main`. Os testes rodam sozinhos. Com tudo verde, faça o merge. **Em até 5 minutos a homologação está atualizada.** Confira em https://hml-sirg.softwares.net.br (o código instalado aparece em Sobre).

Se usar o Claude Code, ele lê o `CLAUDE.md` do repositório com as regras do projeto.

### Levar para a produção
**Caminho principal (2.15): pelo botão na homologação.**
1. Num ramo, suba a versão (`SIRG_VERSAO` em `config/settings.py` e `VERSOES` em `contas/views.py`) e faça o merge, como qualquer alteração.
2. Espere a homologação mostrar a versão nova em **Sobre** e teste.
3. Na homologação, em **Sobre › Enviar para a produção**, digite a versão e clique no botão. Em até 5 minutos o PC instala na produção o mesmo código, com backup antes. O resultado aparece na mesma tela.

O implantador recusa o pedido se o código não for o que está instalado na homologação ou se a versão já estiver na produção.

**Caminho alternativo: pela tag.**
1. Na `main`, suba a versão em `config/settings.py` (`SIRG_VERSAO = "2.15"`) e acrescente o que mudou em `VERSOES`, em `contas/views.py`. Faça o merge disso como qualquer alteração (passa pela homologação).
2. Crie a tag: no GitHub, **Releases › Draft a new release › Choose a tag › `v2.15`**, com alvo `main`, e clique em **Publish**. Pelo terminal:
   ```
   git checkout main && git pull
   git tag v2.15 && git push origin v2.15
   ```
3. O GitHub confere que a tag bate com `SIRG_VERSAO` e que o código já passou pela homologação. Em até 5 minutos o PC da DGDI faz o backup, guarda a versão anterior e atualiza a produção. O resultado aparece em **Sobre** na produção.

### Se algo der errado
- **Testes falharam no GitHub:** nada é instalado. Corrija no mesmo ramo e envie de novo.
- **A instalação falhou no PC:** a tela Sobre (e o log no PC) mostra o erro. O ambiente continua no ar com o código anterior. Corrija e envie de novo; o implantador tenta outra vez quando houver código novo.
- **Voltar a produção para uma versão anterior:** crie uma nova versão com a correção. Em caso de urgência, o Luiz usa o `subir_prd.bat` com o zip da versão anterior; as últimas 3 versões ficam em `Relatório de Gestão\versoes_anteriores`.
- **Dados da homologação:** o implantador nunca copia os dados da produção para a homologação sozinho. Para atualizar a cópia, o Luiz roda o `instalar_hml.bat` e responde **S**.
