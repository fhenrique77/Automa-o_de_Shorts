# 🎬 Podcast Automation Bot (Multi-Platform Reels/Shorts)

Este é um sistema robusto e modular de automação para curadoria, edição e publicação automática de cortes de vídeo curtinho (Shorts/Reels/TikToks) a partir de canais de podcast do YouTube.

O bot realiza o download dos episódios, utiliza **Inteligência Artificial (Google Gemini)** para selecionar o trecho com maior potencial de viralização, corta e renderiza o vídeo em formato vertical (9:16) usando **FFmpeg**, e publica de forma automática em quatro redes sociais simultaneamente usando **Playwright**.

---

## 🚀 Funcionalidades Principais

*   **Curadoria Inteligente por IA:** Integração direta com a API do Google Gemini para analisar a transcrição do vídeo e extrair o trecho mais impactante e viral (ou seleção manual de tempos).
*   **Processamento de Vídeo Vertical:** Redimensionamento inteligente e corte automático no formato vertical ($1080 \times 1920$ px) em alta qualidade e otimizado por hardware via FFmpeg.
*   **Distribuição Multi-plataforma:**
    *   **YouTube Shorts**
    *   **TikTok**
    *   **Instagram Reels**
    *   **Facebook Reels**
*   **Upload via Navegador Automatizado (Playwright):** Evita restrições e custos das APIs oficiais das redes de anúncios simulando interações humanas reais de forma otimizada.
*   **Persistência de Sessão:** Gerenciamento independente de cookies e diretórios de perfil (`browser_data_...`) para cada plataforma social, garantindo que você só precise fazer login manualmente uma única vez.
*   **Agendamento Automatizado integrado:** Scripts utilitários para configurar tarefas agendadas no Windows executando o bot silenciosamente nos melhores horários de audiência (3 vezes ao dia).
*   **Fila e prevenção de duplicidade:** Banco SQLite local (`publicacoes.sqlite3`) com resultado por clipe e plataforma, retomada de pendências e importação do antigo `historico.json`.

---

## 📁 Estrutura do Projeto

*   `main.py`: Ponto de entrada do sistema. Gerencia o fluxo de download, curadoria, corte e enfileiramento dos uploads.
*   `config.py`: Centraliza todas as configurações globais do bot (limites de clipes, caminhos, hashtags estratégicas, chaves de API, resoluções de renderização).
*   `cutter.py`: Responsável por baixar o vídeo fonte (via `yt-dlp`), obter transcrições, acionar a IA (Gemini/Whisper), e renderizar o vídeo final usando comandos FFmpeg estruturados.
*   `utils.py`: Funções utilitárias compartilhadas, como filtragem de vídeos históricos e montagem de títulos/descrições/hashtags formatadas respeitando os limites de caracteres de cada plataforma.
*   `uploader.py`: Módulo base e específico para upload no YouTube Studio.
*   `tiktok_uploader.py`, `instagram_uploader.py`, `facebook_uploader.py`: Scripts especializados em automatizar a navegação de upload de cada rede social específica usando Playwright.
*   `login_youtube.py`, `login_facebook.py`, `login_instagram.py`: Scripts simplificados para abrir o navegador, permitir o login manual inicial do usuário e salvar a sessão no disco local.
*   `setup_agendamento.py`: Utilitário em Python para instalar e agendar a execução periódica do bot no Agendador de Tarefas do Windows de forma totalmente silenciosa.

---

## 🛠️ Instalação e Configuração

### Pré-requisitos

1.  **Python 3.10+** instalado no seu sistema.
2.  **FFmpeg** instalado e configurado no PATH do sistema operacional (necessário para o processamento de vídeos).

### Configuração Passo a Passo

1.  **Clonar o repositório:**
    ```bash
    git clone https://github.com/fhenrique77/Automa-o_de_Shorts.git
    cd Automa-o_de_Shorts
    ```

2.  **Criar e ativar o ambiente virtual (opcional, mas recomendado):**
    ```bash
    python -m venv .venv
    # No Windows:
    .venv\Scripts\activate
    ```

3.  **Instalar dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Instalar os navegadores do Playwright:**
    ```bash
    playwright install chromium
    ```

5.  **Variáveis de Ambiente:**
    Adicione a chave da API do Gemini nas variáveis de ambiente do seu sistema:
    *   Nome: `GEMINI_API_KEY`
    *   Valor: `Sua_Chave_Privada_Aqui`

6.  **Configurar Fontes e Canais:**
    Edite o arquivo `authorized_sources.txt` adicionando os links dos canais ou podcasts do YouTube de onde o bot deve extrair os cortes.

---

## 🔑 Login Inicial e Sessões

Para que o upload automatizado funcione sem intervenção manual nas execuções futuras,
salve a sessão em disco uma única vez com os scripts de login.

