@echo off
REM =============================================================
REM  Transfere o projeto para a VPS Oracle
REM  Uso: deploy_to_vps.bat IP_DA_VPS CAMINHO_DA_CHAVE_SSH
REM  Exemplo: deploy_to_vps.bat 123.456.78.90 C:\Users\SEU_USUARIO\.ssh\id_rsa
REM =============================================================

if "%~1"=="" (
    echo Uso: %~nx0 IP_DA_VPS CAMINHO_DA_CHAVE_SSH
    echo Exemplo: %~nx0 123.456.78.90 C:\Users\SEU_USUARIO\.ssh\id_rsa
    exit /b 1
)

set VPS_IP=%~1
set SSH_KEY=%~2
set PROJECT_DIR=%~dp0
set REMOTE_DIR=~/podcast_automation

echo ==========================================
echo   Transferindo projeto para %VPS_IP%
echo ==========================================
echo.

REM 1. Criar diretorio remoto
echo [1/5] Criando diretorio remoto...
ssh -i "%SSH_KEY%" ubuntu@%VPS_IP% "mkdir -p %REMOTE_DIR%/deploy %REMOTE_DIR%/logs"

REM 2. Copiar arquivos Python (codigo fonte)
echo [2/5] Copiando codigo fonte...
for %%f in (main.py config.py config_vps.py cutter.py downloader.py uploader.py tiktok_uploader.py utils.py setup_agendamento.py requirements.txt) do (
    scp -i "%SSH_KEY%" "%PROJECT_DIR%%%f" ubuntu@%VPS_IP%:%REMOTE_DIR%/ 2>nul
)

REM 3. Copiar scripts de deploy
echo [3/5] Copiando scripts de deploy...
scp -i "%SSH_KEY%" "%PROJECT_DIR%deploy\setup_vps.sh" ubuntu@%VPS_IP%:%REMOTE_DIR%/deploy/
scp -i "%SSH_KEY%" "%PROJECT_DIR%deploy\run_bot.sh" ubuntu@%VPS_IP%:%REMOTE_DIR%/deploy/
scp -i "%SSH_KEY%" "%PROJECT_DIR%deploy\cron_setup.sh" ubuntu@%VPS_IP%:%REMOTE_DIR%/deploy/
scp -i "%SSH_KEY%" "%PROJECT_DIR%deploy\iniciar_login.sh" ubuntu@%VPS_IP%:%REMOTE_DIR%/deploy/
scp -i "%SSH_KEY%" "%PROJECT_DIR%deploy\parar_login.sh" ubuntu@%VPS_IP%:%REMOTE_DIR%/deploy/

REM 4. Copiar dados (cookies, historico, fontes)
echo [4/5] Copiando dados de configuracao...
scp -i "%SSH_KEY%" "%PROJECT_DIR%cookies.txt" ubuntu@%VPS_IP%:%REMOTE_DIR%/ 2>nul
scp -i "%SSH_KEY%" "%PROJECT_DIR%historico.json" ubuntu@%VPS_IP%:%REMOTE_DIR%/ 2>nul
scp -i "%SSH_KEY%" "%PROJECT_DIR%authorized_sources.txt" ubuntu@%VPS_IP%:%REMOTE_DIR%/ 2>nul
scp -i "%SSH_KEY%" "%PROJECT_DIR%source_schedules.json" ubuntu@%VPS_IP%:%REMOTE_DIR%/ 2>nul

REM 5. Configurar API key na VPS
echo [5/5] Configurando variavel de ambiente...
ssh -i "%SSH_KEY%" ubuntu@%VPS_IP% "grep -q GEMINI_API_KEY ~/.bashrc || echo 'export GEMINI_API_KEY=\"COLE_SUA_CHAVE_AQUI\"' >> ~/.bashrc"

echo.
echo ==========================================
echo   Transferencia concluida!
echo ==========================================
echo.
echo   Proximo passo: conecte na VPS e rode:
echo     ssh -i "%SSH_KEY%" ubuntu@%VPS_IP%
echo     cd %REMOTE_DIR%
echo     bash deploy/setup_vps.sh
echo.
echo   IMPORTANTE: Edite a GEMINI_API_KEY no ~/.bashrc:
echo     nano ~/.bashrc
echo     (troque COLE_SUA_CHAVE_AQUI pela sua chave real)
echo     source ~/.bashrc
echo.
