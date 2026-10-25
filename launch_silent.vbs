' Skyzen silent launcher
' Keep this file beside main.py, run.bat, setup.bat, and .venv.
' Uses pythonw.exe so a terminal window is not shown.

Option Explicit

Dim shell, fso, root, mainFile, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
mainFile = fso.BuildPath(root, "main.py")
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")

If Not fso.FileExists(mainFile) Then
    MsgBox "Skyzen main.py was not found:" & vbCrLf & mainFile, vbExclamation, "Skyzen"
    WScript.Quit 1
End If

If Not fso.FileExists(pythonw) Then
    MsgBox "Skyzen's virtual environment is not ready, or pythonw.exe is missing." & vbCrLf & _
           "Please run setup.bat first. If Skyzen still will not start, use run_debug.bat.", _
           vbExclamation, "Skyzen"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & mainFile & Chr(34)
shell.Run command, 0, False
