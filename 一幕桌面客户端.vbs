Option Explicit
' YIMU Studio desktop launcher (Windows).
' ASCII-only + CRLF + no BOM: WSH reads .vbs as ANSI, non-ASCII text corrupts paths.
' V15.8: window style MUST be 1 (SW_SHOWNORMAL). Style 0 (SW_HIDE) is applied to
' the first top-level window of the child process, which is the pywebview main
' window under pythonw.exe -- the classic "double click does nothing" bug.
Dim WshShell, fso, root, pyExe, launcher, batFolder, batFile
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

' pythonw.exe has no console; force UTF-8 so prints and uvicorn logs never fail.
WshShell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
WshShell.Environment("PROCESS")("PYTHONUTF8") = "1"

' Prefer the self-contained portable runtime, then a local venv.
If fso.FileExists(root & "\runtime\pythonw.exe") Then
    pyExe = root & "\runtime\pythonw.exe"
ElseIf fso.FileExists(root & "\runtime\python.exe") Then
    pyExe = root & "\runtime\python.exe"
ElseIf fso.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
    pyExe = root & "\.venv\Scripts\pythonw.exe"
ElseIf fso.FileExists(root & "\.venv\Scripts\python.exe") Then
    pyExe = root & "\.venv\Scripts\python.exe"
End If

If pyExe = "" Then
    ' No runtime: hand over to the bundled bootstrap .bat (name may be localized).
    Set batFolder = fso.GetFolder(root)
    For Each batFile In batFolder.Files
        If LCase(fso.GetExtensionName(batFile.Name)) = "bat" Then
            WshShell.Run "cmd /c """ & batFile.Path & """", 1, False
            WScript.Quit
        End If
    Next
    WshShell.Popup "YIMU Studio: Python runtime not found in " & root, 0, "YIMU Studio", 16
    WScript.Quit 1
End If

' The launcher shim normalizes cwd / sys.path and delegates to desktop.py.
' desktop.py itself owns log redirection, single-instance lock and window creation.
launcher = root & "\app\launch_desktop.py"
If Not fso.FileExists(launcher) Then launcher = root & "\launch_desktop.py"
If Not fso.FileExists(launcher) Then launcher = root & "\app\desktop.py"
If Not fso.FileExists(launcher) Then launcher = root & "\desktop.py"
If Not fso.FileExists(launcher) Then
    WshShell.Popup "YIMU Studio: desktop.py not found in " & root, 0, "YIMU Studio", 16
    WScript.Quit 1
End If

WshShell.CurrentDirectory = fso.GetParentFolderName(launcher)
WshShell.Run """" & pyExe & """ """ & launcher & """", 1, False
