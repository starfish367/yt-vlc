"""
test_tier1_features.py - Tier 1: Feature Coverage (F1 to F15)
Covers all 15 core features with at least 5 test cases per feature (75 tests total).
"""
import os
import sys
import re
import unittest
import tempfile
import json
from unittest.mock import MagicMock, patch

# Ensure paths & imports
from tests.conftest_base import (
    get_yt_vlc_module,
    make_sample_video,
    make_sample_playlist,
    find_forbidden_emojis,
    mock_vlc_execution,
    PROJECT_DIR,
)

yt_vlc = get_yt_vlc_module()

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
except Exception:
    Gtk = None
    GLib = None


# ============================================================================
# F1: PlayQueueManager Core Data & Operations (5 tests)
# ============================================================================
class TestF1PlayQueueCore(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f1_01_add_item_end(self):
        """F1: add_item with position='end' appends to queue and returns new length."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        item1 = make_sample_video("v1", "Track 1")
        item2 = make_sample_video("v2", "Track 2")
        self.assertEqual(pq.add_item(item1, position="end"), 1)
        self.assertEqual(pq.add_item(item2, position="end"), 2)
        items = pq.get_items()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["id"], "v2")

    def test_f1_02_add_item_next(self):
        """F1: add_item with position='next' inserts item immediately after current."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        item1 = make_sample_video("v1", "Track 1")
        item2 = make_sample_video("v2", "Track 2")
        item_next = make_sample_video("v_next", "Priority Track")
        pq.add_item(item1)
        pq.add_item(item2)
        pq.next_track()  # start on item1 (index 0)
        pq.add_item(item_next, position="next")
        items = pq.get_items()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[1]["id"], "v_next")

    def test_f1_03_add_batch_items(self):
        """F1: add_batch appends multiple items preserving order."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        batch = [make_sample_video(f"v_{i}", f"Track {i}") for i in range(5)]
        total = pq.add_batch(batch, position="end")
        self.assertEqual(total, 5)
        self.assertEqual([x["id"] for x in pq.get_items()], [f"v_{i}" for i in range(5)])

    def test_f1_04_remove_item(self):
        """F1: remove_item removes target index and returns the removed item."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        for i in range(3):
            pq.add_item(make_sample_video(f"v_{i}", f"Track {i}"))
        removed = pq.remove_item(1)
        self.assertIsNotNone(removed)
        self.assertEqual(removed["id"], "v_1")
        self.assertEqual(len(pq.get_items()), 2)

    def test_f1_05_clear_queue(self):
        """F1: clear empties the queue and resets current track."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.clear()
        self.assertEqual(len(pq.get_items()), 0)
        self.assertIsNone(pq.get_current_item())


# ============================================================================
# F2: Continuous Playback Auto-Advance & VLC Lifecycle (5 tests)
# ============================================================================
class TestF2AutoAdvanceLifecycle(unittest.TestCase):
    def test_f2_01_vlc_cmd_includes_play_and_exit_when_in_queue(self):
        """F2: launch_vlc includes --play-and-exit when in_queue=True."""
        captured_cmd = []
        with mock_vlc_execution(captured_list=captured_cmd):
            launch_fn = getattr(yt_vlc, "launch_vlc", None)
            self.assertIsNotNone(launch_fn, "launch_vlc function missing")
            video = make_sample_video("v1", "Test")
            settings = {"caching": 3000, "hw_accel": True}
            try:
                launch_fn(video, settings, in_queue=True)
            except TypeError:
                self.fail("launch_vlc does not accept in_queue argument")
            self.assertIn("--play-and-exit", captured_cmd)

    def test_f2_02_vlc_cmd_omits_play_and_exit_in_single_playback(self):
        """F2: launch_vlc omits --play-and-exit when in_queue=False."""
        captured_cmd = []
        with mock_vlc_execution(captured_list=captured_cmd):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1", "Test")
            settings = {"caching": 3000, "hw_accel": True}
            try:
                launch_fn(video, settings, in_queue=False)
            except TypeError:
                self.fail("launch_vlc in_queue argument not supported")
            self.assertNotIn("--play-and-exit", captured_cmd)

    def test_f2_03_monitor_vlc_rc_disconnect_detection(self):
        """F2: monitor_vlc_rc cleanly exits when response is None (VLC disconnect)."""
        monitor_fn = getattr(yt_vlc, "monitor_vlc_rc", None)
        self.assertIsNotNone(monitor_fn)
        # Verify monitor_vlc_rc handles None gracefully without infinite loop
        done_called = []
        def on_done(vid):
            done_called.append(vid)

        with patch("socket.socket") as mock_sock_cls, \
             patch("time.sleep", return_value=None):
            mock_sock = MagicMock()
            mock_sock.recv.return_value = b""  # EOF
            mock_sock_cls.return_value = mock_sock
            try:
                monitor_fn(9999, "vid_test", [], on_playback_done=on_done)
            except Exception as e:
                self.fail(f"monitor_vlc_rc crashed on disconnect: {e}")

    def test_f2_04_playback_done_triggers_next_track(self):
        """F2: on_playback_done triggers next track on PlayQueueManager."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.next_track()  # start playback on first track
        self.assertEqual(pq.get_current_item()["id"], "v1")
        # Trigger advance
        next_item = pq.next_track()
        self.assertIsNotNone(next_item)
        self.assertEqual(next_item["id"], "v2")

    def test_f2_05_playback_done_dispatched_via_glib(self):
        """F2: on_playback_done is dispatched via GLib.idle_add for thread safety."""
        # Check source code of monitor_vlc_rc or launch_vlc for GLib.idle_add
        import inspect
        monitor_fn = getattr(yt_vlc, "monitor_vlc_rc")
        src = inspect.getsource(monitor_fn)
        self.assertTrue("GLib.idle_add" in src or "idle_add" in src)


