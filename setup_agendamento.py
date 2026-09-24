"""
Configura tarefas agendadas no Windows para postar Shorts automaticamente.

Substitui o loop while True antigo por tarefas nativas do Agendador de
Tarefas do Windows (Task Scheduler), eliminando a janela preta permanente e
o consumo de CPU entre execucoes.

Uso:
    python setup_agendamento.py          # Cria as tarefas agendadas
    python setup_agendamento.py --remove # Remove as tarefas agendadas
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TASK_PREFIX = "PodcastAutomation"
WORK_DIR = str(Path(__file__).resolve().parent)
VBS_PATH = str(Path(WORK_DIR) / "run_bot_silent.vbs")

# Horários de postagem — calibrados para o mercado brasileiro 2026 (BRT)
#
# Estratégia aplicada da pesquisa:
#   - Pico TikTok BR: ter-qui 16h-21h (quarta = melhor dia absoluto)
#   - Pico YouTube Shorts BR: 12h-15h e 19h-22h
#   - Estratégia "Off-Peak": postar 45min ANTES do pico para evitar saturação do feed
#     Ex: 18h15 captura audiência antes do rush das 19h com menos concorrência
#
# Slots escolhidos (cobrem todos os picos primários identificados):
#   12h45 → captura almoço (12h-15h Shorts) antes do rush
#   15h15 → janela vespertina TikTok (terça/quarta 16h) — antecipada
#   17h45 → pré-pico noturno TikTok (17h-19h) — máxima eficiência anti-saturação
#   20h15 → rolagem noturna (19h-22h) — zona dourada entretenimento BR
HORARIOS = [
    "11:30",
    "16:45",
    "18:30",
]


def _task_name(horario: str) -> str:
    return f"{TASK_PREFIX}_{horario.replace(':', 'h')}"


def _build_task_xml(horario: str) -> str:
    """Gera XML compativel com o Task Scheduler para uma tarefa diaria."""
    # Formata hora para o XML (HH:MM:SS)
    hora_xml = f"{horario}:00"
    task_name = _task_name(horario)

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Robo de Shorts - Postagem automatica as {horario}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{hora_xml}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"{VBS_PATH}"</Arguments>
      <WorkingDirectory>{WORK_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def create_tasks() -> None:
    # Remove qualquer tarefa antiga cadastrada anteriormente para evitar conflito ou duplicidade
    remove_tasks()

    print("\nConfigurando novas tarefas agendadas no Windows...\n")

    for horario in HORARIOS:
        task_name = _task_name(horario)

        # Gera o XML e salva em arquivo temporario
        xml_content = _build_task_xml(horario)
        xml_path = Path(WORK_DIR) / f"_task_{task_name}.xml"
        xml_path.write_text(xml_content, encoding="utf-16")

        try:
            # Cria tarefa via XML (suporta WorkingDirectory e configuracoes avancadas)
            result = subprocess.run(
                [
                    "schtasks", "/Create",
                    "/TN", task_name,
                    "/XML", str(xml_path),
                    "/F",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"  ✅ Tarefa '{task_name}' criada para rodar todo dia às {horario}")
                print(f"     📂 Diretório de trabalho: {WORK_DIR}")
                print(f"     🔋 Roda mesmo na bateria: Sim")
                print(f"     🌐 Requer rede: Sim")
            else:
                print(f"  ❌ Falha ao criar tarefa '{task_name}': {result.stderr.strip()}")
        finally:
            # Remove arquivo XML temporario
            if xml_path.exists():
                xml_path.unlink()

    print(f"\n🎯 Pronto! {len(HORARIOS)} tarefas configuradas.")
    print("   O robô vai rodar nos horários programados SEM janela aberta.")
    print("   Para ver/editar: Abra o Agendador de Tarefas (taskschd.msc)")
    print(f"\n   Para remover todas: python {Path(__file__).name} --remove")


def remove_tasks() -> None:
    print("Buscando e removendo todas as tarefas agendadas antigas do robô...\n")

    result = subprocess.run(
        ["schtasks", "/Query", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        errors="replace"
    )

    deleted_count = 0
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split(",")
            if parts:
                task_path = parts[0].strip('"')
                task_name = task_path.lstrip("\\")
                if task_name.startswith("PodcastAutomation_"):
                    del_result = subprocess.run(
                        ["schtasks", "/Delete", "/TN", task_name, "/F"],
                        capture_output=True,
                    )
                    if del_result.returncode == 0:
                        print(f"  🗑️  Tarefa '{task_name}' removida.")
                        deleted_count += 1
                    else:
                        print(f"  ⚠️  Falha ao remover tarefa '{task_name}'.")

    if deleted_count == 0:
        print("Nenhuma tarefa da automação encontrada para remover.")
    else:
        print(f"\nLimpeza concluída! {deleted_count} tarefas antigas foram removidas.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerencia tarefas agendadas do robô de Shorts")
    parser.add_argument("--remove", action="store_true", help="Remove todas as tarefas agendadas")
    args = parser.parse_args()

    if args.remove:
        remove_tasks()
    else:
        create_tasks()


if __name__ == "__main__":
    main()
