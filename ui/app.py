"""GUI 应用：MediaMergerApp。

包含窗口布局、控件构建、消息队列轮询与分发、文件状态表格、
错误弹窗与日志落盘等全部 UI 关注点。

依赖方向（单向）：ui.app -> media / dialogs / ui.theme；
本文件不包含任何合并/调度逻辑（见 media.py），消息协议常量
（media.MSG_*/media.STATUS_*）集中定义在后端 media.py。
"""
import os
import queue
import threading
import multiprocessing
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime

import dialogs
import media
from ui import theme


class MediaMergerApp(tk.Tk):
    """视频音频合并器主窗口（自身即 Tk 根窗口，无需额外 root）。"""

    def __init__(self, default_folder=""):
        """主窗口。

        default_folder：文件选择对话框的默认打开目录；由入口 main.pyw 的
        DEFAULT_FOLDER 传入（空字符串表示使用系统默认位置）。
        """
        super().__init__()
        self.default_folder = default_folder
        self.title("视频音频合并器")
        self.geometry("700x550")
        self.resizable(False, False)  # 固定窗口大小，简化布局

        # ------------------------------------------------------------------
        # 线程间通信的数据结构：
        #  progress_queue：工作线程 -> 主线程的唯一通道，元素为消息元组，如
        #    (media.MSG_PROGRESS, 总体百分比, 已完成数, 总数)
        #    (media.MSG_FILE_START / media.MSG_FILE_STATUS /
        #     media.MSG_FILE_PROGRESS / media.MSG_FILE_ESTIMATE, 视频名, ...)
        #    (media.MSG_DONE, 完成数, 输出目录) /
        #    (media.MSG_STOPPED,) / (media.MSG_ERROR / media.MSG_FFMPEG_ERROR, ...)
        #  file_items：视频名 -> Treeview 行 id，便于按名更新某一行
        #  file_progresses：视频名 -> 当前百分比，用于求整体平均进度
        #  estimate_by_file：视频名 -> 预计收尾秒数，用于状态栏提示
        #  stop_event：点击"停止"后置位，各工作线程据此中断任务
        # ------------------------------------------------------------------
        self.progress_queue = queue.Queue()
        self.file_items = {}  # 存储每个文件在 Treeview 中的 item id
        self.file_progresses = {}
        self.estimate_by_file = {}
        self.stop_event = threading.Event()

        self.total_cores = multiprocessing.cpu_count()
        # 默认并行度 = min(上限, CPU核数/4)，且至少为 2（与 media.merge_media 同源）
        self.default_workers = media.recommended_workers()
        self.thread_var = tk.StringVar(value=str(self.default_workers))

        self._build_widgets()
        self.after(100, self._drain_queue)

    # ------------------- 界面布局（自上而下） -------------------
    def _build_widgets(self):
        # 第 1 行：主标题
        title_label = tk.Label(self, text="视频音频合并工具", font=theme.FONT_TITLE)
        title_label.pack(pady=10)

        # 第 2 行：整体进度条 + 百分比
        progress_frame = tk.Frame(self)
        progress_frame.pack(pady=10, padx=20, fill=tk.X)

        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", length=500, mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.percent_label = tk.Label(progress_frame, text="0%", font=theme.FONT_PERCENT, width=6)
        self.percent_label.pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(self, text="等待开始...", font=theme.FONT_NORMAL)
        self.status_label.pack(pady=5)

        # 第 3 行：并行线程数设置区（含 CPU 信息与恢复默认按钮）
        settings_frame = tk.Frame(self)
        settings_frame.pack(pady=(0, 5), anchor="center")

        thread_label = tk.Label(settings_frame, text="线程数：")
        thread_label.pack(side=tk.LEFT)
        # Spinbox 允许用户在 1~16 之间手动输入/选择并发任务数
        self.thread_entry = ttk.Spinbox(settings_frame, from_=1, to=16, textvariable=self.thread_var, width=8)
        self.thread_entry.pack(side=tk.LEFT, padx=(0, 8))
        cpu_label = tk.Label(settings_frame, text=f"CPU总数: {self.total_cores}")
        cpu_label.pack(side=tk.LEFT, padx=(0, 8))
        # 一键把线程数恢复为自动计算的默认值
        self.reset_thread_btn = tk.Button(
            settings_frame,
            text="恢复默认",
            command=lambda: self.thread_var.set(str(self.default_workers)),
            font=theme.FONT_SMALL,
        )
        self.reset_thread_btn.pack(side=tk.LEFT)

        # 第 4 行：主要操作按钮（开始合并 / 停止）
        button_frame = tk.Frame(self)
        button_frame.pack(pady=5, anchor="center")

        self.start_btn = tk.Button(
            button_frame,
            text="选择文件夹并开始合并",
            command=self._start_merge,
            font=theme.FONT_BTN_BOLD,
            bg=theme.COLOR_START_BG,
            fg="white",
            activebackground=theme.COLOR_START_ACTIVE,
            cursor="hand2",
            height=2,
        )
        self.start_btn.pack(side=tk.LEFT, padx=10, pady=(0, 5))

        self.stop_btn = tk.Button(
            button_frame,
            text="停止",
            command=self._stop,
            font=theme.FONT_BTN,
            bg=theme.COLOR_STOP_BG,
            fg="white",
            activebackground=theme.COLOR_STOP_ACTIVE,
            cursor="hand2",
            height=2,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=10)
        self.stop_btn.config(state=tk.DISABLED)

        info_text = "说明：选择包含 .mp4 和 .m4a 文件的文件夹，程序将自动匹配并进行无损合并"
        info_label = tk.Label(self, text=info_text, font=theme.FONT_SMALL, fg=theme.COLOR_INFO_FG)
        info_label.pack(pady=5)

        # ---------------- 文件状态表格 ----------------
        # 每一行对应一个待合并的视频：显示文件名、当前状态、完成率三列
        table_frame = tk.LabelFrame(self, text="文件状态", font=theme.FONT_TABLE)
        table_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)

        # show="headings"：隐藏第一列行号，只显示表头
        self.tree = ttk.Treeview(table_frame, columns=("file", "status", "percent"), show="headings", height=12)
        self.tree.heading("file", text="文件名")
        self.tree.heading("status", text="状态")
        self.tree.heading("percent", text="完成率")
        self.tree.column("file", width=360, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("percent", width=100, anchor="center")
        self.tree.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

    # ------------------- 控件状态 -------------------
    def set_controls_state(self, enabled):
        """切换控件可用状态：任务运行时锁定"开始"与设置，结束后解锁并禁用"停止"。"""
        self.start_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)
        self.thread_entry.config(state="normal" if enabled else tk.DISABLED)
        self.reset_thread_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)
        if enabled:
            self.stop_btn.config(state=tk.DISABLED)

    # ------------------- 用户动作 -------------------
    def _start_merge(self):
        """选择文件夹并启动新一轮合并。"""
        # 弹窗选择文件夹；取消时返回空串，直接跳过本次操作
        folder_selected = dialogs.choose_folder(
            initial_dir=self.default_folder,
            title="选择包含视频和音频的文件夹",
        )
        if folder_selected:
            # ---- 重置上一轮任务留下的状态 ----
            self.stop_event.clear()  # 确保停止标志为未触发状态
            self.progress_bar['value'] = 0
            self.percent_label.config(text="0%")
            self.status_label.config(text="正在准备...")
            # 清空状态表格与各项记录，为新一轮任务做准备
            for item_id in self.tree.get_children():
                self.tree.delete(item_id)
            self.file_items.clear()
            self.file_progresses.clear()
            self.estimate_by_file.clear()
            # 任务期间锁定"开始/线程数/恢复默认"，只保留"停止"可点
            self.set_controls_state(False)
            self.stop_btn.config(state=tk.NORMAL)
            # 在独立后台线程中执行合并，避免阻塞 Tk 主循环导致界面卡死
            media.start_merge_thread(folder_selected, self.progress_queue, self.stop_event, self.thread_var.get())

    def _stop(self):
        """点击"停止"：置位停止事件，各工作线程据此中断任务。"""
        self.stop_event.set()

    # ------------------- 消息队列分发（主线程轮询） -------------------
    def _drain_queue(self):
        """从 queue 更新进度条和文件表格。"""
        # Tkinter 控件只能在主线程中更新，因此工作线程绝不直接碰控件，
        # 而是把消息塞进队列；本函数由 after 定时驱动、逐条取出处理。
        try:
            # 一次性把当前队列中的全部消息处理完
            while True:
                item = self.progress_queue.get_nowait()
                tag = item[0]
                if tag == media.MSG_PROGRESS:
                    self._on_progress(item[1], item[2], item[3])
                elif tag == media.MSG_FILE_START:
                    self._on_file_start(item[1])
                elif tag == media.MSG_FILE_STATUS:
                    self._on_file_status(item[1], item[2])
                elif tag == media.MSG_FILE_PROGRESS:
                    self._on_file_progress(item[1], item[2])
                elif tag == media.MSG_FILE_ESTIMATE:
                    self._on_file_estimate(item[1], item[2])
                elif tag == media.MSG_DONE:
                    self._on_done(item[1], item[2])
                elif tag == media.MSG_STOPPED:
                    self._on_stopped()
                elif tag == media.MSG_ERROR:
                    self._on_error(item[1])
                elif tag == media.MSG_FFMPEG_ERROR:
                    self._on_ffmpeg_error(item[1], item[2])
                # media.MSG_LOG 为历史遗留消息，GUI 从未消费——保持不处理，行为不变
        except queue.Empty:
            pass  # 队列暂时为空属正常现象，下次轮询再检查
        self.after(100, self._drain_queue)  # 每 100ms 重复调度自身，实现周期性刷新

    # ---- 总体进度（media.MSG_PROGRESS） ----
    def _on_progress(self, progress_percent, current, total):
        if not self.file_progresses:
            self.progress_bar['value'] = progress_percent
            self.percent_label.config(text=f"{progress_percent:.0f}%")
        pending_estimates = [value for value in self.estimate_by_file.values() if value > 0]
        if pending_estimates:
            self.status_label.config(text=f"已完成: {current}/{total} · 预计收尾: {max(pending_estimates):.1f}s")
        else:
            self.status_label.config(text=f"已完成: {current}/{total}")

    # ---- 单个文件开始（media.MSG_FILE_START） ----
    def _on_file_start(self, video_name):
        self.file_progresses[video_name] = 0.0
        self.estimate_by_file[video_name] = 0.0
        # 在表格末尾插入新行，初始状态为"已提交"
        item_id = self.tree.insert("", tk.END, values=(video_name, media.STATUS_QUEUED, "0%"))
        self.file_items[video_name] = item_id

    # ---- 单个文件状态变化（media.MSG_FILE_STATUS） ----
    def _on_file_status(self, video_name, status):
        if video_name not in self.file_items:
            return
        item_id = self.file_items[video_name]
        if status == media.STATUS_PROCESSING:
            self.tree.set(item_id, "status", media.STATUS_PROCESSING)
        elif status == media.STATUS_DONE:
            # 完成后把该行进度钉死为 100%，并从估算表中移除
            self.tree.set(item_id, "status", media.STATUS_DONE)
            self.tree.set(item_id, "percent", "100%")
            self.file_progresses[video_name] = 100.0
            self.estimate_by_file[video_name] = 0.0
        elif status == media.STATUS_FAILED:
            self.tree.set(item_id, "status", media.STATUS_FAILED)
            self.file_progresses[video_name] = 100.0
            self.estimate_by_file[video_name] = 0.0
        elif status == media.STATUS_AUDIO_MISSING:
            self.tree.set(item_id, "status", media.STATUS_AUDIO_MISSING)
            self.file_progresses[video_name] = 100.0
            self.estimate_by_file[video_name] = 0.0
        elif status == media.STATUS_ERROR:
            self.tree.set(item_id, "status", media.STATUS_ERROR)
            self.file_progresses[video_name] = 100.0
            self.estimate_by_file[video_name] = 0.0
        elif status == media.STATUS_STOPPED:
            self.tree.set(item_id, "status", media.STATUS_STOPPED)
            self.file_progresses[video_name] = 100.0
            self.estimate_by_file[video_name] = 0.0

    # ---- 单个文件实时进度（media.MSG_FILE_PROGRESS） ----
    def _on_file_progress(self, video_name, percent):
        if video_name not in self.file_items:
            return
        item_id = self.file_items[video_name]
        self.file_progresses[video_name] = percent
        self.tree.set(item_id, "percent", f"{percent:.0f}%")
        # 只要还在变化就标记为"处理中"
        current_status = self.tree.set(item_id, "status")
        if current_status in {media.STATUS_QUEUED, media.STATUS_PROCESSING}:
            self.tree.set(item_id, "status", media.STATUS_PROCESSING)

        # 顶栏进度 = 所有文件进度的平均值
        total_progress = sum(self.file_progresses.values()) / max(1, len(self.file_progresses))
        self.progress_bar['value'] = total_progress
        self.percent_label.config(text=f"{total_progress:.0f}%")
        pending_estimates = [value for value in self.estimate_by_file.values() if value > 0]
        if pending_estimates:
            self.status_label.config(
                text=f"总体进度: {total_progress:.0f}% ({sum(1 for p in self.file_progresses.values() if p >= 100)}/{len(self.file_progresses)}) · 预计收尾: {max(pending_estimates):.1f}s")
        else:
            self.status_label.config(
                text=f"总体进度: {total_progress:.0f}% ({sum(1 for p in self.file_progresses.values() if p >= 100)}/{len(self.file_progresses)})")

    # ---- 收尾时间估算（media.MSG_FILE_ESTIMATE） ----
    def _on_file_estimate(self, video_name, estimate):
        self.estimate_by_file[video_name] = estimate

    # ---- 任务正常完成（media.MSG_DONE） ----
    def _on_done(self, merged_count, output_folder):
        self.status_label.config(text="处理完成！")
        messagebox.showinfo("完成", f"已合并 {merged_count} 个文件\n保存位置：{output_folder}")
        # 结束后复位控件，允许开始下一轮任务
        self.set_controls_state(True)
        self.file_items.clear()
        self.file_progresses.clear()
        self.estimate_by_file.clear()

    # ---- 任务被用户停止（media.MSG_STOPPED） ----
    def _on_stopped(self):
        self.status_label.config(text="已停止")
        messagebox.showinfo("已停止", "合并已停止")
        self.set_controls_state(True)
        self.file_items.clear()
        self.file_progresses.clear()
        self.estimate_by_file.clear()

    # ---- 全局性错误（media.MSG_ERROR） ----
    def _on_error(self, message):
        # 例如所选文件夹中没有任何 MP4 文件
        messagebox.showerror("错误", message)
        self.status_label.config(text="发生错误")
        self.set_controls_state(True)

    # ---- FFmpeg 运行错误（media.MSG_FFMPEG_ERROR） ----
    def _on_ffmpeg_error(self, video_name, err):
        # 弹窗只显示前几行摘要，完整错误写入日志文件便于排查
        log_path = os.path.join(media.PROJECT_DIR, "ffmpeg_error.log")
        summary = err.splitlines()[:6]
        messagebox.showerror(
            "FFmpeg 错误",
            f"{video_name}: {summary[0] if summary else '未知错误'}\n(详细日志已写入 {log_path})",
        )
        self._write_ffmpeg_error_log(video_name, err)

    def _write_ffmpeg_error_log(self, video_name, err):
        """以追加模式把带时间戳的错误记录写入仓库根目录的 ffmpeg_error.log。"""
        log_path = os.path.join(media.PROJECT_DIR, "ffmpeg_error.log")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"=== {video_name} @ {datetime.now().isoformat()} ===\n")
                f.write(err + "\n\n")
        except Exception:
            pass

    def main(self):
        """进入 Tk 事件循环，等待用户操作。"""
        self.mainloop()
