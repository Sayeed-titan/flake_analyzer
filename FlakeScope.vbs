' FlakeScope.vbs — double-click launcher (no console flash, no window flicker)
' Uses pythonw.exe (Windows GUI subsystem) to avoid console/Qt message-queue conflicts.
Option Explicit

Dim WshShell, fso, dir, pythonw, ready

Set WshShell = CreateObject("WScript.Shell")
Set fso     = CreateObject("Scripting.FileSystemObject")

dir    = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = dir & "\.venv\Scripts\pythonw.exe"
ready   = dir & "\.venv\Scripts\flakescope.ready"

' ── First-time setup: run the bat to create venv + install packages ──────────
If Not fso.FileExists(pythonw) Or Not fso.FileExists(ready) Then
    Dim ret
    ret = MsgBox("FlakeScope needs a one-time setup (~2-3 min)." & vbCrLf & _
                 "Click OK to start — a setup window will open.", _
                 vbOKCancel + vbInformation, "FlakeScope Setup")
    If ret <> vbOK Then WScript.Quit
    ' Run bat in a visible window and wait for it to finish
    WshShell.Run Chr(34) & dir & "\FlakeScope.bat" & Chr(34), 1, True
End If

' ── Launch the app cleanly ───────────────────────────────────────────────────
If fso.FileExists(pythonw) Then
    WshShell.CurrentDirectory = dir
    ' windowStyle 0 = hidden console; bWaitOnReturn False = fire and forget
    WshShell.Run Chr(34) & pythonw & Chr(34) & " """ & dir & "\main.py""", 0, False
Else
    MsgBox "Setup did not complete. Please run FlakeScope.bat manually.", _
           vbCritical, "FlakeScope"
End If
