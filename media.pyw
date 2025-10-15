import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
import threading
import queue

FFMPEG_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"  # 请修改为你的ffmpeg.exe实际路径

def merge_single_media(video_path, audio_path, output_path, ffmpeg_threads, progress_queue, video_name):
    """合并单个视频和音频"""
    # 稍微延迟一下，确保GUI先处理"已提交"消息
    import time
    time.sleep(0.05)
    
    if not os.path.exists(audio_path):
        progress_queue.put(("file_status", video_name, "未找到音频"))
        return False
    
    # 更新状态为处理中
    progress_queue.put(("file_status", video_name, "处理中"))
    
    cmd = [
        FFMPEG_PATH,
        '-i', video_path,
        '-i', audio_path,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-threads', str(ffmpeg_threads),
        '-y',
        output_path
    ]
    
    try:
        # 防止弹出黑窗口
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        
        if result.returncode == 0:
            progress_queue.put(("file_status", video_name, "完成"))
            return True
        else:
            progress_queue.put(("file_status", video_name, "失败"))
            return False
    except Exception as e:
        progress_queue.put(("file_status", video_name, "错误"))
        return False

def merge_media(folder, progress_queue):
    """多线程合并媒体文件，并通过 queue 更新 GUI"""
    files = os.listdir(folder)
    videos = [f for f in files if f.lower().endswith('.mp4')]
    total_videos = len(videos)
    merged_count = 0

    if total_videos == 0:
        progress_queue.put(("error", "未找到MP4文件"))
        return

    # 输出文件夹
    output_folder = os.path.join(folder, "output")
    os.makedirs(output_folder, exist_ok=True)

    # 线程数控制：最少 2，最多 10，如果 CPU 核心数的一半小于 10，则用其值
    total_cores = multiprocessing.cpu_count()
    max_workers = min(max(2, total_cores // 2), 10)

    # 每个 FFmpeg 内部线程
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
            
            # 任务提交
            progress_queue.put(("file_start", video))
            future = executor.submit(merge_single_media, video_path, audio_path, output_path, 
                                   ffmpeg_threads, progress_queue, video)
            futures[future] = video

        for i, future in enumerate(as_completed(futures), 1):
            if future.result():
                merged_count += 1
            progress_percent = (i / total_videos) * 100
            progress_queue.put(("progress", progress_percent, i, total_videos))

    progress_queue.put(("done", merged_count, output_folder))

def start_merge_thread(folder, progress_queue):
    """在后台线程运行合并任务"""
    threading.Thread(target=merge_media, args=(folder, progress_queue), daemon=True).start()

def select_folder_and_merge():
    """创建 GUI 并处理文件夹选择"""
    root = tk.Tk()
    root.title("视频音频合并器")
    root.geometry("700x550")
    root.resizable(False, False)

    progress_queue = queue.Queue()
    file_lines = {}  # 存储每个文件的日志行号

    # 标题
    title_label = tk.Label(root, text="视频音频合并工具", font=("微软雅黑", 16, "bold"))
    title_label.pack(pady=10)

    # 进度框架
    progress_frame = tk.Frame(root)
    progress_frame.pack(pady=10, padx=20, fill=tk.X)

    # 进度条
    progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", length=500, mode="determinate")
    progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # 百分比标签
    percent_label = tk.Label(progress_frame, text="0%", font=("Arial", 12, "bold"), width=6)
    percent_label.pack(side=tk.LEFT, padx=5)

    # 状态标签
    status_label = tk.Label(root, text="等待开始...", font=("微软雅黑", 10))
    status_label.pack(pady=5)

    # 日志框架
    log_frame = tk.LabelFrame(root, text="处理日志", font=("微软雅黑", 10))
    log_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)

    log_text = scrolledtext.ScrolledText(log_frame, width=80, height=15, font=("Consolas", 9))
    log_text.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

    def update_gui():
        """从 queue 更新进度条和日志"""
        try:
            while True:
                item = progress_queue.get_nowait()
                
                if item[0] == "progress":
                    progress_percent, current, total = item[1], item[2], item[3]
                    progress_bar['value'] = progress_percent
                    percent_label.config(text=f"{progress_percent:.0f}%")
                    status_label.config(text=f"总进度: {current}/{total}")
                    
                elif item[0] == "log":
                    log_text.insert(tk.END, item[1] + "\n")
                    log_text.see(tk.END)
                    
                elif item[0] == "file_start":
                    video_name = item[1]
                    log_text.insert(tk.END, f"[ 已提交 ] {video_name}\n")
                    log_text.see(tk.END)
                    # 记录这个文件的行号（在插入后立即获取）
                    line_num = int(log_text.index("end-2c").split('.')[0])
                    file_lines[video_name] = line_num
                    
                elif item[0] == "file_status":
                    video_name, status = item[1], item[2]
                    if video_name in file_lines:
                        line_num = file_lines[video_name]
                        # 更新对应行的内容
                        log_text.delete(f"{line_num}.0", f"{line_num}.end")
                        
                        if status == "处理中":
                            log_text.insert(f"{line_num}.0", f"[ 处理中 ] {video_name}")
                        elif status == "完成":
                            log_text.insert(f"{line_num}.0", f"[ ✓ 完成 ] {video_name}")
                        elif status == "失败":
                            log_text.insert(f"{line_num}.0", f"[ ✗ 失败 ] {video_name}")
                        elif status == "未找到音频":
                            log_text.insert(f"{line_num}.0", f"[ ✗ 未找到音频 ] {video_name}")
                        elif status == "错误":
                            log_text.insert(f"{line_num}.0", f"[ ✗ 错误 ] {video_name}")
                        
                        log_text.see(tk.END)
                        
                elif item[0] == "done":
                    merged_count, output_folder = item[1], item[2]
                    status_label.config(text="处理完成！")
                    log_text.insert(tk.END, f"\n{'='*60}\n")
                    log_text.insert(tk.END, f"所有任务完成！成功合并 {merged_count} 个文件\n")
                    log_text.see(tk.END)
                    messagebox.showinfo("完成", f"已合并 {merged_count} 个文件\n保存位置：{output_folder}")
                    start_btn.config(state=tk.NORMAL)
                    file_lines.clear()
                    
                elif item[0] == "error":
                    messagebox.showerror("错误", item[1])
                    status_label.config(text="发生错误")
                    start_btn.config(state=tk.NORMAL)
                    
        except queue.Empty:
            pass
        root.after(100, update_gui)  # 每 100ms 检查一次 queue

    def start_merge():
        folder_selected = filedialog.askdirectory(title="选择包含视频和音频的文件夹")
        if folder_selected:
            progress_bar['value'] = 0
            percent_label.config(text="0%")
            status_label.config(text="正在准备...")
            log_text.delete(1.0, tk.END)
            file_lines.clear()
            start_btn.config(state=tk.DISABLED)
            start_merge_thread(folder_selected, progress_queue)

    # 开始按钮
    start_btn = tk.Button(root, text="选择文件夹并开始合并", command=start_merge, 
                         font=("微软雅黑", 11, "bold"), bg="#4CAF50", fg="white",
                         activebackground="#45a049", cursor="hand2", height=2)
    start_btn.pack(pady=15)

    # 说明文本
    info_text = "说明：选择包含 .mp4 和 .m4a 文件的文件夹，程序会自动匹配并合并"
    info_label = tk.Label(root, text=info_text, font=("微软雅黑", 9), fg="gray")
    info_label.pack(pady=5)

    root.after(100, update_gui)
    root.mainloop()

if __name__ == "__main__":
    select_folder_and_merge()