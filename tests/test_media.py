"""media.py 后端纯逻辑回归测试（stdlib unittest，零第三方依赖）。

只覆盖纯函数与常量健全性，不真实调用 ffmpeg/ffprobe，也不拉起 GUI。
兼容 Python 3.7+。运行方式（仓库根目录）：
    python3 -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest
from unittest import mock

import media

MSG_NAMES = (
    "MSG_PROGRESS",
    "MSG_FILE_START",
    "MSG_FILE_STATUS",
    "MSG_FILE_PROGRESS",
    "MSG_FILE_ESTIMATE",
    "MSG_DONE",
    "MSG_STOPPED",
    "MSG_ERROR",
    "MSG_FFMPEG_ERROR",
    "MSG_LOG",
)
STATUS_NAMES = (
    "STATUS_QUEUED",
    "STATUS_PROCESSING",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_AUDIO_MISSING",
    "STATUS_ERROR",
    "STATUS_STOPPED",
)


class ConstantsTest(unittest.TestCase):
    """常量健全性：值非空、互不重复，防止手误改坏消息/状态协议。"""

    def test_msg_values_non_empty_and_unique(self):
        values = [getattr(media, name) for name in MSG_NAMES]
        for name, value in zip(MSG_NAMES, values):
            self.assertTrue(value, f"{name} 不应为空")
        self.assertEqual(len(set(values)), len(values), "MSG_* 值不应互相重复")

    def test_status_values_non_empty_and_unique(self):
        values = [getattr(media, name) for name in STATUS_NAMES]
        for name, value in zip(STATUS_NAMES, values):
            self.assertTrue(value, f"{name} 不应为空")
        self.assertEqual(len(set(values)), len(values), "STATUS_* 值不应互相重复")

    def test_msg_status_namespaces_do_not_overlap(self):
        # 消息标签与文件状态取自不同集合，混用会破坏队列分发
        overlap = set(getattr(media, n) for n in MSG_NAMES) & set(
            getattr(media, n) for n in STATUS_NAMES)
        self.assertFalse(overlap, f"MSG_* 与 STATUS_* 不应共用取值: {overlap}")

    def test_protocol_wire_values_kept(self):
        # 协议字符串与历史版本保持一致，防止改动破坏既有消息匹配
        self.assertEqual(media.MSG_FILE_STATUS, "file_status")
        self.assertEqual(media.MSG_FILE_PROGRESS, "file_progress")
        self.assertEqual(media.MSG_DONE, "done")
        self.assertEqual(media.STATUS_QUEUED, "已提交")
        self.assertEqual(media.STATUS_PROCESSING, "处理中")
        self.assertEqual(media.STATUS_AUDIO_MISSING, "未找到音频")


class BuildCommandTest(unittest.TestCase):
    """build_ffmpeg_command 返回的 argv 结构。"""

    def test_argv_starts_with_ffmpeg_path(self):
        cmd = media.build_ffmpeg_command("a.mp4", "a.m4a", "o.mp4", 4)
        self.assertEqual(cmd[0], media.FFMPEG_PATH)

    def test_inputs_output_order_and_key_params(self):
        cmd = media.build_ffmpeg_command("a.mp4", "a.m4a", "o.mp4", 4)

        def positions(arg):
            return [i for i, x in enumerate(cmd) if x == arg]

        i_positions = positions("-i")
        self.assertEqual(len(i_positions), 2, "应恰好有两个 -i 输入")
        self.assertEqual(cmd[i_positions[0] + 1], "a.mp4", "第一个输入应为视频")
        self.assertEqual(cmd[i_positions[1] + 1], "a.m4a", "第二个输入应为音频")

        map_positions = positions("-map")
        self.assertEqual([cmd[i + 1] for i in map_positions], ["0:v:0", "1:a:0"])

        self.assertEqual(cmd[cmd.index("-threads") + 1], "4")
        self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-movflags") + 1], "+faststart")
        # 输出路径必须是最后一个参数（-y 之后），且两个输入都在 map 之前
        self.assertEqual(cmd[-1], "o.mp4")
        self.assertEqual(cmd[cmd.index("-y") + 1], "o.mp4")
        self.assertLess(i_positions[1], cmd.index("-map"))
        self.assertLess(cmd.index("-map"), cmd.index("-y"))


class GetMediaDurationTest(unittest.TestCase):
    """get_media_duration：用 mock 顶替 subprocess.run，不真实调用 ffprobe。"""

    def _fake_run(self, returncode, stdout):
        proc = mock.Mock()
        proc.returncode = returncode
        proc.stdout = stdout
        return proc

    def test_success_parses_float(self):
        with mock.patch("media.subprocess.run", return_value=self._fake_run(0, "12.5\n")):
            self.assertEqual(media.get_media_duration("x.mp4"), 12.5)

    def test_nonzero_returncode_returns_none(self):
        with mock.patch("media.subprocess.run", return_value=self._fake_run(1, "")):
            self.assertIsNone(media.get_media_duration("x.mp4"))

    def test_exception_returns_none(self):
        with mock.patch("media.subprocess.run", side_effect=OSError("boom")):
            self.assertIsNone(media.get_media_duration("x.mp4"))


class EstimateFinalizationTest(unittest.TestCase):
    """estimate_finalization_time：结果被夹紧在 [2.0, 60.0]，无文件兜底不抛错。"""

    def test_regular_files_within_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "a.mp4")
            audio = os.path.join(tmp, "a.m4a")
            for path in (video, audio):
                with open(path, "wb") as f:
                    f.write(b"\x00" * 4096)
            estimate = media.estimate_finalization_time(video, audio, duration=60)
        self.assertGreaterEqual(estimate, 2.0)
        self.assertLessEqual(estimate, 60.0)

    def test_missing_files_do_not_raise(self):
        # 文件不存在且未给时长：get_media_duration 被顶掉返回 None，按 10 分钟兜底
        with mock.patch("media.get_media_duration", return_value=None):
            estimate = media.estimate_finalization_time("/no/v.mp4", "/no/a.m4a")
        self.assertGreaterEqual(estimate, 2.0)
        self.assertLessEqual(estimate, 60.0)

    def test_clamped_to_upper_bound(self):
        # 超长时长 → 估算远超上限，必须被钉在 60.0
        estimate = media.estimate_finalization_time("/no/v.mp4", "/no/a.m4a", duration=1e7)
        self.assertEqual(estimate, 60.0)

    def test_clamped_to_lower_bound(self):
        # 极短时长 + 极小文件 → 估算低于下限，必须被钉在 2.0
        estimate = media.estimate_finalization_time("/no/v.mp4", "/no/a.m4a", duration=1)
        self.assertEqual(estimate, 2.0)


class RecommendedWorkersTest(unittest.TestCase):
    """recommended_workers：与 configure(max_workers=...) 设定的上限的封顶关系。"""

    def setUp(self):
        # 记录模块级配置状态，用例结束后恢复，避免相互污染
        self._snapshot = (media._CONFIG_MAX_WORKERS, media._CONFIG_FFMPEG_PATH, media.FFMPEG_PATH)

    def tearDown(self):
        (media._CONFIG_MAX_WORKERS, media._CONFIG_FFMPEG_PATH, media.FFMPEG_PATH) = self._snapshot

    def _patch_cpu_count(self, cores):
        return mock.patch("media.multiprocessing.cpu_count", return_value=cores)

    def test_many_cores_capped_by_max_workers(self):
        media.configure(max_workers=8)
        with self._patch_cpu_count(128):
            self.assertEqual(media.recommended_workers(), 8)

    def test_configured_lower_cap_limits_workers(self):
        media.configure(max_workers=3)
        with self._patch_cpu_count(128):
            self.assertEqual(media.recommended_workers(), 3)

    def test_low_core_count_floor_of_two(self):
        media.configure(max_workers=8)
        with self._patch_cpu_count(4):
            self.assertEqual(media.recommended_workers(), 2)

    def test_typical_desktop(self):
        media.configure(max_workers=8)
        with self._patch_cpu_count(16):
            self.assertEqual(media.recommended_workers(), 4)


class ConfigureTest(unittest.TestCase):
    """configure()：入口配置注入后端并生效。"""

    def setUp(self):
        self._snapshot = (media._CONFIG_MAX_WORKERS, media._CONFIG_FFMPEG_PATH, media.FFMPEG_PATH)

    def tearDown(self):
        (media._CONFIG_MAX_WORKERS, media._CONFIG_FFMPEG_PATH, media.FFMPEG_PATH) = self._snapshot

    def test_ffmpeg_path_reconfigured(self):
        # 配置一个真实存在的路径（不实际执行），应优先于 PATH 生效
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "ffmpeg-fake")
            with open(fake, "wb") as f:
                f.write(b"# fake ffmpeg\n")
            media.configure(ffmpeg_path=fake)
            cmd = media.build_ffmpeg_command("a.mp4", "a.m4a", "o.mp4", 2)
            self.assertEqual(cmd[0], fake)
            self.assertEqual(media.FFMPEG_PATH, fake)

    def test_nonexistent_configured_path_falls_back_to_path(self):
        media.configure(ffmpeg_path="/no/such/ffmpeg-bin")
        found = __import__("shutil").which("ffmpeg")
        self.assertEqual(media.FFMPEG_PATH, found or "ffmpeg")

    def test_partial_configure_keeps_other_setting(self):
        old_path = media.FFMPEG_PATH
        media.configure(max_workers=4)
        self.assertEqual(media.FFMPEG_PATH, old_path, "只改线程数不应影响 ffmpeg 路径")
        old_cap = media._CONFIG_MAX_WORKERS
        media.configure(ffmpeg_path="/fake/bin/ffmpeg")
        self.assertEqual(media._CONFIG_MAX_WORKERS, old_cap, "只改路径不应影响线程数上限")

    def test_max_workers_floor_at_one(self):
        media.configure(max_workers=0)
        with mock.patch("media.multiprocessing.cpu_count", return_value=128):
            self.assertEqual(media.recommended_workers(), 1)


if __name__ == "__main__":
    unittest.main()
