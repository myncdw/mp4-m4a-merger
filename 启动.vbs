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
' 1. ������ǰ�ļ��У��ռ� .py �� .pyw �ļ�
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
' 2. ȷ��Ҫ���е� Python �ļ�
' ==========================
fileToRun = ""

If pyFiles.Count + pywFiles.Count = 0 Then
    MsgBox "��ǰ�ļ���û�� Python �ű� (.py �� .pyw) �����У�", vbExclamation, "��ʾ"
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
        MsgBox "���ڶ�� Python �ļ�����δ�ҵ� main.py �� main.pyw�����ֶ�ѡ��Ҫ���еĽű���", vbExclamation, "��ʾ"
        WScript.Quit
    End If
End If

' ==========================
' 3. ȷ�� Python ������·��
' ==========================
Dim shell, isPy
Set shell = CreateObject("WScript.Shell")
isPy = (LCase(fso.GetExtensionName(fileToRun)) = "py")

If fso.FolderExists(folder.Path & "\.venv") Then
    ' ����������⻷��
    If isPy Then
        pythonPath = folder.Path & "\.venv\Scripts\python.exe"
    Else
        pythonPath = folder.Path & "\.venv\Scripts\pythonw.exe"
    End If
    
    If Not fso.FileExists(pythonPath) Then
        MsgBox "δ�ҵ����⻷���е� Python������ .venv �ļ��С�", vbExclamation, "��ʾ"
        WScript.Quit
    End If
Else
    ' û�����⻷����ʹ��ϵͳĬ�� Python
    If isPy Then
        pythonPath = "python.exe"
    Else
        pythonPath = "pythonw.exe"
    End If
End If

' ==========================
' 4. ���� Python �ű�
' ==========================
If isPy Then
    ' .py �ļ���ʾ����̨����
    shell.Run """" & pythonPath & """ """ & fileToRun & """", 1, False
Else
    ' .pyw �ļ����ش���
    shell.Run """" & pythonPath & """ """ & fileToRun & """", 0, False
End If
