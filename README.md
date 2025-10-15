# mp4-m4a-merger

简单的 Windows GUI 工具，使用 FFmpeg 批量将同名的 .mp4 视频和 .m4a 音频合并为带音轨的 MP4 文件。支持多线程并行处理与进度实时显示。

## 特性
- 基于 Tkinter 的桌面 GUI
- 自动匹配同名的 .mp4 与 .m4a 文件
- 并行处理（自动根据 CPU 核心数调整线程数）
- 使用 FFmpeg 无损合并视频流，音频转为 AAC
- 输出到 input_folder/output 子目录
- 任务日志与每文件状态实时更新

## 要求
- Windows（脚本中使用了 Windows 专用的 subprocess flags）
- Python 3.7+
- 已安装 FFmpeg（可执行文件路径需在脚本中配置）
- 依赖：tkinter（通常随 Python 一起安装）

## 安装与使用
1. 克隆仓库：
   git clone https://github.com/myncdw/mp4-m4a-merger.git

2. 编辑脚本顶部的 FFMPEG_PATH 为你系统中 ffmpeg.exe 的实际路径，例如：
   FFMPEG_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"

3. 运行：
   python merge_gui.py

4. 在 GUI 中点击 “选择文件夹并开始合并”，选择包含 .mp4 与 .m4a 文件的文件夹。处理完成的文件会保存在该文件夹下的 output 子目录。

## 工作原理（简要）
- 脚本会列出所选文件夹内所有 .mp4 文件，按同名规则查找对应的 .m4a 音频。
- 使用多个 worker（ThreadPoolExecutor）并行调用 ffmpeg，每个 ffmpeg 使用若干内部线程以提高性能。
- 合并命令示例：
  `ffmpeg -i input.mp4 -i input.m4a -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -threads N -y output.mp4`

## 注意事项
- 确保 .mp4 与 .m4a 文件同名（仅扩展名不同），否则不会匹配。
- 若未找到对应 .m4a，会在日志中显示 “未找到音频” 并跳过该文件。
- 脚本中使用了 creationflags=subprocess.CREATE_NO_WINDOW，适用于 Windows，若在其它平台运行需修改相关调用。