Os scripts de login e publicação usam o Google Chrome instalado no computador
para abrir os perfis persistentes das quatro plataformas.

```bash
# Para o Facebook
python login_facebook.py

# Para o Instagram
python login_instagram.py

# Para o TikTok
python login_tiktok.py

# Para o YouTube (caso use cookies adicionais)
python login_youtube.py
```
*Após rodar cada script, faça o login na sua conta correspondente na janela do navegador que se abrir e feche-o. A sessão ficará salva localmente na pasta `browser_data_...` correspondente.*

### Chave do Gemini e arquivos privados

A chave é lida exclusivamente da variável de ambiente `GEMINI_API_KEY`. Não coloque
chaves em `config.py`. Sem a variável, o bot usa a curadoria alternativa já existente.
Configure a variável para o usuário do Windows que executa as tarefas e reinicie os
processos que precisam recebê-la. Arquivos `.env` não são carregados automaticamente.
Se uma chave real já foi incluída em um commit, substitua/revogue essa chave no
provedor: removê-la do código atual não a remove do histórico do Git.

O `.gitignore` também cobre backups e variações de `browser_data*`, arquivos `.env`
e o arquivo de bloqueio `.podcast_automation.lock`.

### Execução única e limpeza dos temporários

Quando o YouTube limita consultas de legenda com HTTP 429, o bot interrompe essas
consultas e usa o fallback Whisper, quando habilitado. Para transcrever, baixa
somente o áudio; o trecho de vídeo é baixado depois da seleção do corte. Mantenha
o `yt-dlp` atualizado conforme `requirements.txt`, pois versões antigas podem
deixar de baixar mídias mesmo quando a página do vídeo continua acessível.

O `main.py` obtém um bloqueio do sistema operacional antes de iniciar o pipeline.
Uma segunda execução encerra sem processar ou publicar. O bloqueio é liberado
automaticamente ao encerrar o processo, inclusive em encerramentos forçados;
o arquivo `.podcast_automation.lock` permanece no disco e não deve ser apagado.
O lançador `run_bot_silent.vbs` aguarda o Python terminar e devolve seu código de
saída ao Agendador. As tarefas existentes que apontam para esse lançador já usam
o novo comportamento na próxima execução; não é necessário recriá-las.

Cada execução cria `temp_videos/run_<id>/` e `temp_clips/run_<id>/`:

- Downloads brutos e incompletos são removidos após cada tentativa de processamento
  da fonte, inclusive quando se esgotam as tentativas de download.
- Quando todas as plataformas de um clipe confirmam a publicação, seu arquivo
  gerado pode ser removido. Falhas de exclusão são tentadas novamente e registradas.
- Cortes com envio incompleto, interrompido ou de teste (`--dry-run`) são preservados
  por **7 dias**, com metadados em `.run.json`. Envios reais também são registrados
  na fila SQLite. Testes não criam entregas nem são publicados depois automaticamente.
- Na próxima execução, resíduos de execuções gerenciadas são limpos. Cortes
  preservados só expiram após `TEMP_PENDING_RETENTION_DAYS`; a exclusão acontece
  quando o bot rodar novamente após esse prazo.
- Arquivos do formato antigo diretamente nas pastas temporárias só são elegíveis
  após **24 horas sem alteração** em `temp_videos` ou **7 dias** em `temp_clips`.
  Esses limites são configurados em `config.py`.
- `--no-cleanup` ou `CLEANUP_TEMP_FILES = False` desativam a limpeza da execução e
  marcam seus arquivos para preservação, inclusive nas próximas execuções.
- O arquivo informado por `--input-video` é protegido da limpeza dessa execução.
  Guarde vídeos permanentes fora das pastas temporárias.

Processos iniciados antes desta atualização continuam usando o código anterior;
deixe-os encerrar antes de iniciar a versão nova. A proteção de execução única se
aplica às execuções do pipeline via `main.py`.

Para validar sem acessar as plataformas, execute `python -m unittest discover -s tests -v`.

### Fila por plataforma, confirmação e duplicatas

`publicacoes.sqlite3` guarda os cortes, uma entrega por plataforma e os eventos de
transição. As gravações usam transações SQLite, WAL e sincronização completa.
O `historico.json` existente é importado uma única vez e permanece intacto. Um
histórico inválido bloqueia a primeira importação, em vez de liberar republicações.
Registros antigos conservam os resultados declarados pela versão anterior; a
migração não verifica retroativamente esses posts.

