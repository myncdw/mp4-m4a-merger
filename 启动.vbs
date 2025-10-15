' ==========================
' run_python.vbs
' ==========================

Option Explicit

Dim fso, folder, files, pyFiles, pywFiles
Dim fileToRun, pythonPath

Set fso = CreateObject("Scripting.FileSystemObject")
Set folder = fso.GetFolder(fso.GetParentFolderName(WScript.ScriptFullName))
Set files = folder.Files

Set pyFiles = CreateObject("Scripting.Dictionary")
Set pywFiles = CreateObject("Scripting.Dictionary")

' ==========================
' 1. 遍历当前文件夹，收集 .py 和 .pyw 文件
' ==========================
Dim file
For Each file In files
    If LCase(fso.GetExtensionName(file.Name)) = "py" Then
        pyFiles.Add file.Name, file.Path
    ElseIf LCase(fso.GetExtensionName(file.Name)) = "pyw" Then
        pywFiles.Add file.Name, file.Path
    End If
Next

' ==========================
' 2. 确定要运行的 Python 文件
' ==========================
fileToRun = ""

If pyFiles.Count + pywFiles.Count = 0 Then
    MsgBox "当前文件夹没有 Python 脚本 (.py 或 .pyw) 可运行！", vbExclamation, "提示"
    WScript.Quit
End If

If pyFiles.Count + pywFiles.Count = 1 Then
    If pyFiles.Count = 1 Then
        fileToRun = pyFiles.Items()(0)
    Else
        fileToRun = pywFiles.Items()(0)
    End If
Else
    If pyFiles.Exists("main.py") Then
        fileToRun = pyFiles("main.py")
    ElseIf pywFiles.Exists("main.pyw") Then
        fileToRun = pywFiles("main.pyw")
    Else
        MsgBox "存在多个 Python 文件，但未找到 main.py 或 main.pyw，请手动选择要运行的脚本！", vbExclamation, "提示"
        WScript.Quit
    End If
End If

' ==========================
' 3. 确定 Python 解释器路径
' ==========================
Dim shell, isPy
Set shell = CreateObject("WScript.Shell")
isPy = (LCase(fso.GetExtensionName(fileToRun)) = "py")

If fso.FolderExists(folder.Path & "\.venv") Then
    ' 如果存在虚拟环境
    If isPy Then
        pythonPath = folder.Path & "\.venv\Scripts\python.exe"
    Else
        pythonPath = folder.Path & "\.venv\Scripts\pythonw.exe"
    End If
    
    If Not fso.FileExists(pythonPath) Then
        MsgBox "未找到虚拟环境中的 Python，请检查 .venv 文件夹。", vbExclamation, "提示"
        WScript.Quit
    End If
Else
    ' 没有虚拟环境，使用系统默认 Python
    If isPy Then
        pythonPath = "python.exe"
    Else
        pythonPath = "pythonw.exe"
    End If
End If

' ==========================
' 4. 运行 Python 脚本
' ==========================
If isPy Then
    ' .py 文件显示控制台窗口
    shell.Run """" & pythonPath & """ """ & fileToRun & """", 1, False
Else
    ' .pyw 文件隐藏窗口
    shell.Run """" & pythonPath & """ """ & fileToRun & """", 0, False
End If
