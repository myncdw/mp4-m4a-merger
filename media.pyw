import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
import threading
import queue
import traceback
from datetime import datetime

FFMPEG_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"  # 请修改为你的 ffmpeg.exe 实际路径


def build_ffmpeg_command(video_path, audio_path, output_path, ffmpeg_threads):
    """构造无损合并所需的 FFmpeg 命令。"""
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
    ffprobe_path = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe.exe")
    if not os.path.exists(ffprobe_path):
        return None

    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except Exception:
        return None


def estimate_finalization_time(video_path, audio_path, duration=None):
    """根据视频长度和文件体积，估算最后封装/收尾所需时间。"""
    if duration is None:
        duration = get_media_duration(video_path)
    if duration is None:
        duration = 600

    video_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0.0
    audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024) if os.path.exists(audio_path) else 0.0
    total_size_mb = max(video_size_mb, 1.0) + max(audio_size_mb, 0.0)
    duration_min = max(duration / 60.0, 1.0)

    estimate_seconds = 1.5 + total_size_mb / 120.0 + duration_min * 0.3
    return round(min(60.0, max(2.0, estimate_seconds)), 1)


def merge_single_media(video_path, audio_path, output_path, ffmpeg_threads, progress_queue, video_name, stop_event):
    """合并单个视频和音频，仅进行无损流复制。"""
    import time
    time.sleep(0.05)

    if not os.path.exists(audio_path):
        progress_queue.put(("file_status", video_name, "未找到音频"))
        return False

    progress_queue.put(("file_status", video_name, "处理中"))

    if stop_event.is_set():
        progress_queue.put(("file_status", video_name, "已停止"))
        return False

    duration = get_media_duration(video_path)
    estimated_finalization = estimate_finalization_time(video_path, audio_path, duration)
    progress_queue.put(("file_estimate", video_name, estimated_finalization))
    cmd = build_ffmpeg_command(video_path, audio_path, output_path, ffmpeg_threads)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            bufsize=1,
        )
        stderr_lines = []

        def _read_err():
            try:
                if proc.stderr:
                    for line in proc.stderr:
                        stderr_lines.append(line)
            except Exception:
                pass

        err_thread = threading.Thread(target=_read_err, daemon=True)
        err_thread.start()

        while True:
            if stop_event.is_set():
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                progress_queue.put(("file_status", video_name, "已停止"))
                return False

            if not proc.stdout:
                progress_queue.put(("file_status", video_name, "错误"))
                break

            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if not line:
                continue

            line = line.strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            if key == "out_time_ms" and duration:
                try:
                    current_ms = int(value)
                    percent = min(99.0, current_ms / 1000.0 / duration * 100.0)
                    progress_queue.put(("file_progress", video_name, percent))
                except ValueError:
                    pass
            elif key == "progress" and value == "end" and duration:
                progress_queue.put(("file_progress", video_name, 99.0))

        try:
            return_code = proc.wait()
        except Exception:
            return_code = proc.poll()

        try:
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
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                progress_queue.put(("file_status", video_name, "完成"))
                progress_queue.put(("file_progress", video_name, 100.0))
                return True
            progress_queue.put(("file_status", video_name, "失败"))
            if stderr_text:
                progress_queue.put(("ffmpeg_error", video_name, stderr_text))
            return False

        progress_queue.put(("file_status", video_name, "失败"))
        if stderr_text:
            progress_queue.put(("ffmpeg_error", video_name, stderr_text))
        return False
    except Exception:
        tb = traceback.format_exc()
        progress_queue.put(("file_status", video_name, "错误"))
        progress_queue.put(("ffmpeg_error", video_name, tb))
        return False


