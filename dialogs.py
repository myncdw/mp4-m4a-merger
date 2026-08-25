"""跨平台文件夹选择对话框封装。

在 Linux 上优先使用系统原生对话框（kdialog / zenity / yad），
全部不可用时回退到 tkinter（兼容 Windows）。
"""
import os
import shutil
import subprocess


def _detect_preferred():
    """根据桌面环境返回首选对话框程序名。"""
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if 'kde' in desktop:
        return 'kdialog'
    if any(name in desktop for name in ('gnome', 'unity', 'pantheon', 'cinnamon')):
        return 'zenity'
    return None


def _available():
    """返回本机可用且按优先级排序的原生对话框程序列表。"""
    preferred = _detect_preferred()
    order = []
    if preferred and shutil.which(preferred):
        order.append(preferred)
    for name in ('zenity', 'kdialog', 'yad'):
        if name not in order and shutil.which(name):
            order.append(name)
    return order


def _ask_kdialog(title, initial_dir=None):
    command = ['kdialog', '--title', title, '--getexistingdirectory']
    if initial_dir and os.path.isdir(initial_dir):
        command.append(initial_dir)
    p = subprocess.run(
        command,
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        return ''  # 用户取消
    path = p.stdout.strip()
    return path if os.path.isdir(path) else ''


def _ask_zenity(title, initial_dir=None):
    command = ['zenity', '--file-selection', '--directory', '--title', title]
    if initial_dir and os.path.isdir(initial_dir):
        command.extend(['--filename', initial_dir.rstrip(os.sep) + os.sep])
    p = subprocess.run(
        command,
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        return ''  # 用户取消
    path = p.stdout.strip()
    return path if os.path.isdir(path) else ''


def _ask_yad(title, initial_dir=None):
    command = ['yad', '--file', '--directory', '--title', title, '--center']
    if initial_dir and os.path.isdir(initial_dir):
        command.extend(['--filename', initial_dir.rstrip(os.sep) + os.sep])
    p = subprocess.run(
        command,
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        return ''  # 用户取消
    path = p.stdout.strip()
    return path if os.path.isdir(path) else ''


def _ask_tk(title, initial_dir=None):
    from tkinter import Tk, filedialog
    root = Tk()
    root.withdraw()
    try:
        folder = filedialog.askdirectory(title=title, initialdir=initial_dir)
        return folder or ''
    finally:
        root.destroy()


def choose_folder(title="请选择文件夹", initial_dir=None):
    """弹出文件夹选择对话框，返回路径字符串（取消时返回空字符串）。"""
    for prog in _available():
        try:
            if prog == 'kdialog':
                path = _ask_kdialog(title, initial_dir)
            elif prog == 'zenity':
                path = _ask_zenity(title, initial_dir)
            else:
                path = _ask_yad(title, initial_dir)
            # 无论选中还是取消都结束，避免重复弹窗
            return path
        except Exception:
            continue
    # 无可用原生对话框时回退 tkinter
    return _ask_tk(title, initial_dir)