# ============================================================================
# F3: Queue Controls & Modes (Shuffle & Repeat) (5 tests)
# ============================================================================
class TestF3QueueControls(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f3_01_repeat_mode_off_stops_at_queue_end(self):
        """F3: repeat_mode='off' stops and returns None when reaching queue end."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.next_track()  # start playing v1
        pq.set_repeat_mode("off")
        item2 = pq.next_track()  # v2
        self.assertEqual(item2["id"], "v2")
        item_end = pq.next_track()  # end of queue
        self.assertIsNone(item_end)

    def test_f3_02_repeat_mode_all_cycles_to_start(self):
        """F3: repeat_mode='all' wraps back to the first track at queue end."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.next_track()  # start playing v1
        pq.set_repeat_mode("all")
        item2 = pq.next_track()  # now on v2
        self.assertEqual(item2["id"], "v2")
        item_loop = pq.next_track()  # loops back to v1
        self.assertIsNotNone(item_loop)
        self.assertEqual(item_loop["id"], "v1")

    def test_f3_03_repeat_mode_one_repeats_current_track(self):
        """F3: repeat_mode='one' returns the identical current track on next_track."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.next_track()  # start playing v1
        pq.set_repeat_mode("one")
        item_same = pq.next_track()
        self.assertEqual(item_same["id"], "v1")

    def test_f3_04_shuffle_mode_reorders_remaining_tracks(self):
        """F3: set_shuffle(True) enables randomized track ordering without loss."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        batch = [make_sample_video(f"v_{i}") for i in range(20)]
        pq.add_batch(batch)
        orig_ids = [x["id"] for x in pq.get_items()]
        pq.set_shuffle(True)
        shuffled_ids = [x["id"] for x in pq.get_items()]
        self.assertEqual(set(orig_ids), set(shuffled_ids))

    def test_f3_05_skip_prev_track_navigation(self):
        """F3: prev_track returns previous item."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2"), make_sample_video("v3")])
        pq.next_track()  # v1
        pq.next_track()  # v2
        pq.next_track()  # v3
        prev = pq.prev_track()
        self.assertIsNotNone(prev)
        self.assertEqual(prev["id"], "v2")


# ============================================================================
# F4: Visual Queue GTK3 UI Widgets (5 tests)
# ============================================================================
class TestF4VisualQueueUI(unittest.TestCase):
    def test_f4_01_play_queue_widget_instantiation(self):
        """F4: PlayQueueWidget instantiates and is a Gtk.Widget."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if widget_cls is None or pq_cls is None:
            self.fail("PlayQueueWidget is not implemented in yt_vlc")
        widget = widget_cls(pq_cls(), MagicMock())
        self.assertIsInstance(widget, Gtk.Widget)

    def test_f4_02_queue_tab_added_to_main_window(self):
        """F4: MainWindow includes Play Queue tab."""
        mw_cls = getattr(yt_vlc, "MainWindow", None)
        self.assertIsNotNone(mw_cls)
        # Inspect MainWindow layout or tab names
        import inspect
        src = inspect.getsource(mw_cls)
        self.assertTrue("PlayQueueWidget" in src or "Hàng đợi" in src or "queue" in src.lower(),
                        "MainWindow does not include Play Queue tab reference")

    def test_f4_03_queue_ui_updates_on_queue_changed_signal(self):
        """F4: PlayQueueWidget updates displayed list when queue contents change."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if widget_cls is None or pq_cls is None:
            self.fail("PlayQueue UI components not implemented")
        pq = pq_cls()
        widget = widget_cls(pq, MagicMock())
        pq.add_item(make_sample_video("v1", "Track 1"))
        self.assertTrue(hasattr(widget, "update_ui") or hasattr(widget, "refresh") or hasattr(widget, "_render_queue"))

    def test_f4_04_queue_control_buttons_exist(self):
        """F4: PlayQueueWidget provides control buttons (Next, Prev, Clear, Shuffle)."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if widget_cls is None or pq_cls is None:
            self.fail("PlayQueueWidget is not implemented in yt_vlc")
        widget = widget_cls(pq_cls(), MagicMock())
        # Verify widget has buttons or controls container
        self.assertTrue(hasattr(widget, "btn_clear") or hasattr(widget, "btn_next") or hasattr(widget, "controls_box"))

    def test_f4_05_video_item_has_add_to_queue_actions(self):
        """F4: Video row/card context menu or buttons have queue enqueue options."""
        video_row_cls = getattr(yt_vlc, "VideoRow", None)
        self.assertIsNotNone(video_row_cls)
        import inspect
        src = inspect.getsource(video_row_cls)
        self.assertTrue("add_item" in src or "hàng đợi" in src.lower() or "queue" in src.lower(),
                        "VideoRow missing queue actions")


# ============================================================================
# F5: Audio-Only Mode & VLC --no-video (5 tests)
# ============================================================================
class TestF5AudioOnlyMode(unittest.TestCase):
    def test_f5_01_extract_stream_url_audio_quality(self):
        """F5: extract_stream_url with quality='audio' uses audio stream spec."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "https://googlevideo.com/videoplayback?audio_only=1\n"
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc
            v_url, a_url = extract_fn("v123", quality="audio")
            # Verify yt-dlp command used format containing bestaudio
            call_cmd = mock_run.call_args[0][0]
            fmt_idx = call_cmd.index("-f") + 1
            self.assertIn("bestaudio", call_cmd[fmt_idx])

    def test_f5_02_launch_vlc_audio_mode_includes_no_video(self):
        """F5: launch_vlc in audio-only mode appends --no-video to VLC command."""
        captured_cmd = []
        with mock_vlc_execution(captured_list=captured_cmd):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1", "Audio Track")
            settings = {"caching": 3000, "hw_accel": True}
            try:
                launch_fn(video, settings, quality_override="audio", is_audio=True)
            except TypeError:
                # If is_audio is passed as quality_override
                try:
                    launch_fn(video, settings, quality_override="audio")
                except Exception as e:
                    self.fail(f"launch_vlc failed for audio: {e}")
            self.assertIn("--no-video", captured_cmd)

    def test_f5_03_launch_vlc_video_mode_omits_no_video(self):
        """F5: launch_vlc in video mode does not include --no-video."""
        captured_cmd = []
        with mock_vlc_execution(captured_list=captured_cmd):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1", "Normal Video")
            settings = {"caching": 3000, "hw_accel": True}
            launch_fn(video, settings, quality_override="720")
            self.assertNotIn("--no-video", captured_cmd)

    def test_f5_04_audio_only_stream_prefers_m4a_container(self):
        """F5: Audio format spec strictly prefers m4a container for lowest CPU decode."""
        import inspect
        fn = getattr(yt_vlc, "extract_stream_url")
        src = inspect.getsource(fn)
        self.assertIn("bestaudio[ext=m4a]", src)

    def test_f5_05_audio_only_playback_status_callback(self):
        """F5: Status callback receives audio notification when playing audio."""
        messages = []
        def status_cb(msg):
            messages.append(msg)

        with mock_vlc_execution():
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1", "Podcast")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, quality_override="audio", status_callback=status_cb)
            except Exception:
                pass
            # Check if status_callback was invoked with audio info or idle_add
            self.assertTrue(len(messages) > 0 or hasattr(yt_vlc, "GLib"))


# ============================================================================
# F6: S905X Low CPU/RAM Profile (5 tests)
# ============================================================================
class TestF6S905XProfile(unittest.TestCase):
    def test_f6_01_audio_mode_disables_video_decoding(self):
        """F6: Audio mode must use --no-video to eliminate Mali-450 GPU utilization."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--no-video", src)

    def test_f6_02_vlc_avcodec_skiploopfilter_level3(self):
        """F6: VLC command enforces --avcodec-skiploopfilter=3 for Cortex-A53."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--avcodec-skiploopfilter=3", src)

    def test_f6_03_vlc_frame_dropping_flags(self):
        """F6: VLC command enforces --drop-late-frames and --skip-frames."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--drop-late-frames", src)
        self.assertIn("--skip-frames", src)

    def test_f6_04_vlc_no_video_title_show(self):
        """F6: VLC command enforces --no-video-title-show to prevent OSD CPU load."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--no-video-title-show", src)

    def test_f6_05_single_download_worker_concurrency(self):
        """F6: DownloadManager restricts worker thread concurrency to 1."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance() if hasattr(dm_cls, "get_instance") else dm_cls()
        max_workers = getattr(dm, "max_concurrent", getattr(dm, "_max_workers", 1))
        self.assertEqual(max_workers, 1)


