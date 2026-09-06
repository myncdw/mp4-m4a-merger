# ============================================================================
# 模块说明：
#  本文件是 mp4-m4a-merger 的后端模块（被 main.pyw / ui/app.py 导入使用）。
#  它负责把同一文件夹内同名的 .mp4（视频流）与 .m4a（音频流）
#  无损合并成一个 MP4 文件。合并过程使用 FFmpeg 的 -c copy 流复制，
#  不重新编码，因此速度快且画质/音质无损。
#
#  主要职责：
#   1. 平台检测与 ffmpeg/ffprobe 路径解析
#   2. 构造无损合并所需的 FFmpeg 命令
#   3. 探测视频时长并估算最后封装阶段的耗时
#   4. 后台批量调度 FFmpeg 任务（多文件并行、线程池 + 停止标志）
#   5. 把进度/状态/结果通过消息队列上报给 GUI（协议常量见下方）
#
#  注意：本模块不 import tkinter，可在无 GUI 环境被单独导入
#  （单元测试、未来的 CLI 等）。UI 相关逻辑在 ui/ 子包中。
# ============================================================================

import os
import sys
import shutil
import subprocess
import threading
import traceback
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 平台检测 =================
IS_WINDOWS = sys.platform.startswith("win")
# 仅在 Windows 上有意义，其它平台为 0（Popen 会忽略该参数）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ================= 后端内部默认值 =================
# 用户可改的默认配置已集中到入口 main.pyw 顶部，启动时通过 configure()
# 注入本模块；以下只是脱离入口单独导入（单元测试等）时的内置出厂值：
#   _CONFIG_FFMPEG_PATH：ffmpeg 可执行文件默认路径
#     （Windows 示例: r"C:\Tools\ffmpeg\bin\ffmpeg.exe"）
#   _CONFIG_MAX_WORKERS：默认线程数上限（实际取 min(该值, CPU相关计算)）
_CONFIG_FFMPEG_PATH = "ffmpeg"  # Linux 下默认命令名
_CONFIG_MAX_WORKERS = 8


def resolve_ffmpeg_path():
    """跨平台解析 ffmpeg 路径：显式配置的路径若存在则优先，否则从 PATH 查找。"""
    # 入口显式配置了存在的可执行文件路径（如 Windows 的 ffmpeg.exe）→ 直接使用
    if os.path.isfile(_CONFIG_FFMPEG_PATH):
        return _CONFIG_FFMPEG_PATH
    # 否则（如 Linux 下的命令名 "ffmpeg"）依赖 PATH 环境变量中的 ffmpeg 命令
    found = shutil.which("ffmpeg")
    # 都找不到时退回配置的默认命令名，让后续调用自然报错，便于用户发现环境问题
    return found or _CONFIG_FFMPEG_PATH


FFMPEG_PATH = resolve_ffmpeg_path()  # Linux 下通常为 PATH 中的 "ffmpeg"


def get_ffprobe_path():
    """跨平台获取 ffprobe 可执行文件路径。"""
    probe_exe = "ffprobe.exe" if IS_WINDOWS else "ffprobe"
    # 优先使用与 FFMPEG_PATH 同目录下的 ffprobe（常见于绿色版/手动安装）
    local = os.path.join(os.path.dirname(FFMPEG_PATH), probe_exe)
    if os.path.isfile(local):
        return local
    # 否则从 PATH 中查找，找不到则返回命令名本身
    return shutil.which("ffprobe") or probe_exe


def configure(ffmpeg_path=None, max_workers=None):
    """用 main.pyw 顶部的用户配置覆盖后端默认值并使其生效。

    - ffmpeg_path：ffmpeg 可执行文件路径；覆盖后立即按新值重新解析
      FFMPEG_PATH（供 build_ffmpeg_command / get_ffprobe_path 使用）。
    - max_workers：并发 worker 的封顶值（须 >= 1），影响
      recommended_workers() 与 merge_media() 的钳制上限。

    两个参数均可省略（省略则不修改对应项）；须在任何合并任务启动前调用。
    """
    global _CONFIG_FFMPEG_PATH, _CONFIG_MAX_WORKERS, FFMPEG_PATH
    if ffmpeg_path is not None:
        _CONFIG_FFMPEG_PATH = ffmpeg_path
        # 立即按新配置重新解析，保证后续合并命令使用新路径
        FFMPEG_PATH = resolve_ffmpeg_path()
    if max_workers is not None:
        _CONFIG_MAX_WORKERS = max(1, int(max_workers))


