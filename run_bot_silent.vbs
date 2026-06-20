' =============================================================
'  Lança o bot SEM abrir NENHUMA janela visível
'  Usa o .bat como intermediário (resolve caminhos com espaço)
'  WshShell.Run com style=0 oculta a janela do CMD
' =============================================================
Dim fso, scriptDir, batPath
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath   = fso.BuildPath(scriptDir, "run_bot.bat")

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & batPath & """", 0, False

Set WshShell = Nothing
Set fso = Nothing
