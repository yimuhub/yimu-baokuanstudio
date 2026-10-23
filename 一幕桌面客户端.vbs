Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 优先使用内置便携 runtime，次优使用 .venv
If fso.FileExists(currentDir & "\runtime\pythonw.exe") Then
    pyExe = """" & currentDir & "\runtime\pythonw.exe"""
ElseIf fso.FileExists(currentDir & "\runtime\python.exe") Then
    pyExe = """" & currentDir & "\runtime\python.exe"""
ElseIf fso.FileExists(currentDir & "\.venv\Scripts\pythonw.exe") Then
    pyExe = """" & currentDir & "\.venv\Scripts\pythonw.exe"""
ElseIf fso.FileExists(currentDir & "\.venv\Scripts\python.exe") Then
    pyExe = """" & currentDir & "\.venv\Scripts\python.exe"""
Else
    ' 若尚未配置任何环境，引导运行一键启动脚本
    WshShell.Run "cmd /c """ & currentDir & "\一键启动.bat""", 1, False
    WScript.Quit
End If

desktopScript = """" & currentDir & "\desktop.py"""
' 运行 desktop.py，第 2 参数为 0 表示隐藏黑色控制台窗口，获得纯净桌面原生体验
WshShell.Run pyExe & " " & desktopScript, 0, False
