"""UI 主题与 UI 侧配置：字体、颜色、默认文件夹等纯常量。

只被 ui/app.py 使用；刻意不 import 后端 media.py，避免形成
theme -> media 的依赖，保证 theme 可被单独替换/维护。

本文件的 IS_WINDOWS 与 media.IS_WINDOWS 是同一判断逻辑的一行重复：
两者用途不同——media 用它决定子进程参数（CREATE_NO_WINDOW 等），
theme 用它选择 UI 字体族。为维持依赖方向单向（ui -> media）而保留此重复。
"""
import sys

IS_WINDOWS = sys.platform.startswith("win")

# ================= 字体常量（按平台选择，可自行调整） =================
FONT_FAMILY = "微软雅黑" if IS_WINDOWS else "Noto Sans CJK SC"
FONT_NUMERIC = "Arial" if IS_WINDOWS else "DejaVu Sans Mono"

FONT_TITLE = (FONT_FAMILY, 16, "bold")       # 主标题
FONT_PERCENT = (FONT_NUMERIC, 12, "bold")    # 进度百分比
FONT_NORMAL = (FONT_FAMILY, 10)              # 普通文本
FONT_SMALL = (FONT_FAMILY, 9)                # 小号辅助文本
FONT_BTN_BOLD = (FONT_FAMILY, 11, "bold")    # 主按钮
FONT_BTN = (FONT_FAMILY, 11)                 # 普通按钮
FONT_TABLE = (FONT_FAMILY, 10)               # 表格/分组标题

# ================= 按钮与文字颜色 =================
COLOR_START_BG = "#4CAF50"
COLOR_START_ACTIVE = "#45a049"
COLOR_STOP_BG = "#f44336"
COLOR_STOP_ACTIVE = "#d32f2f"
COLOR_INFO_FG = "gray"

# 文件选择对话框默认打开的文件夹（留空 "" 则使用系统默认位置）
# 示例: DEFAULT_FOLDER = r"D:\Videos"  （Windows） 或  DEFAULT_FOLDER = "/home/user/Videos"
DEFAULT_FOLDER = "/home/myncdw/下载/"
