"""程序入口：python3 main.pyw / Windows 双击（pythonw 运行，无控制台）。

本文件是用户唯一需要打开/编辑的启动文件：顶部的可调配置会通过
media.configure() 应用到后端（ffmpeg 路径、并发上限），默认文件夹则
直接传给主窗口。其余逻辑位于 media.py（后端）与 ui/（界面）。

注意 .pyw 只能作为入口直接执行、不能被 import，因此被导入的模块
（media.py / ui.*）一律使用 .py 后缀。
"""
import media
from ui.app import MediaMergerApp

# ---------------- 用户可调配置（按需修改） ----------------
# ffmpeg 可执行文件路径（Windows 示例: r"C:\Tools\ffmpeg\bin\ffmpeg.exe"；
# Linux 下为 PATH 中的命令名，一般无需修改）
DEFAULT_FFMPEG_PATH = "ffmpeg"

# 默认线程数上限（实际取 min(该值, CPU核数相关计算)）
DEFAULT_MAX_WORKERS = 8

# 文件选择对话框默认打开的文件夹（留空 "" 则使用系统默认位置）
# 示例: r"D:\Videos"（Windows） 或  "/home/user/Videos"
DEFAULT_FOLDER = "/home/myncdw/下载/"

if __name__ == "__main__":
    # 把上面的用户配置应用到后端（重新解析 ffmpeg 路径、设定并发封顶）
    media.configure(
        ffmpeg_path=DEFAULT_FFMPEG_PATH,
        max_workers=DEFAULT_MAX_WORKERS,
    )
    MediaMergerApp(default_folder=DEFAULT_FOLDER).mainloop()