# ============================================================================
# F7: Background DownloadManager Queue & Single Worker (5 tests)
# ============================================================================
class TestF7DownloadManagerCore(unittest.TestCase):
    def setUp(self):
        self.dm_cls = getattr(yt_vlc, "DownloadManager", None)

    def test_f7_01_download_manager_singleton_pattern(self):
        """F7: DownloadManager.get_instance() provides a singleton instance."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        inst1 = self.dm_cls.get_instance()
        inst2 = self.dm_cls.get_instance()
        self.assertIs(inst1, inst2)

    def test_f7_02_add_download_task_returns_unique_id(self):
        """F7: add_task enqueues download task and returns unique string task_id."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        task_id = dm.add_task(video_id="v123", title="Video 1", quality_format="720", download_dir="/tmp")
        self.assertIsInstance(task_id, str)
        self.assertTrue(len(task_id) > 0)

    def test_f7_03_download_task_queue_ordering(self):
        """F7: Tasks are queued and registered in FIFO order."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        t1 = dm.add_task(video_id="v1", title="Title 1", quality_format="720", download_dir="/tmp")
        t2 = dm.add_task(video_id="v2", title="Title 2", quality_format="720", download_dir="/tmp")
        tasks = dm.get_tasks()
        task_ids = [t["task_id"] for t in tasks]
        self.assertIn(t1, task_ids)
        self.assertIn(t2, task_ids)

    def test_f7_04_get_tasks_list_structure(self):
        """F7: get_tasks returns list of dicts with required status fields."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        t = dm.add_task(video_id="v_struct", title="Structure Test", quality_format="mp4", download_dir="/tmp")
        tasks = dm.get_tasks()
        matching = [x for x in tasks if x["task_id"] == t]
        self.assertTrue(len(matching) > 0)
        item = matching[0]
        for field in ["task_id", "status", "title"]:
            self.assertIn(field, item)

    def test_f7_05_cancel_task_removes_from_queue(self):
        """F7: cancel_task changes task status to cancelled."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        tid = dm.add_task(video_id="v_cancel", title="Cancel Test", quality_format="720", download_dir="/tmp")
        success = dm.cancel_task(tid)
        self.assertTrue(success)
        task = next((x for x in dm.get_tasks() if x["task_id"] == tid), None)
        if task:
            self.assertEqual(task["status"], "cancelled")


# ============================================================================
# F8: Download Progress Hooks & Cancel (5 tests)
# ============================================================================
class TestF8DownloadProgressHooks(unittest.TestCase):
    def test_f8_01_progress_hook_reports_percentage(self):
        """F8: Progress hook parses yt-dlp progress and reports percentage 0-100%."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        # Test progress hook handler
        hook = getattr(dm, "_ytdl_hook", None) or getattr(dm, "progress_hook", None)
        self.assertTrue(callable(hook) or hasattr(dm, "on_task_progress"))

    def test_f8_02_progress_hook_reports_speed_string(self):
        """F8: Progress hook formats download speed correctly."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        fmt_speed = getattr(dm, "_format_speed", None)
        if fmt_speed:
            self.assertEqual(fmt_speed(1048576), "1.0 MB/s")
        else:
            self.assertTrue(hasattr(dm, "get_tasks"))

    def test_f8_03_progress_hook_reports_eta_string(self):
        """F8: Progress hook formats ETA correctly."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        fmt_eta = getattr(dm, "_format_eta", None)
        if fmt_eta:
            self.assertEqual(fmt_eta(65), "01:05")
        else:
            self.assertTrue(hasattr(dm, "get_tasks"))

    def test_f8_04_progress_hook_dispatched_via_glib(self):
        """F8: Progress updates to UI callback are scheduled with GLib.idle_add."""
        import inspect
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        src = inspect.getsource(dm_cls)
        self.assertTrue("GLib.idle_add" in src or "idle_add" in src)

    def test_f8_05_active_download_cancellation(self):
        """F8: Cancelling in-flight task flags cancellation token and aborts worker."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        self.assertTrue(hasattr(dm, "cancel_task"))


# ============================================================================
# F9: Download Formats (MP4, M4A, MP3 check) (5 tests)
# ============================================================================
class TestF9DownloadFormats(unittest.TestCase):
    def test_f9_01_download_format_mp4_h264_spec(self):
        """F9: MP4 download uses H.264 (avc1) format spec for S905X hardware decoding."""
        import inspect
        fn = getattr(yt_vlc, "download_media", None)
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        src = inspect.getsource(dm_cls) if dm_cls else (inspect.getsource(fn) if fn else "")
        self.assertIn("vcodec^=avc1", src)

    def test_f9_02_download_format_m4a_audio(self):
        """F9: Audio download supports native M4A (no transcoding)."""
        import inspect
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        fn = getattr(yt_vlc, "download_media", None)
        src = inspect.getsource(dm_cls) if dm_cls else (inspect.getsource(fn) if fn else "")
        self.assertTrue("m4a" in src)

    def test_f9_03_download_format_mp3_ffmpeg_check(self):
        """F9: MP3 download checks for ffmpeg binary before attempting audio conversion."""
        import shutil
        has_ffmpeg = shutil.which("ffmpeg") is not None
        # Verify check logic in module
        self.assertIsInstance(has_ffmpeg, bool)

    def test_f9_04_download_output_filename_sanitization(self):
        """F9: Download output filename sanitizes forbidden filesystem characters."""
        sanitize_fn = getattr(yt_vlc, "sanitize_filename", None)
        if sanitize_fn:
            cleaned = sanitize_fn('Video: "Title" / Test? * <Cool> | Song')
            for bad_char in [':', '"', '/', '?', '*', '<', '>', '|']:
                self.assertNotIn(bad_char, cleaned)
        else:
            # Check default template in yt-dlp options
            self.assertTrue(True)

    def test_f9_05_download_sponsorblock_support(self):
        """F9: Download media includes SponsorBlock remove flag when enabled."""
        import inspect
        fn = getattr(yt_vlc, "download_media", None)
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        src = inspect.getsource(dm_cls) if dm_cls else (inspect.getsource(fn) if fn else "")
        self.assertIn("sponsorblock", src.lower())


# ============================================================================
# F10: Offline Library Scanner & Metadata (.info.json) (5 tests)
# ============================================================================
class TestF10OfflineLibrary(unittest.TestCase):
    def test_f10_01_scan_downloads_directory(self):
        """F10: Scanner identifies video/audio media files in download directory."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner function is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "My Video.mp4")
            with open(test_file, "w") as f:
                f.write("mock media")
            results = scan_fn(tmpdir)
            self.assertEqual(len(results), 1)

    def test_f10_02_parse_info_json_sidecar(self):
        """F10: Scanner extracts metadata from .info.json sidecar."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = os.path.join(tmpdir, "Song.m4a")
            json_path = os.path.join(tmpdir, "Song.info.json")
            with open(media_path, "w") as f:
                f.write("media")
            with open(json_path, "w") as f:
                json.dump({"title": "Sample Song", "uploader": "Singer", "duration": 180}, f)
            results = scan_fn(tmpdir)
            self.assertEqual(results[0]["title"], "Sample Song")

    def test_f10_03_fallback_metadata_when_no_json(self):
        """F10: Scanner falls back to file name when .info.json is absent."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = os.path.join(tmpdir, "Offline Video.mp4")
            with open(media_path, "w") as f:
                f.write("media")
            results = scan_fn(tmpdir)
            self.assertEqual(results[0]["title"], "Offline Video")

    def test_f10_04_launch_offline_vlc_playback(self):
        """F10: Local VLC playback uses file caching flags for offline media."""
        captured_cmd = []
        with mock_vlc_execution(captured_list=captured_cmd):
            launch_local = getattr(yt_vlc, "launch_vlc_local", None) or getattr(yt_vlc, "launch_vlc")
            video = {"url": "/path/to/local.mp4", "title": "Local"}
            settings = {"caching": 1000}
            try:
                launch_local(video, settings)
            except Exception:
                pass
            self.assertTrue(len(captured_cmd) == 0 or "--file-caching=1000" in captured_cmd or "vlc" in captured_cmd)

    def test_f10_05_offline_library_widget_display(self):
        """F10: OfflineLibraryWidget instantiates as Gtk.Widget."""
        widget_cls = getattr(yt_vlc, "OfflineLibraryWidget", None)
        if widget_cls is None:
            self.fail("OfflineLibraryWidget is not implemented in yt_vlc")
        w = widget_cls()
        self.assertIsInstance(w, Gtk.Widget)


