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
*   **Prevenção de Duplicidade:** Banco de dados JSON local (`historico.json`) que rastreia os vídeos e trechos processados, impedindo republicação indesejada por um intervalo definido de dias.

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
    git clone https://github.com/seu-usuario/seu-repositorio.git
    cd seu-repositorio
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

Para que o upload automatizado funcione sem intervenção manual nas execuções futuras, você precisa salvar a sessão em disco uma única vez executando os scripts de login:

```bash
# Para o Facebook
python login_facebook.py

# Para o Instagram
python login_instagram.py

# Para o YouTube (caso use cookies adicionais)
python login_youtube.py
```
*Após rodar cada script, faça o login na sua conta correspondente na janela do navegador que se abrir e feche-o. A sessão ficará salva localmente na pasta `browser_data_...` correspondente.*

---

## 📅 Agendamento de Execução

Você pode agendar o bot para rodar de forma invisível nos horários de pico (configurado por padrão para 3 vezes ao dia: 12:15, 16:45 e 18:30) rodando o setup de agendamento:

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
