# mp4-m4a-merger

跨平台（Windows / Linux）GUI 工具，使用 FFmpeg 批量将同名的 .mp4 视频和 .m4a 音频合并为带音轨的 MP4 文件。支持多线程并行处理与进度实时显示。

## 依赖

本项目依赖 [xdg-dialogs](https://github.com/myncdw/xdg_dialogs)（未发布到 PyPI），请先获取

## 特性
- 基于 Tkinter 的桌面 GUI
- 自动匹配同名的 .mp4 与 .m4a 文件
- 并行处理（自动根据 CPU 核心数调整线程数）
- 使用 FFmpeg 无损合并视频流，音频转为 AAC
- 输出到 input_folder/output 子目录
- 任务日志与每文件状态实时更新

## 模块结构
```
├── main.pyw       程序入口（python3 main.pyw 或 Windows 双击）；
│                  顶部为用户可改的默认配置（ffmpeg 路径/线程上限/默认文件夹）
├── media.py       后端：ffmpeg/ffprobe 路径解析、命令构造、并发合并调度、
│                  消息/状态常量（不 import tkinter，可无 GUI 导入与测试）
├── dialogs.py     跨平台文件夹选择对话框
├── ui/
│   ├── __init__.py
│   ├── theme.py   UI 主题：字体与颜色常量（FONT_*、COLOR_*）
│   └── app.py     MediaMergerApp 主窗口：布局、控件、队列分发、错误日志
└── tests/         后端回归测试（stdlib unittest，见下文“运行测试”）
```
注意：`.pyw` 只能作为入口直接执行、不能被 `import`，因此只有 `main.pyw` 使用
`.pyw` 后缀，被导入的模块全部为 `.py`。依赖方向单向：`main.pyw → ui.app →
media`，`ui.app → dialogs`。启动时 `main.pyw` 会把顶部的用户配置通过
`media.configure()` 注入后端。

## 要求
- Windows / Linux（脚本会自动适配平台差异）
- Python 3.7+
- 已安装 FFmpeg 与 FFprobe
  - Windows：可在 `main.pyw` 顶部 `DEFAULT_FFMPEG_PATH` 配置路径；若未配置，脚本会尝试从 PATH 查找
  - Linux：安装后确保 `ffmpeg`、`ffprobe` 在 PATH 中（例如 `sudo apt install ffmpeg`）
- 依赖：tkinter（通常随 Python 一起安装；Linux 下可能需要额外安装 `python3-tk`）

## 安装与使用
1. 克隆仓库：
   git clone https://github.com/myncdw/mp4-m4a-merger.git

2. 编辑 `main.pyw` 顶部为用户可改的默认配置：`DEFAULT_FFMPEG_PATH`（ffmpeg 路径）、
   `DEFAULT_MAX_WORKERS`（并发上限）、`DEFAULT_FOLDER`（默认打开文件夹）。例如（Windows）：
   DEFAULT_FFMPEG_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"
   若 ffmpeg 已加入 PATH（Linux 常见做法），无需修改，程序会自动查找。

3. 运行：
   python3 main.pyw
   （Windows 下也可直接双击 `main.pyw`）

4. 在 GUI 中点击 “选择文件夹并开始合并”，选择包含 .mp4 与 .m4a 文件的文件夹。处理完成的文件会保存在该文件夹下的 output 子目录。

## 运行测试
后端纯逻辑回归测试使用标准库 unittest（零第三方依赖，兼容 Python 3.7+），在仓库根目录执行：
   python3 -m unittest discover -s tests -v

## 工作原理（简要）
- 脚本会列出所选文件夹内所有 .mp4 文件，按同名规则查找对应的 .m4a 音频。
- 使用多个 worker（ThreadPoolExecutor）并行调用 ffmpeg，每个 ffmpeg 使用若干内部线程以提高性能。
- 支持选择更快的编码 preset，并可启用或禁用 `-movflags +faststart`，减少最后阶段写入 header 的耗时。
- 合并命令示例：
  `ffmpeg -i input.mp4 -i input.m4a -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -threads N -y output.mp4`

## 注意事项
- 确保 .mp4 与 .m4a 文件同名（仅扩展名不同），否则不会匹配。
- 若未找到对应 .m4a，会在日志中显示 “未找到音频” 并跳过该文件。
- 脚本已做跨平台处理：`CREATE_NO_WINDOW` 仅 Windows 生效，Linux 下自动忽略；字体与颜色常量位于 `ui/theme.py`（`FONT_*`、`COLOR_*`），ffmpeg 路径、线程上限与默认文件夹等用户可调项集中在 `main.pyw` 顶部。