Na execução normal, o bot atende entregas pendentes ou falhas antes de buscar novas fontes.
Se publicou no YouTube e falhou antes de publicar no Instagram, a próxima execução
tenta somente o Instagram, sem baixar ou renderizar novamente. Somente plataformas
habilitadas em `config.py` são atendidas. Cada envio usa sua própria sessão de
navegador e persiste a confirmação antes de fechar essa sessão.
Entregas incertas permanecem reservadas e não são reenviadas automaticamente.
Quando só restam entregas incertas, o agendamento pode gerar novos cortes;
a reserva de fonte e intervalo evita reutilizar o conteúdo enquanto a revisão
estiver pendente.

Os estados exibidos são:

| Estado | Comportamento |
| --- | --- |
| `pending` / `failed` | Pode tentar na próxima execução; nenhuma publicação foi iniciada. |
| `starting` | Preparação do navegador; interrupção volta para `failed`. |
| `submitting` | Comando de publicar prestes a ser enviado ou já enviado. Interrupção vira `uncertain`. |
| `confirmed` | Confirmação explícita recebida, com mensagem, data e link quando disponível. Não reenvia. |
| `uncertain` | Resultado desconhecido após iniciar publicação. Exige revisão antes de qualquer reenvio. |
| `expired` | Prazo de recuperação do arquivo gerado terminou; não reenvia automaticamente. |

Redirecionamento, fim da barra de progresso e textos genéricos como “seu reel” ou
“copiar link” não confirmam publicação. É necessária uma mensagem explícita nova
de sucesso. Mudanças na interface ou mensagens não reconhecidas deixam o resultado
incerto. A confirmação indica que a plataforma aceitou/salvou o post; não garante
alcance, conclusão de análise de conteúdo ou disponibilidade pública posterior.

```powershell
# Consultar IDs, plataformas, estados e comprovantes; não publica
python main.py --queue-status

# Atender somente pendências seguras; não gerar novos cortes
python main.py --retry-pending

# Se um clipe gerado ficou inválido e nenhuma plataforma o publicou,
# refazer a mídia sem criar uma segunda entrega (substitua pelo ID real)
python main.py --repair-delivery 12

# Após conferir manualmente um resultado incerto e encontrar o post
python main.py --resolve-delivery 12 --resolution published --post-url "https://www.instagram.com/reel/ID_DO_POST/" --resolution-note "Conferido na conta"

# Somente após confirmar que o post não existe: liberar a próxima tentativa
python main.py --resolve-delivery 12 --resolution not-published --resolution-note "Conferi posts, processamento e rascunhos; não foi publicado"
```

Resolver uma entrega apenas registra a revisão; não publica no mesmo comando.
O reparo também não publica; exige que todas as entregas do clipe continuem
`pending` ou `failed` e valida quadros de vídeo e áudio antes de substituir o MP4.
O download do trecho prioriza formatos HTTPS para evitar fluxos HLS que podem
entregar somente áudio. Os fluxos completos são baixados com retomada HTTP e o
corte é feito localmente; a validação exige imagem e som até o final do trecho.
Uma entrega com arquivo incompleto é recusada antes de abrir o navegador.
resultar em cortes só com áudio.
Uma entrega incerta continua bloqueando a reutilização do trecho mesmo depois de
expirar a retenção do vídeo. O reenvio de um arquivo já expirado exige recuperação
manual do arquivo e tratamento da entrega; não é liberado pelo bot automaticamente.
Manifestos antigos `.run.json`, anteriores à fila SQLite, não são importados como
novos envios, pois não permitem distinguir posts concluídos de pendências.

Os filtros de 30 dias por vídeo e 90 dias por trecho passam a retornar uma lista
vazia quando todos os candidatos são repetidos. Entregas ainda pendentes ou incertas
também reservam o vídeo/trecho. Uma mesma origem e intervalo tem identidade única
na fila, independentemente do título; vídeos locais são identificados pelo conteúdo.
Não apague o banco para destravar a fila: ele contém as confirmações que evitam
reenvios. Para backup, pare o bot e preserve o banco junto de seus arquivos auxiliares.

---

## 📅 Agendamento de Execução

Você pode agendar o bot para rodar de forma invisível três vezes ao dia: 11:30,
16:45 e 18:30 (horário local do Windows). Para instalar as tarefas:

```bash
python setup_agendamento.py
```
*Isso gerará os arquivos `.bat` e `.vbs` necessários no diretório e os registrará como tarefa silenciosa no Windows.*

---

## ⚠️ Segurança e Boas Práticas

> [!IMPORTANT]
> O arquivo `.gitignore` já está configurado para **excluir** pastas de dados de login local (`browser_data_...`), cookies (`cookies.txt`, `client_secrets.json`, `token.json`), arquivos de log (`automacao.log`) e vídeos temporários. **Nunca desative essas regras**, para evitar que suas chaves de API e credenciais de acesso às redes sociais vazem publicamente no GitHub!

---

## 📝 Licença

Este projeto é de uso educacional e privado. Sinta-se livre para adaptar e utilizar como portfólio de desenvolvimento de automações.