# ================= 队列消息类型与文件状态（worker → GUI 协议常量） =================
# 队列消息统一为 (tag, ...) 元组：第一元素为类型标签，其余为负载。
# 字段结构说明（GUI 在 ui/app.py 中按标签分发，请勿随意改动以下常量值）：
#   MSG_PROGRESS      -> (total_percent: float, done: int, total: int)
#   MSG_FILE_START    -> (video_name: str)
#   MSG_FILE_STATUS   -> (video_name: str, status: STATUS_*)
#   MSG_FILE_PROGRESS -> (video_name: str, percent: float)
#   MSG_FILE_ESTIMATE -> (video_name: str, estimate_seconds: float)
#   MSG_DONE          -> (merged_count: int, output_folder: str)
#   MSG_STOPPED       -> ()
#   MSG_ERROR         -> (message: str)
#   MSG_FFMPEG_ERROR  -> (video_name: str, detail: str)
#   MSG_LOG           -> (message: str)   # 历史保留：GUI 目前不消费
MSG_PROGRESS = "progress"
MSG_FILE_START = "file_start"
MSG_FILE_STATUS = "file_status"
MSG_FILE_PROGRESS = "file_progress"
MSG_FILE_ESTIMATE = "file_estimate"
MSG_DONE = "done"
MSG_STOPPED = "stopped"
MSG_ERROR = "error"
MSG_FFMPEG_ERROR = "ffmpeg_error"
MSG_LOG = "log"

# 文件状态（Treeview“状态”列的取值，GUI 与 worker 共用）
STATUS_QUEUED = "已提交"           # 仅 GUI 插入
STATUS_PROCESSING = "处理中"
STATUS_DONE = "完成"
STATUS_FAILED = "失败"
STATUS_AUDIO_MISSING = "未找到音频"
STATUS_ERROR = "错误"
STATUS_STOPPED = "已停止"

# 仓库根目录（本文件所在目录，即旧 media.pyw 所在目录），
# 供 UI 把 ffmpeg_error.log 写到与原版一致的位置。
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def recommended_workers():
    """GUI 默认并行度：min(_CONFIG_MAX_WORKERS, max(2, CPU核数//4))。

    与 merge_media 对用户输入的钳制逻辑同源（默认值从不超过线程数上限
    _CONFIG_MAX_WORKERS），供 ui/app.py 初始化“线程数”输入框。
    线程数上限可由入口 main.pyw 通过 configure(max_workers=...) 调整。
    """
    total_cores = multiprocessing.cpu_count()
    return min(_CONFIG_MAX_WORKERS, max(2, total_cores // 4))


def build_ffmpeg_command(video_path, audio_path, output_path, ffmpeg_threads):
    """构造无损合并所需的 FFmpeg 命令。"""
    # 参数含义：
    #   -hide_banner / -loglevel error / -nostats：屏蔽无关提示，只保留错误
    #   -progress pipe:1：以 key=value 形式把进度写入 stdout，供本程序解析
    #   -map 0:v:0 -map 1:a:0：视频流取第 1 个输入，音频流取第 2 个输入
    #   -threads：控制本次合并使用的编解码线程数
    #   -c copy：直接复制流而不重新编码（无损、速度最快）
    #   -movflags +faststart：把 moov 元数据移到文件头部，便于"边下边播"
    #   -y：输出文件已存在时直接覆盖
    return [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel", "error",
        "-progress", "pipe:1",
        "-nostats",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-threads", str(ffmpeg_threads),
        "-c", "copy",
        "-movflags", "+faststart",
        "-y", output_path,
    ]


def get_media_duration(video_path):
    """返回视频时长（秒），用于估算进度百分比。"""
    ffprobe_path = get_ffprobe_path()

    # 让 ffprobe 只输出时长：
    #   -v error              关闭多余日志
    #   -show_entries format=duration  只查询容器总时长
    #   -of ... nokey=1       输出纯数字（如 12.340000），便于直接转 float
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        # creationflags 用于 Windows 下隐藏弹出的控制台窗口
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                creationflags=CREATE_NO_WINDOW)
        if result.returncode != 0:
            # ffprobe 解析失败（文件损坏等），返回 None 由调用方兜底
            return None
        # 去掉末尾换行后转为秒数
        return float(result.stdout.strip())
    except Exception:
        # 任何异常都返回 None，不让探测失败影响整体流程
        return None


def estimate_finalization_time(video_path, audio_path, duration=None):
    """根据视频长度和文件体积，估算最后封装/收尾所需时间。"""
    # 优先用调用方传入的时长，否则现场用 ffprobe 探测
    if duration is None:
        duration = get_media_duration(video_path)
    # 探测失败时按 10 分钟兜底，避免后续进度估算失效
    if duration is None:
        duration = 600

    # 把视频、音频的文件体积换算为 MB（文件不存在时按 0 处理）
    video_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0.0
    audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024) if os.path.exists(audio_path) else 0.0
    # max() 保证分母不为 0，避免极小文件导致估算异常
    total_size_mb = max(video_size_mb, 1.0) + max(audio_size_mb, 0.0)
    duration_min = max(duration / 60.0, 1.0)

    # 经验公式：固定开销 1.5s + 每 120MB 约 1s + 每分钟时长约 0.3s
    estimate_seconds = 1.5 + total_size_mb / 120.0 + duration_min * 0.3
    # 实际收尾时间基本落在 2~60 秒内，把估算值夹紧到该区间
    return round(min(60.0, max(2.0, estimate_seconds)), 1)


