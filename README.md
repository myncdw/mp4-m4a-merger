# mp4-m4a-merger

跨平台（Windows / Linux）GUI 工具，使用 FFmpeg 批量将同名的 .mp4 视频和 .m4a 音频合并为带音轨的 MP4 文件。支持多线程并行处理与进度实时显示。

## 特性
- 基于 Tkinter 的桌面 GUI
- 自动匹配同名的 .mp4 与 .m4a 文件
- 并行处理（自动根据 CPU 核心数调整线程数）
- 使用 FFmpeg 无损合并视频流，音频转为 AAC
- 输出到 input_folder/output 子目录
- 任务日志与每文件状态实时更新

## 要求
- Windows / Linux（脚本会自动适配平台差异）
- Python 3.7+
- 已安装 FFmpeg 与 FFprobe
  - Windows：可在脚本顶部 `DEFAULT_FFMPEG_PATH` 配置路径；若未配置，脚本会尝试从 PATH 查找
  - Linux：安装后确保 `ffmpeg`、`ffprobe` 在 PATH 中（例如 `sudo apt install ffmpeg`）
- 依赖：tkinter（通常随 Python 一起安装；Linux 下可能需要额外安装 `python3-tk`）

## 安装与使用
1. 克隆仓库：
   git clone https://github.com/myncdw/mp4-m4a-merger.git

2. 编辑脚本顶部的 `DEFAULT_FFMPEG_PATH` 为你系统中 ffmpeg 的实际路径（Windows），例如：
   DEFAULT_FFMPEG_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"
   若 ffmpeg 已加入 PATH（Linux 常见做法），无需修改，脚本会自动查找。

3. 运行：
   python media.pyw

4. 在 GUI 中点击 “选择文件夹并开始合并”，选择包含 .mp4 与 .m4a 文件的文件夹。处理完成的文件会保存在该文件夹下的 output 子目录。

## 工作原理（简要）
- 脚本会列出所选文件夹内所有 .mp4 文件，按同名规则查找对应的 .m4a 音频。
- 使用多个 worker（ThreadPoolExecutor）并行调用 ffmpeg，每个 ffmpeg 使用若干内部线程以提高性能。
- 支持选择更快的编码 preset，并可启用或禁用 `-movflags +faststart`，减少最后阶段写入 header 的耗时。
- 合并命令示例：
  `ffmpeg -i input.mp4 -i input.m4a -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -threads N -y output.mp4`

## 注意事项
- 确保 .mp4 与 .m4a 文件同名（仅扩展名不同），否则不会匹配。
- 若未找到对应 .m4a，会在日志中显示 “未找到音频” 并跳过该文件。
- 脚本已做跨平台处理：`CREATE_NO_WINDOW` 仅 Windows 生效，Linux 下自动忽略；字体常量位于脚本开头（`FONT_*`），可按平台自行调整。
