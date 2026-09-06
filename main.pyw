"""程序入口：python3 main.pyw / Windows 双击（pythonw 运行，无控制台）。

只需组装 GUI 应用并进入主循环；全部逻辑位于 media.py（后端）与
ui/（界面）。注意 .pyw 只能作为入口直接执行、不能被 import，
因此被导入的模块（media.py / ui.*）一律使用 .py 后缀。
"""
from ui.app import MediaMergerApp

if __name__ == "__main__":
    MediaMergerApp().mainloop()