def merge_single_media(video_path, audio_path, output_path, ffmpeg_threads, progress_queue, video_name, stop_event):
    """合并单个视频和音频，仅进行无损流复制。"""
    # 延迟 import：只有真正进入工作线程时才加载，加快程序启动速度
    import time
    # 略微等待，让同一批 worker 错峰启动，降低瞬时 CPU 抢占
    time.sleep(0.05)

    # 音频文件不存在则直接标记失败，无需拉起 FFmpeg 进程
    if not os.path.exists(audio_path):
        progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_AUDIO_MISSING))
        return False

    progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_PROCESSING))

    # 提交前再检查一次停止标志，避免白启动子进程
    if stop_event.is_set():
        progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_STOPPED))
        return False

    # 预先探测时长并估算收尾耗时，供主线程计算并显示进度
    duration = get_media_duration(video_path)
    estimated_finalization = estimate_finalization_time(video_path, audio_path, duration)
    progress_queue.put((MSG_FILE_ESTIMATE, video_name, estimated_finalization))
    cmd = build_ffmpeg_command(video_path, audio_path, output_path, ffmpeg_threads)

    try:
        # text=True + bufsize=1：按行读取子进程输出；
        # stdout 用于解析 -progress 进度，stderr 用于收集错误信息
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            bufsize=1,
        )
        stderr_lines = []  # 存放 stderr 输出的每一行

        def _read_err():
            # 持续读取并暂存 stderr，避免管道写满导致 ffmpeg 被阻塞
            try:
                if proc.stderr:
                    for line in proc.stderr:
                        stderr_lines.append(line)
            except Exception:
                pass

        # 用守护线程专门排空 stderr，防止输出较多时与主循环互相等待
        err_thread = threading.Thread(target=_read_err, daemon=True)
        err_thread.start()

        while True:
            # 用户点击"停止"时：先温和 terminate，超时仍未退出则强制 kill
            if stop_event.is_set():
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_STOPPED))
                return False

            if not proc.stdout:
                progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_ERROR))
                break

            # readline 读到空串且进程已结束，说明输出流读完，正常退出循环
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if not line:
                continue

            line = line.strip()
            # -progress 输出的每行都是 "key=value" 形式，非此格式的行直接忽略
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            # out_time_ms：FFmpeg 已处理的毫秒数，换算成百分比
            if key == "out_time_ms" and duration:
                try:
                    current_ms = int(value)
                    # 上限 99%：最后的 moov/mux 收尾阶段不计入 out_time
                    percent = min(99.0, current_ms / 1000.0 / duration * 100.0)
                    progress_queue.put((MSG_FILE_PROGRESS, video_name, percent))
                except ValueError:
                    pass
            # 出现 progress=end 表示 FFmpeg 处理完毕，先把进度固定到 99%
            elif key == "progress" and value == "end" and duration:
                progress_queue.put((MSG_FILE_PROGRESS, video_name, 99.0))

        try:
            # 主循环结束后再回收一次退出码（某些情况下 wait 会抛异常，用 poll 兜底）
            return_code = proc.wait()
        except Exception:
            return_code = proc.poll()

        try:
            # 清空残留输出，确保子进程完全退出
            proc.communicate(timeout=5)
        except Exception:
            try:
                proc.communicate()
            except Exception:
                pass

        try:
            err_thread.join()
        except Exception:
            pass

        stderr_text = "\n".join(stderr_lines).strip()
        if return_code == 0:
            # 返回码为 0 时还要确认输出文件真实存在且非空，才算真正成功
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_DONE))
                progress_queue.put((MSG_FILE_PROGRESS, video_name, 100.0))
                return True
            # ffmpeg 成功但没产出文件（罕见），视为失败
            progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_FAILED))
            if stderr_text:
                progress_queue.put((MSG_FFMPEG_ERROR, video_name, stderr_text))
            return False

        # 返回码非 0：合并失败，附带收集到的 stderr 错误信息
        progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_FAILED))
        if stderr_text:
            progress_queue.put((MSG_FFMPEG_ERROR, video_name, stderr_text))
        return False
    except Exception:
        # Popen 启动或运行阶段抛出异常：回传错误状态与完整堆栈
        tb = traceback.format_exc()
        progress_queue.put((MSG_FILE_STATUS, video_name, STATUS_ERROR))
        progress_queue.put((MSG_FFMPEG_ERROR, video_name, tb))
        return False