def merge_media(folder, progress_queue, stop_event, max_workers):
    """批量合并媒体文件，仅做无损流复制。"""
    files = os.listdir(folder)
    videos = [f for f in files if f.lower().endswith('.mp4')]
    total_videos = len(videos)
    merged_count = 0

    if total_videos == 0:
        progress_queue.put(("error", "未找到MP4文件"))
        return

    output_folder = os.path.join(folder, "output")
    os.makedirs(output_folder, exist_ok=True)

    total_cores = multiprocessing.cpu_count()
    max_workers = max(1, min(8, int(max_workers or max(2, total_cores // 4))))
    ffmpeg_threads = max(1, total_cores // max_workers)

    progress_queue.put(("log", f"找到 {total_videos} 个视频文件"))
    progress_queue.put(("log", f"使用 {max_workers} 个线程并行处理\n"))

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for video in videos:
            base_name = os.path.splitext(video)[0]
            audio = base_name + '.m4a'
            video_path = os.path.join(folder, video)
            audio_path = os.path.join(folder, audio)
            output_path = os.path.join(output_folder, video)

            if stop_event.is_set():
                break

            progress_queue.put(("file_start", video))
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

        if stop_event.is_set():
            progress_queue.put(("stopped",))
            return

        for future in as_completed(futures):
            if stop_event.is_set():
                break
            if future.result():
                merged_count += 1
            progress_queue.put(("progress", (merged_count / total_videos) * 100, merged_count, total_videos))

    if not stop_event.is_set():
        progress_queue.put(("done", merged_count, output_folder))


def start_merge_thread(folder, progress_queue, stop_event, max_workers):
    """在后台线程运行合并任务。"""
    threading.Thread(target=merge_media, args=(folder, progress_queue, stop_event, max_workers), daemon=True).start()

def select_folder_and_merge():
    """创建 GUI 并处理文件夹选择"""
    root = tk.Tk()
    root.title("视频音频合并器")
    root.geometry("700x550")
    root.resizable(False, False)

    progress_queue = queue.Queue()
    file_items = {}  # 存储每个文件在 Treeview 中的 item id
    file_progresses = {}
    estimate_by_file = {}
    stop_event = threading.Event()
    total_cores = multiprocessing.cpu_count()
    default_workers = min(max(2, total_cores // 4), 8)

    title_label = tk.Label(root, text="视频音频合并工具", font=("微软雅黑", 16, "bold"))
    title_label.pack(pady=10)

    progress_frame = tk.Frame(root)
    progress_frame.pack(pady=10, padx=20, fill=tk.X)

    progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", length=500, mode="determinate")
    progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

    percent_label = tk.Label(progress_frame, text="0%", font=("Arial", 12, "bold"), width=6)
    percent_label.pack(side=tk.LEFT, padx=5)

    status_label = tk.Label(root, text="等待开始...", font=("微软雅黑", 10))
    status_label.pack(pady=5)

    settings_frame = tk.Frame(root)
    settings_frame.pack(pady=(0, 5), anchor="center")

    thread_label = tk.Label(settings_frame, text="线程数：")
    thread_label.pack(side=tk.LEFT)
    thread_var = tk.StringVar(value=str(default_workers))
    thread_entry = ttk.Spinbox(settings_frame, from_=1, to=16, textvariable=thread_var, width=8)
    thread_entry.pack(side=tk.LEFT, padx=(0, 8))
    cpu_label = tk.Label(settings_frame, text=f"CPU总数: {total_cores}")
    cpu_label.pack(side=tk.LEFT, padx=(0, 8))
    reset_thread_btn = tk.Button(settings_frame, text="恢复默认", command=lambda: thread_var.set(str(default_workers)), font=("微软雅黑", 9))
    reset_thread_btn.pack(side=tk.LEFT)

    button_frame = tk.Frame(root)
    button_frame.pack(pady=5, anchor="center")

    def set_controls_state(enabled):
        start_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)
        thread_entry.config(state="normal" if enabled else tk.DISABLED)
        reset_thread_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)
        if enabled:
            stop_btn.config(state=tk.DISABLED)

    def start_merge():
        folder_selected = filedialog.askdirectory(title="选择包含视频和音频的文件夹")
        if folder_selected:
            stop_event.clear()
            progress_bar['value'] = 0
            percent_label.config(text="0%")
            status_label.config(text="正在准备...")
            for item_id in tree.get_children():
                tree.delete(item_id)
            file_items.clear()
            file_progresses.clear()
            estimate_by_file.clear()
            set_controls_state(False)
            stop_btn.config(state=tk.NORMAL)
            start_merge_thread(folder_selected, progress_queue, stop_event, thread_var.get())

    start_btn = tk.Button(
        button_frame,
        text="选择文件夹并开始合并",
        command=start_merge,
        font=("微软雅黑", 11, "bold"),
        bg="#4CAF50",
        fg="white",
        activebackground="#45a049",
        cursor="hand2",
        height=2,
    )
    start_btn.pack(side=tk.LEFT, padx=10, pady=(0, 5))

    stop_btn = tk.Button(
        button_frame,
        text="停止",
        command=lambda: stop_event.set(),
        font=("微软雅黑", 11),
        bg="#f44336",
        fg="white",
        activebackground="#d32f2f",
        cursor="hand2",
        height=2,
    )
    stop_btn.pack(side=tk.LEFT, padx=10)
    stop_btn.config(state=tk.DISABLED)

    info_text = "说明：选择包含 .mp4 和 .m4a 文件的文件夹，程序将自动匹配并进行无损合并"
    info_label = tk.Label(root, text=info_text, font=("微软雅黑", 9), fg="gray")
    info_label.pack(pady=5)

    # 文件状态表格
    table_frame = tk.LabelFrame(root, text="文件状态", font=("微软雅黑", 10))
    table_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(table_frame, columns=("file", "status", "percent"), show="headings", height=12)
    tree.heading("file", text="文件名")
    tree.heading("status", text="状态")
    tree.heading("percent", text="完成率")
    tree.column("file", width=360, anchor="w")
    tree.column("status", width=120, anchor="center")
    tree.column("percent", width=100, anchor="center")
    tree.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

    def update_gui():
        """从 queue 更新进度条和文件表格"""
        try:
            while True:
                item = progress_queue.get_nowait()

                if item[0] == "progress":
                    progress_percent, current, total = item[1], item[2], item[3]
                    if not file_progresses:
                        progress_bar['value'] = progress_percent
                        percent_label.config(text=f"{progress_percent:.0f}%")
                    pending_estimates = [value for value in estimate_by_file.values() if value > 0]
                    if pending_estimates:
                        status_label.config(text=f"已完成: {current}/{total} · 预计收尾: {max(pending_estimates):.1f}s")
                    else:
                        status_label.config(text=f"已完成: {current}/{total}")

                elif item[0] == "file_start":
                    video_name = item[1]
                    file_progresses[video_name] = 0.0
                    estimate_by_file[video_name] = 0.0
                    item_id = tree.insert("", tk.END, values=(video_name, "已提交", "0%"))
                    file_items[video_name] = item_id

                elif item[0] == "file_status":
                    video_name, status = item[1], item[2]
                    if video_name in file_items:
                        item_id = file_items[video_name]
                        if status == "处理中":
                            tree.set(item_id, "status", "处理中")
                        elif status == "完成":
                            tree.set(item_id, "status", "完成")
                            tree.set(item_id, "percent", "100%")
                            file_progresses[video_name] = 100.0
                            estimate_by_file[video_name] = 0.0
                        elif status == "失败":
                            tree.set(item_id, "status", "失败")
                            file_progresses[video_name] = 100.0
                            estimate_by_file[video_name] = 0.0
                        elif status == "未找到音频":
                            tree.set(item_id, "status", "未找到音频")
                            file_progresses[video_name] = 100.0
                            estimate_by_file[video_name] = 0.0
                        elif status == "错误":
                            tree.set(item_id, "status", "错误")
                            file_progresses[video_name] = 100.0
                            estimate_by_file[video_name] = 0.0
                        elif status == "已停止":
                            tree.set(item_id, "status", "已停止")
                            file_progresses[video_name] = 100.0
                            estimate_by_file[video_name] = 0.0

                elif item[0] == "file_progress":
                    video_name, percent = item[1], item[2]
                    if video_name in file_items:
                        item_id = file_items[video_name]
                        file_progresses[video_name] = percent
                        tree.set(item_id, "percent", f"{percent:.0f}%")
                        current_status = tree.set(item_id, "status")
                        if current_status in {"已提交", "处理中"}:
                            tree.set(item_id, "status", "处理中")

                        total_progress = sum(file_progresses.values()) / max(1, len(file_progresses))
                        progress_bar['value'] = total_progress
                        percent_label.config(text=f"{total_progress:.0f}%")
                        pending_estimates = [value for value in estimate_by_file.values() if value > 0]
                        if pending_estimates:
                            status_label.config(text=f"总体进度: {total_progress:.0f}% ({sum(1 for p in file_progresses.values() if p >= 100)}/{len(file_progresses)}) · 预计收尾: {max(pending_estimates):.1f}s")
                        else:
                            status_label.config(text=f"总体进度: {total_progress:.0f}% ({sum(1 for p in file_progresses.values() if p >= 100)}/{len(file_progresses)})")

                elif item[0] == "file_estimate":
                    video_name, estimate = item[1], item[2]
                    estimate_by_file[video_name] = estimate

                elif item[0] == "done":
                    merged_count, output_folder = item[1], item[2]
                    status_label.config(text="处理完成！")
                    messagebox.showinfo("完成", f"已合并 {merged_count} 个文件\n保存位置：{output_folder}")
                    set_controls_state(True)
                    file_items.clear()
                    file_progresses.clear()
                    estimate_by_file.clear()

                elif item[0] == "stopped":
                    status_label.config(text="已停止")
                    messagebox.showinfo("已停止", "合并已停止")
                    set_controls_state(True)
                    file_items.clear()
                    file_progresses.clear()
                    estimate_by_file.clear()

                elif item[0] == "error":
                    messagebox.showerror("错误", item[1])
                    status_label.config(text="发生错误")
                    set_controls_state(True)
                elif item[0] == "ffmpeg_error":
                    video_name, err = item[1], item[2]
                    # 显示较短的错误摘要，并记录完整错误到脚本目录下的日志文件
                    summary = err.splitlines()[:6]
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    log_path = os.path.join(script_dir, "ffmpeg_error.log")
                    messagebox.showerror("FFmpeg 错误", f"{video_name}: {summary[0] if summary else '未知错误'}\n(详细日志已写入 {log_path})")
                    try:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"=== {video_name} @ {datetime.now().isoformat()} ===\n")
                            f.write(err + "\n\n")
                    except Exception:
                        pass

        except queue.Empty:
            pass
        root.after(100, update_gui)  # 每 100ms 检查一次 queue

    root.after(100, update_gui)
    root.mainloop()

if __name__ == "__main__":
    select_folder_and_merge()