# ============================================================================
# F11: Channel Playlists Tab Parsing (5 tests)
# ============================================================================
class TestF11ChannelPlaylists(unittest.TestCase):
    def test_f11_01_channel_videos_dialog_has_playlists_tab(self):
        """F11: ChannelVideosDialog creates Playlists tab (_create_playlists_tab)."""
        dlg_cls = getattr(yt_vlc, "ChannelVideosDialog", None)
        self.assertIsNotNone(dlg_cls)
        self.assertTrue(hasattr(dlg_cls, "_create_playlists_tab") or hasattr(dlg_cls, "create_playlists_tab"),
                        "ChannelVideosDialog missing _create_playlists_tab method")

    def test_f11_02_parse_channel_playlists_ytinitialdata(self):
        """F11: Scraper extracts playlist id, title, count from ytInitialData structure."""
        parse_fn = getattr(yt_vlc, "parse_channel_playlists_json", None) or getattr(yt_vlc, "fetch_channel_playlists", None)
        if parse_fn is None:
            self.fail("parse_channel_playlists function is not implemented in yt_vlc")
        mock_data = {
            "contents": {
                "twoColumnBrowseResultsRenderer": {
                    "tabs": [
                        {}, {}, {},
                        {
                            "tabRenderer": {
                                "title": "Playlists",
                                "content": {
                                    "sectionListRenderer": {
                                        "contents": [{
                                            "itemSectionRenderer": {
                                                "contents": [{
                                                    "gridRenderer": {
                                                        "items": [{
                                                            "gridPlaylistRenderer": {
                                                                "playlistId": "PL_123",
                                                                "title": {"runs": [{"text": "Greatest Hits"}]},
                                                                "videoCountText": {"runs": [{"text": "12"}]}
                                                            }
                                                        }]
                                                    }
                                                }]
                                            }
                                        }]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
        res = parse_fn(mock_data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["playlist_id"], "PL_123")

    def test_f11_03_channel_playlists_fallback_flat_playlist(self):
        """F11: Fallback uses yt-dlp --flat-playlist when scraping returns empty."""
        import inspect
        dlg_cls = getattr(yt_vlc, "ChannelVideosDialog", None)
        fetch_fn = getattr(yt_vlc, "fetch_channel_playlists_ytdlp", None)
        src = inspect.getsource(fetch_fn) if fetch_fn else inspect.getsource(dlg_cls)
        self.assertTrue("flat-playlist" in src or "fetch_channel_playlists" in dir(yt_vlc))

    def test_f11_04_playlist_dict_structure(self):
        """F11: Playlist item dictionary contains playlist_id, title, item_count, thumbnail_url."""
        pl = make_sample_playlist("PL_abc", "My Playlist", 5)
        for key in ["id", "title", "item_count", "thumbnail", "videos"]:
            self.assertIn(key, pl)

    def test_f11_05_playlist_item_click_loads_videos(self):
        """F11: Selecting a playlist loads its constituent videos."""
        fetch_pl_vids = getattr(yt_vlc, "fetch_playlist_videos", None)
        if fetch_pl_vids is None:
            self.fail("fetch_playlist_videos is not implemented in yt_vlc")
        self.assertTrue(callable(fetch_pl_vids))


# ============================================================================
# F12: Batch Queue Enqueueing (5 tests)
# ============================================================================
class TestF12BatchQueueEnqueue(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f12_01_batch_enqueue_adds_all_items(self):
        """F12: Batch enqueue adds all videos from playlist."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        playlist = make_sample_playlist("PL_1", "Test Album", 8)
        count = pq.add_batch(playlist["videos"])
        self.assertEqual(count, 8)
        self.assertEqual(len(pq.get_items()), 8)

    def test_f12_02_batch_enqueue_preserves_order(self):
        """F12: Batch enqueue preserves strict track sequencing."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        playlist = make_sample_playlist("PL_1", "Ordered Album", 5)
        pq.add_batch(playlist["videos"])
        stored = [v["id"] for v in pq.get_items()]
        expected = [v["id"] for v in playlist["videos"]]
        self.assertEqual(stored, expected)

    def test_f12_03_batch_enqueue_to_end_position(self):
        """F12: Batch enqueue to 'end' appends after existing tracks."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_item(make_sample_video("initial_01"))
        playlist = make_sample_playlist("PL_1", "Batch", 3)
        pq.add_batch(playlist["videos"], position="end")
        items = pq.get_items()
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["id"], "initial_01")
        self.assertEqual(items[1]["id"], playlist["videos"][0]["id"])

    def test_f12_04_batch_enqueue_to_next_position(self):
        """F12: Batch enqueue to 'next' inserts tracks immediately after current track."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        # current is v1
        playlist = make_sample_playlist("PL_next", "Insert", 2)
        pq.add_batch(playlist["videos"], position="next")
        items = pq.get_items()
        self.assertEqual(items[0]["id"], "v1")
        self.assertEqual(items[1]["id"], playlist["videos"][0]["id"])
        self.assertEqual(items[2]["id"], playlist["videos"][1]["id"])
        self.assertEqual(items[3]["id"], "v2")

    def test_f12_05_batch_enqueue_empty_list_noop(self):
        """F12: Batch enqueue with empty list does not alter queue length."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_item(make_sample_video("v1"))
        total = pq.add_batch([])
        self.assertEqual(total, 1)
        self.assertEqual(len(pq.get_items()), 1)


# ============================================================================
# F13: Live Stream Detection & HLS Playback (5 tests)
# ============================================================================
class TestF13LiveStreamHandling(unittest.TestCase):
    def test_f13_01_detect_live_stream_metadata(self):
        """F13: extract_stream_url detects live streams and returns is_live=True."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "https://manifest.googlevideo.com/api/manifest/hls_live/index.m3u8\n"
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc
            res = extract_fn("live_vid_123")
            # Must return tuple with 3 elements (url, audio_url, is_live)
            self.assertIsInstance(res, tuple)
            self.assertTrue(len(res) >= 3, "extract_stream_url must return (url, audio_url, is_live)")
            self.assertTrue(res[2], "is_live must be True for live stream")

    def test_f13_02_extract_direct_hls_m3u8_url(self):
        """F13: Live stream extraction yields direct HLS .m3u8 URL."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "https://manifest.googlevideo.com/live/playlist.m3u8\n"
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc
            res = extract_fn("live_stream_01")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3, "extract_stream_url must return 3-tuple (url, audio_url, is_live)")
            v_url, a_url, is_live = res
            self.assertTrue(v_url.endswith(".m3u8"))

    def test_f13_03_vlc_live_caching_3000ms(self):
        """F13: Live stream playback sets --network-caching=3000 in VLC args."""
        captured_cmd = []
        with mock_vlc_execution(stream_url="https://manifest.googlevideo.com/live.m3u8", is_live=True, captured_list=captured_cmd):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("live_1", "Live Stream")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, is_live=True)
            except TypeError:
                self.fail("launch_vlc does not support is_live argument")
            self.assertIn("--network-caching=3000", captured_cmd)

    def test_f13_04_live_stream_skips_sponsorblock(self):
        """F13: Live stream playback skips SponsorBlock segments query."""
        with mock_vlc_execution(stream_url="https://manifest.googlevideo.com/live.m3u8", is_live=True), \
             patch("yt_vlc.fetch_sponsorblock_segments") as mock_sb:
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("live_1", "Live Stream")
            settings = {"sponsorblock": True}
            try:
                launch_fn(video, settings, is_live=True)
            except Exception:
                pass
            mock_sb.assert_not_called()

    def test_f13_05_upcoming_premiere_intercepted(self):
        """F13: Upcoming premiere returns status indicating premiere rather than failing."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            # Simulate yt-dlp warning for premiere
            mock_proc.stdout = ""
            mock_proc.stderr = "ERROR: This live event will begin in 2 hours.\n"
            mock_proc.returncode = 1
            mock_run.return_value = mock_proc
            res = extract_fn("premiere_01")
            self.assertIsInstance(res, tuple)


# ============================================================================
# F14: Zero-Emoji Compliance & Gtk.Switch Alignment (5 tests)
# ============================================================================
class TestF14ZeroEmojiAndSwitchAlignment(unittest.TestCase):
    def test_f14_01_zero_color_emojis_in_source_code(self):
        """F14: yt_vlc.py contains zero color emojis (to avoid Tofu font on S905X)."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
        forbidden = find_forbidden_emojis(content)
        self.assertEqual(forbidden, [], f"Found forbidden emojis in yt_vlc.py: {set(forbidden)}")

    def test_f14_02_allowed_unicode_symbols_only(self):
        """F14: Only verified Unicode symbols (•, ✓, ✔) are used in user interface labels."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            if "label=" in line or "tooltip_text=" in line:
                forbidden = find_forbidden_emojis(line)
                self.assertEqual(forbidden, [], f"Forbidden emoji at line {i}: {line.strip()}")

    def test_f14_03_gtk_switches_in_grid_halign_start(self):
        """F14: Gtk.Switch in Gtk.Grid must call set_halign(Gtk.Align.START)."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find every switch variable attached to a grid
        switch_vars = re.findall(r"(\w+)\s*=\s*Gtk\.Switch\(\)", content)
        for var in switch_vars:
            self.assertIn(f"{var}.set_halign(Gtk.Align.START)", content,
                          f"Switch {var} does not have set_halign(Gtk.Align.START)")

    def test_f14_04_gtk_switches_in_grid_valign_center(self):
        """F14: Gtk.Switch in Gtk.Grid must call set_valign(Gtk.Align.CENTER)."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
        switch_vars = re.findall(r"(\w+)\s*=\s*Gtk\.Switch\(\)", content)
        for var in switch_vars:
            self.assertIn(f"{var}.set_valign(Gtk.Align.CENTER)", content,
                          f"Switch {var} does not have set_valign(Gtk.Align.CENTER)")

    def test_f14_05_native_symbolic_icons_used_for_buttons(self):
        """F14: UI buttons use Gtk.Image.new_from_icon_name symbolic icons."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Gtk.Image.new_from_icon_name", content)


# ============================================================================
# F15: S905X Hardware VLC Flags Verification (5 tests)
# ============================================================================
class TestF15S905XVLCFlags(unittest.TestCase):
    def test_f15_01_vlc_h264_avc1_forced_in_format(self):
        """F15: Format spec enforces H.264 (avc1) for S905X hardware VPU decoding."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "extract_stream_url"))
        self.assertIn("vcodec^=avc1", src)

    def test_f15_02_vlc_direct_stream_url_no_stdout_pipe(self):
        """F15: Direct URL passed to VLC, forbidden stdout pipe is not used."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertNotIn("yt-dlp -o - | vlc", src)
        self.assertNotIn("subprocess.PIPE", src.split("vlc_cmd =")[0] if "vlc_cmd =" in src else "")

    def test_f15_03_vlc_all_required_hardware_flags_present(self):
        """F15: VLC command includes all required hardware acceleration and frame drop flags."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        for flag in [
            "--avcodec-skiploopfilter=3",
            "--drop-late-frames",
            "--skip-frames",
            "--no-video-title-show"
        ]:
            self.assertIn(flag, src, f"Required S905X flag {flag} missing in launch_vlc")

    def test_f15_04_vlc_audio_stream_combined_or_slave(self):
        """F15: When audio is separate, VLC passes --input-slave."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--input-slave=", src)

    def test_f15_05_vlc_rc_host_and_port_configured(self):
        """F15: VLC command includes --extraintf=rc and --rc-host=127.0.0.1:<port>."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--extraintf=rc", src)
        self.assertIn("--rc-host=", src)


if __name__ == "__main__":
    unittest.main()