def merge_media(folder, progress_queue, stop_event, max_workers):
    """批量合并媒体文件，仅做无损流复制。"""
    files = os.listdir(folder)
    # 以 .mp4 结尾的文件作为"视频"候选（不区分大小写）
    videos = [f for f in files if f.lower().endswith('.mp4')]
    total_videos = len(videos)
    merged_count = 0  # 统计成功合并的数量

    if total_videos == 0:
        # 没有任何可处理的视频时直接报错返回，不进入并行逻辑
        progress_queue.put((MSG_ERROR, "未找到MP4文件"))
        return

    # 合并结果统一输出到源目录下的 output 子文件夹，避免覆盖原文件
    output_folder = os.path.join(folder, "output")
    os.makedirs(output_folder, exist_ok=True)

    # ---- 并发策略 ----
    total_cores = multiprocessing.cpu_count()  # 读取本机 CPU 总核数
    # 并行 worker 数 = 用户设置（默认与 CPU 核数相关），但封顶为线程数上限
    # （默认 8，可由入口 main.pyw 经 configure(max_workers=...) 调整）
    max_workers = max(1, min(_CONFIG_MAX_WORKERS, int(max_workers or max(2, total_cores // 4))))
    # 再把核数平均分给每个 worker 作为其 ffmpeg 的 -threads，
    # 使"worker数 × 线程数"不超过 CPU 总核数，避免过度竞争
    ffmpeg_threads = max(1, total_cores // max_workers)

    progress_queue.put((MSG_LOG, f"找到 {total_videos} 个视频文件"))
    progress_queue.put((MSG_LOG, f"使用 {max_workers} 个线程并行处理\n"))

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for video in videos:
            # 命名约定：abc.mp4 对应的音频必须是同目录下的同名 abc.m4a
            base_name = os.path.splitext(video)[0]
            audio = base_name + '.m4a'
            video_path = os.path.join(folder, video)
            audio_path = os.path.join(folder, audio)
            # 输出到 output 子目录，文件名与原视频保持一致
            output_path = os.path.join(output_folder, video)

            # 用户停止后不再提交新的任务
            if stop_event.is_set():
                break

            progress_queue.put((MSG_FILE_START, video))
            # 提交给线程池执行，并记录 future -> 视频名 的映射，
            # 方便随后按完成顺序统计结果
            future = executor.submit(
                merge_single_media,
                video_path,
                audio_path,
                output_path,
                ffmpeg_threads,
                progress_queue,
                video,
                stop_event,
            )
            futures[future] = video

        # 提交阶段若已被要求停止，直接收尾，不再等待结果
        if stop_event.is_set():
            progress_queue.put((MSG_STOPPED,))
            return

        # as_completed：哪个任务先完成就先处理哪个，进度实时累计
        for future in as_completed(futures):
            if stop_event.is_set():
                break
            if future.result():
                merged_count += 1
            # 每次有文件完成就汇报一次总体进度（百分比、完成数、总数）
            progress_queue.put((MSG_PROGRESS, (merged_count / total_videos) * 100, merged_count, total_videos))

    if not stop_event.is_set():
        # 正常走完（未被停止）才发送"完成"信号
        progress_queue.put((MSG_DONE, merged_count, output_folder))


def start_merge_thread(folder, progress_queue, stop_event, max_workers):
    """在后台线程运行合并任务。"""
    # daemon=True：主程序退出时后台线程随之终止，不会阻塞进程结束
    threading.Thread(target=merge_media, args=(folder, progress_queue, stop_event, max_workers), daemon=True).start()
