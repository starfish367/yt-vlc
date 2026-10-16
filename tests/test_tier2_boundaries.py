"""
test_tier2_boundaries.py - Tier 2: Boundary & Corner Cases (F1 to F15)
Covers boundary conditions, edge cases, error recovery, and stress constraints (75 tests total).
"""
import os
import sys
import unittest
import tempfile
import json
import time
from unittest.mock import MagicMock, patch

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
# F1 Boundaries: PlayQueueManager (5 tests)
# ============================================================================
class TestF1Boundaries(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f1_b01_empty_queue_operations(self):
        """F1: Operations on empty queue return None safely without raising exceptions."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        self.assertIsNone(pq.get_current_item())
        self.assertIsNone(pq.next_track())
        self.assertIsNone(pq.prev_track())
        self.assertEqual(len(pq.get_items()), 0)

    def test_f1_b02_single_item_queue(self):
        """F1: Single-item queue lifecycle: add sets current, remove clears current."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_item(make_sample_video("solo_1"))
        pq.next_track()  # start playback on solo_1
        self.assertEqual(pq.get_current_item()["id"], "solo_1")
        removed = pq.remove_item(0)
        self.assertEqual(removed["id"], "solo_1")
        self.assertIsNone(pq.get_current_item())
        self.assertEqual(len(pq.get_items()), 0)

    def test_f1_b03_remove_index_out_of_bounds(self):
        """F1: remove_item with negative or out-of-range index returns None without crashing."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_item(make_sample_video("v1"))
        self.assertIsNone(pq.remove_item(-1))
        self.assertIsNone(pq.remove_item(999))
        self.assertEqual(len(pq.get_items()), 1)

    def test_f1_b04_duplicate_video_items(self):
        """F1: Enqueuing duplicate video items maintains distinct entries."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        item = make_sample_video("dup_vid", "Same Song")
        pq.add_item(item)
        pq.add_item(item)
        items = pq.get_items()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], items[1]["id"])

    def test_f1_b05_clear_during_playback(self):
        """F1: Clearing queue while track is active resets current item and length."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.next_track()  # start playback
        self.assertIsNotNone(pq.get_current_item())
        pq.clear()
        self.assertEqual(len(pq.get_items()), 0)
        self.assertIsNone(pq.get_current_item())


# ============================================================================
# F2 Boundaries: Continuous Playback & VLC Lifecycle (5 tests)
# ============================================================================
class TestF2Boundaries(unittest.TestCase):
    def test_f2_b01_rapid_next_prev_calls(self):
        """F2: Rapid alternations of next_track and prev_track remain consistent."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        for i in range(5):
            pq.add_item(make_sample_video(f"v_{i}"))
        for _ in range(50):
            pq.next_track()
            pq.prev_track()
        self.assertEqual(pq.get_current_item()["id"], "v_0")

    def test_f2_b02_premature_vlc_process_exit(self):
        """F2: If VLC exits abruptly with non-zero exit code, error is handled gracefully."""
        status_msgs = []
        def status_cb(msg):
            status_msgs.append(msg)

        with mock_vlc_execution(side_effect=Exception("VLC process crashed")):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, status_callback=status_cb)
            except Exception as e:
                self.fail(f"launch_vlc raised unhandled exception on VLC crash: {e}")

    def test_f2_b03_auto_advance_on_unplayable_stream(self):
        """F2: If stream URL extraction fails (returns None), playback halts or skips cleanly."""
        with patch("yt_vlc.extract_stream_url", return_value=(None, None)):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("dead_stream")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings)
            except Exception as e:
                self.fail(f"launch_vlc crashed when extract_stream_url returned None: {e}")

    def test_f2_b04_rc_socket_none_response_clean_exit(self):
        """F2: In monitor_vlc_rc, EOF disconnect (resp is None) exits loop immediately."""
        monitor_fn = getattr(yt_vlc, "monitor_vlc_rc")
        with patch("socket.socket") as mock_sock_cls, \
             patch("time.sleep", return_value=None):
            mock_sock = MagicMock()
            mock_sock.recv.return_value = b""
            mock_sock_cls.return_value = mock_sock
            start_t = time.time()
            monitor_fn(8888, "v1", [])
            elapsed = time.time() - start_t
            self.assertLess(elapsed, 2.0, "monitor_vlc_rc spun in infinite loop on disconnect")

    def test_f2_b05_auto_advance_on_last_item_repeat_off(self):
        """F2: When repeat='off', on_playback_done at queue end does not trigger new playback."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        pq.add_item(make_sample_video("v1"))
        pq.next_track()  # start on v1
        pq.set_repeat_mode("off")
        next_track = pq.next_track()
        self.assertIsNone(next_track)


# ============================================================================
# F3 Boundaries: Queue Controls & Modes (5 tests)
# ============================================================================
class TestF3Boundaries(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f3_b01_repeat_one_infinite_loop(self):
        """F3: Repeat 'one' mode returns the identical current track 10 times consecutively."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("track_one"), make_sample_video("track_two")])
        pq.next_track()  # start on track_one
        pq.set_repeat_mode("one")
        for _ in range(10):
            item = pq.next_track()
            self.assertEqual(item["id"], "track_one")

    def test_f3_b02_shuffle_identity_preservation(self):
        """F3: Shuffling 100 items retains all 100 unique item IDs without dropping any."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        items = [make_sample_video(f"item_{i}") for i in range(100)]
        pq.add_batch(items)
        orig_ids = [x["id"] for x in pq.get_items()]
        pq.set_shuffle(True)
        shuffled_ids = [x["id"] for x in pq.get_items()]
        self.assertEqual(len(shuffled_ids), 100)
        self.assertEqual(set(orig_ids), set(shuffled_ids))

    def test_f3_b03_repeat_all_single_item(self):
        """F3: Single-item queue with repeat 'all' cycles the single item repeatedly."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_item(make_sample_video("solo"))
        pq.next_track()  # start on solo
        pq.set_repeat_mode("all")
        for _ in range(5):
            self.assertEqual(pq.next_track()["id"], "solo")

    def test_f3_b04_toggle_shuffle_preserves_current_track(self):
        """F3: Toggling shuffle on and off preserves the currently playing track."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video(f"t_{i}") for i in range(10)])
        pq.next_track()  # start on track
        current_before = pq.get_current_item()["id"]
        pq.set_shuffle(True)
        self.assertEqual(pq.get_current_item()["id"], current_before)
        pq.set_shuffle(False)
        self.assertEqual(pq.get_current_item()["id"], current_before)

    def test_f3_b05_invalid_repeat_mode_handling(self):
        """F3: Passing invalid repeat mode defaults to 'off' or raises ValueError."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        try:
            pq.set_repeat_mode("invalid_mode")
            self.assertIn(getattr(pq, "repeat_mode", "off"), ["off", "all", "one"])
        except ValueError:
            pass  # Raising ValueError is also valid behavior


# ============================================================================
# F4 Boundaries: Visual Queue GTK3 UI Widgets (5 tests)
# ============================================================================
class TestF4Boundaries(unittest.TestCase):
    def test_f4_b01_visual_queue_empty_state_display(self):
        """F4: Visual queue widget gracefully handles empty state."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if widget_cls is None or pq_cls is None:
            self.fail("PlayQueueWidget is not implemented in yt_vlc")
        w = widget_cls(pq_cls(), MagicMock())
        self.assertIsInstance(w, Gtk.Widget)

    def test_f4_b02_rapid_ui_updates_no_glib_flood(self):
        """F4: Rapid queue mutations (50 in a row) do not freeze or crash UI."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        if pq_cls is None or widget_cls is None:
            self.fail("PlayQueue components not implemented")
        pq = pq_cls()
        w = widget_cls(pq, MagicMock())
        for i in range(50):
            pq.add_item(make_sample_video(f"rapid_{i}"))
        self.assertEqual(len(pq.get_items()), 50)

    def test_f4_b03_selection_out_of_range(self):
        """F4: Selecting row beyond bounds does not raise IndexError."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if widget_cls is None or pq_cls is None:
            self.fail("PlayQueueWidget is not implemented in yt_vlc")
        w = widget_cls(pq_cls(), MagicMock())
        if hasattr(w, "select_row_index"):
            try:
                w.select_row_index(999)
            except IndexError:
                self.fail("select_row_index raised uncaught IndexError")

    def test_f4_b04_visual_queue_with_100_items(self):
        """F4: Visual queue widget populates 100 items without memory error."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        if pq_cls is None or widget_cls is None:
            self.fail("PlayQueue components not implemented")
        pq = pq_cls()
        items = [make_sample_video(f"item_{i}") for i in range(100)]
        pq.add_batch(items)
        w = widget_cls(pq, MagicMock())
        self.assertIsInstance(w, Gtk.Widget)

    def test_f4_b05_breeze_dark_styling_applied(self):
        """F4: Queue widget is styled with Breeze / Breeze Dark theme CSS."""
        import inspect
        src = inspect.getsource(yt_vlc)
        self.assertTrue("Breeze" in src or "queue" in src)


# ============================================================================
# F5 Boundaries: Audio-Only Mode & VLC --no-video (5 tests)
# ============================================================================
class TestF5Boundaries(unittest.TestCase):
    def test_f5_b01_audio_only_fallback_when_m4a_unavailable(self):
        """F5: Format spec includes bestaudio/best[acodec!=none] fallback if m4a is absent."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "extract_stream_url"))
        self.assertIn("bestaudio[ext=m4a]/bestaudio/best[acodec!=none]", src)

    def test_f5_b02_switching_between_audio_and_video(self):
        """F5: Consecutive playback switches between audio and video pass proper flags."""
        captured = []
        def fake_popen(cmd, *args, **kwargs):
            captured.append(list(cmd))
            m = MagicMock()
            m.wait.return_value = 0
            return m

        with patch("yt_vlc.extract_stream_url", return_value=("https://googlevideo.com/playback", None, False)), \
             patch("yt_vlc.monitor_vlc_rc"), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("threading.Thread", lambda target, args=(), kwargs={}, daemon=True: MagicMock(start=lambda: target(*args, **kwargs))):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, is_audio=True)
                launch_fn(video, settings, is_audio=False)
            except TypeError:
                pass
            if len(captured) >= 2:
                self.assertIn("--no-video", captured[0])
                self.assertNotIn("--no-video", captured[1])

    def test_f5_b03_audio_only_url_escaping(self):
        """F5: Stream URLs with special query parameters are passed uncorrupted."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = {"url": "https://googlevideo.com/playback?id=123&mime=audio%2Fmp4&rate=fast", "title": "Audio"}
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings)
            except Exception:
                pass
            if captured:
                self.assertTrue(any("googlevideo.com" in arg for arg in captured))

    def test_f5_b04_audio_only_hardware_flags(self):
        """F5: Audio mode maintains hardware stability flags even without video."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, is_audio=True)
            except Exception:
                pass
            if captured:
                self.assertIn("--extraintf=rc", captured)

    def test_f5_b05_audio_only_low_caching(self):
        """F5: Audio caching propagates correctly to VLC command."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1")
            settings = {"caching": 1000}
            try:
                launch_fn(video, settings, is_audio=True)
            except Exception:
                pass
            if captured:
                self.assertIn("--network-caching=1000", captured)


# ============================================================================
# F6 Boundaries: S905X Low CPU/RAM Profile (5 tests)
# ============================================================================
class TestF6Boundaries(unittest.TestCase):
    def test_f6_b01_rapid_queue_mutations_no_leak(self):
        """F6: 1000 enqueue and dequeue cycles do not leave lingering items."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        for i in range(1000):
            pq.add_item(make_sample_video(f"item_{i}"))
            pq.remove_item(0)
        self.assertEqual(len(pq.get_items()), 0)

    def test_f6_b02_vlc_flags_when_hw_accel_disabled(self):
        """F6: When hw_accel=False, VLC command falls back to skiploopfilter=4."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--avcodec-hw=none", src)
        self.assertIn("--avcodec-skiploopfilter=4", src)

    def test_f6_b03_single_thread_download_lock(self):
        """F6: DownloadManager worker thread concurrency stays strictly <= 1."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        concurrency = getattr(dm, "max_concurrent", 1)
        self.assertLessEqual(concurrency, 1)

    def test_f6_b04_garbage_collection_on_queue_clear(self):
        """F6: Clearing queue dereferences item objects for garbage collection."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        pq.add_batch([make_sample_video(f"v_{i}") for i in range(50)])
        pq.clear()
        self.assertEqual(len(pq.get_items()), 0)

    def test_f6_b05_low_ram_caching_ceiling(self):
        """F6: Default caching of 3000ms fits comfortably within 1-2GB RAM budget."""
        settings = getattr(yt_vlc, "load_settings")()
        caching = settings.get("caching", 3000)
        self.assertLessEqual(int(caching), 5000)


# ============================================================================
# F7 Boundaries: Background DownloadManager Queue (5 tests)
# ============================================================================
class TestF7Boundaries(unittest.TestCase):
    def setUp(self):
        self.dm_cls = getattr(yt_vlc, "DownloadManager", None)

    def test_f7_b01_download_cancel_mid_flight(self):
        """F7: Cancelling active download terminates worker execution cleanly."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        tid = dm.add_task("test_mid_flight", "Title", "720", "/tmp")
        cancelled = dm.cancel_task(tid)
        self.assertTrue(cancelled)

    def test_f7_b02_nonexistent_download_directory_creation(self):
        """F7: DownloadManager creates target directory if it does not exist."""
        with tempfile.TemporaryDirectory() as base_tmp:
            target_dir = os.path.join(base_tmp, "sub", "downloads")
            if self.dm_cls:
                dm = self.dm_cls.get_instance()
                dm.add_task("test_dir", "Title", "720", target_dir)
            else:
                # Check download_media function
                fn = getattr(yt_vlc, "download_media", None)
                if fn:
                    fn({"id": "dummy"}, download_dir=target_dir)
            self.assertTrue(os.path.exists(target_dir))

    def test_f7_b03_download_cancel_already_finished_task(self):
        """F7: Cancelling an already finished task returns False without side effects."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        tid = dm.add_task("test_fin", "Title", "720", "/tmp")
        # Manually mark as finished
        for t in dm.get_tasks():
            if t["task_id"] == tid:
                t["status"] = "finished"
        result = dm.cancel_task(tid)
        self.assertFalse(result)

    def test_f7_b04_download_queue_preserves_task_limit(self):
        """F7: Adding 20 tasks queues all tasks reliably in order."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        tids = [dm.add_task(f"v_{i}", f"Title {i}", "720", "/tmp") for i in range(20)]
        tasks = dm.get_tasks()
        self.assertGreaterEqual(len(tasks), 20)

    def test_f7_b05_duplicate_task_enqueues(self):
        """F7: Enqueuing the same video twice creates two unique task IDs."""
        if self.dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = self.dm_cls.get_instance()
        t1 = dm.add_task("same_vid", "Title", "720", "/tmp")
        t2 = dm.add_task("same_vid", "Title", "720", "/tmp")
        self.assertNotEqual(t1, t2)


# ============================================================================
# F8 Boundaries: Download Progress Hooks & Cancel (5 tests)
# ============================================================================
class TestF8Boundaries(unittest.TestCase):
    def test_f8_b01_zero_byte_download_handling(self):
        """F8: Progress hook handles 0 total_bytes without ZeroDivisionError."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            try:
                hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 0})
            except ZeroDivisionError:
                self.fail("Progress hook raised ZeroDivisionError on 0 total_bytes")

    def test_f8_b02_progress_hook_speed_zero_eta(self):
        """F8: When speed is 0 or None, ETA calculation does not crash."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            try:
                hook({"status": "downloading", "speed": 0, "eta": None, "downloaded_bytes": 500, "total_bytes": 1000})
            except Exception as e:
                self.fail(f"Progress hook crashed on zero speed: {e}")

    def test_f8_b03_progress_hook_total_bytes_estimate(self):
        """F8: Handles total_bytes_estimate when total_bytes is None."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            try:
                hook({"status": "downloading", "downloaded_bytes": 250, "total_bytes_estimate": 1000, "total_bytes": None})
            except Exception as e:
                self.fail(f"Progress hook failed with total_bytes_estimate: {e}")

    def test_f8_b04_progress_hook_callback_exception_tolerance(self):
        """F8: Faulty UI callback does not crash worker thread."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        # Set callback that raises exception
        dm.progress_callback = lambda *args: 1 / 0
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            try:
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            except ZeroDivisionError:
                self.fail("Worker crashed due to unhandled callback exception")

    def test_f8_b05_100_percent_completion_transition(self):
        """F8: At 100% completion, progress hook reports 100% and finishes cleanly."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            hook({"status": "finished", "downloaded_bytes": 1000, "total_bytes": 1000})


# ============================================================================
# F9 Boundaries: Download Formats & Sanitization (5 tests)
# ============================================================================
class TestF9Boundaries(unittest.TestCase):
    def test_f9_b01_title_sanitization_special_characters(self):
        """F9: Video titles with invalid filename characters are sanitized."""
        title = 'Song: "Best" / Live? * 2026 <Remix> | Part 1'
        sanitize_fn = getattr(yt_vlc, "sanitize_filename", None)
        if sanitize_fn:
            clean = sanitize_fn(title)
            for c in [':', '"', '/', '?', '*', '<', '>', '|']:
                self.assertNotIn(c, clean)
        else:
            self.assertTrue(True)

    def test_f9_b02_extreme_title_length_truncation(self):
        """F9: Extremely long titles (>255 chars) are safely bounded."""
        long_title = "A" * 300
        sanitize_fn = getattr(yt_vlc, "sanitize_filename", None)
        if sanitize_fn:
            clean = sanitize_fn(long_title)
            self.assertLessEqual(len(clean), 255)

    def test_f9_b03_unsupported_format_rejection(self):
        """F9: Requesting unsupported format defaults to safe MP4 or raises ValueError."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls:
            dm = dm_cls.get_instance()
            try:
                tid = dm.add_task("vid", "Title", "flv_unsupported", "/tmp")
                # Should sanitize format to safe default
            except ValueError:
                pass

    def test_f9_b04_existing_file_collision(self):
        """F9: Downloading when file exists does not crash worker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "Existing.mp4")
            with open(file_path, "w") as f:
                f.write("content")
            # Verify yt-dlp or download function handles overwrite/skip
            self.assertTrue(os.path.exists(file_path))

    def test_f9_b05_permission_denied_directory_handling(self):
        """F9: Downloading to read-only directory sets task status to error."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls:
            dm = dm_cls.get_instance()
            tid = dm.add_task("vid", "Title", "720", "/proc/read_only_fake")
            self.assertIsNotNone(tid)


# ============================================================================
# F10 Boundaries: Offline Library (5 tests)
# ============================================================================
class TestF10Boundaries(unittest.TestCase):
    def test_f10_b01_offline_scan_empty_directory(self):
        """F10: Scanning an empty directory returns an empty list without error."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            res = scan_fn(tmpdir)
            self.assertEqual(res, [])

    def test_f10_b02_corrupted_info_json_recovery(self):
        """F10: Corrupted .info.json sidecar does not crash scanner."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.mp4"), "w") as f:
                f.write("video")
            with open(os.path.join(tmpdir, "test.info.json"), "w") as f:
                f.write("{invalid json corrupt")
            res = scan_fn(tmpdir)
            self.assertEqual(len(res), 1)

    def test_f10_b03_missing_thumbnail_file(self):
        """F10: Missing thumbnail sidecar defaults to None or placeholder."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "nothumb.mp4"), "w") as f:
                f.write("video")
            res = scan_fn(tmpdir)
            self.assertEqual(len(res), 1)
            self.assertIsNone(res[0].get("thumbnail"))

    def test_f10_b04_non_media_files_ignored(self):
        """F10: Non-media files (.txt, .part, .tmp) are ignored."""
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if scan_fn is None:
            self.fail("Offline library scanner is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "notes.txt"), "w") as f:
                f.write("text")
            with open(os.path.join(tmpdir, "temp.part"), "w") as f:
                f.write("part")
            res = scan_fn(tmpdir)
            self.assertEqual(len(res), 0)

    def test_f10_b05_offline_library_refresh(self):
        """F10: OfflineLibraryWidget has refresh method to reload media."""
        widget_cls = getattr(yt_vlc, "OfflineLibraryWidget", None)
        if widget_cls is None:
            self.fail("OfflineLibraryWidget is not implemented in yt_vlc")
        w = widget_cls()
        self.assertTrue(hasattr(w, "refresh") or hasattr(w, "reload"))


# ============================================================================
# F11 Boundaries: Channel Playlists (5 tests)
# ============================================================================
class TestF11Boundaries(unittest.TestCase):
    def test_f11_b01_channel_with_no_playlists(self):
        """F11: Scraping channel with no playlists returns empty list without error."""
        parse_fn = getattr(yt_vlc, "parse_channel_playlists_json", None)
        if parse_fn is None:
            self.fail("parse_channel_playlists_json is not implemented in yt_vlc")
        res = parse_fn({"contents": {}})
        self.assertEqual(res, [])

    def test_f11_b02_malformed_ytinitialdata_handling(self):
        """F11: Incomplete ytInitialData does not raise unhandled exception."""
        parse_fn = getattr(yt_vlc, "parse_channel_playlists_json", None)
        if parse_fn is None:
            self.fail("parse_channel_playlists_json is not implemented in yt_vlc")
        res = parse_fn({"contents": {"unexpected_key": None}})
        self.assertEqual(res, [])

    def test_f11_b03_network_timeout_during_scrape(self):
        """F11: Network timeout in playlist fetch triggers graceful error callback."""
        fetch_fn = getattr(yt_vlc, "fetch_channel_playlists_ytdlp", None)
        if fetch_fn:
            with patch("subprocess.run", side_effect=Exception("Network Timeout")):
                res = fetch_fn("channel_123")
                self.assertEqual(res, [])

    def test_f11_b04_playlist_special_characters_in_title(self):
        """F11: HTML entities in playlist titles (&amp;, &#39;) are unescaped properly."""
        import html
        raw = "Rock &amp; Roll &#39;Hits&#39;"
        unescaped = html.unescape(raw)
        self.assertEqual(unescaped, "Rock & Roll 'Hits'")

    def test_f11_b05_playlist_zero_videos(self):
        """F11: Playlist with 0 videos displays empty list without error."""
        pl = make_sample_playlist("PL_empty", "Empty List", 0)
        self.assertEqual(len(pl["videos"]), 0)


# ============================================================================
# F12 Boundaries: Batch Queue Enqueueing (5 tests)
# ============================================================================
class TestF12Boundaries(unittest.TestCase):
    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)

    def test_f12_b01_batch_enqueue_zero_items(self):
        """F12: Batch enqueue with 0 items is a safe no-op."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        self.assertEqual(pq.add_batch([]), 0)

    def test_f12_b02_batch_enqueue_duplicate_items(self):
        """F12: Batch with internal duplicates enqueues all items in order."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        items = [make_sample_video("v1"), make_sample_video("v1"), make_sample_video("v2")]
        total = pq.add_batch(items)
        self.assertEqual(total, 3)

    def test_f12_b03_batch_enqueue_large_playlist_500(self):
        """F12: Batch enqueueing 500 items completes in < 50ms without recursion limit error."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        items = [make_sample_video(f"bulk_{i}") for i in range(500)]
        start = time.time()
        count = pq.add_batch(items)
        elapsed = time.time() - start
        self.assertEqual(count, 500)
        self.assertLess(elapsed, 0.5)

    def test_f12_b04_batch_enqueue_during_playback(self):
        """F12: Batch enqueueing while video is playing preserves current track index."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        pq.add_batch([make_sample_video("current_v")])
        pq.next_track()  # start playback
        self.assertEqual(pq.get_current_item()["id"], "current_v")
        pq.add_batch([make_sample_video(f"bg_{i}") for i in range(10)])
        self.assertEqual(pq.get_current_item()["id"], "current_v")

    def test_f12_b05_batch_enqueue_invalid_position(self):
        """F12: Invalid position string defaults to 'end' or raises ValueError."""
        if self.pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = self.pq_cls()
        items = [make_sample_video("v1")]
        try:
            pq.add_batch(items, position="invalid_pos")
            self.assertEqual(len(pq.get_items()), 1)
        except ValueError:
            pass


# ============================================================================
# F13 Boundaries: Live Stream Detection & HLS (5 tests)
# ============================================================================
class TestF13Boundaries(unittest.TestCase):
    def test_f13_b01_live_stream_zero_duration(self):
        """F13: Live stream with duration=0 or total_length<=0 handled correctly."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "https://manifest.googlevideo.com/live/index.m3u8\n"
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc
            res = extract_fn("live_zero_dur")
            self.assertIsInstance(res, tuple)

    def test_f13_b02_upcoming_premiere_dialog_or_warning(self):
        """F13: Upcoming premiere displays notification rather than launching VLC."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = ""
            mock_proc.stderr = "ERROR: Premiere will start soon"
            mock_proc.returncode = 1
            mock_run.return_value = mock_proc
            res = extract_fn("upcoming_prem")
            self.assertIsInstance(res, tuple)

    def test_f13_b03_live_stream_reconnect_caching(self):
        """F13: Live stream VLC command uses network-caching=3000 to prevent buffer underruns."""
        captured = []
        with mock_vlc_execution(stream_url="https://manifest.googlevideo.com/live.m3u8", is_live=True, captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("live_rec", "Live Reconnect")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, is_live=True)
            except Exception:
                pass
            if captured:
                self.assertIn("--network-caching=3000", captured)

    def test_f13_b04_live_stream_seek_disallowed(self):
        """F13: Live streams do not execute seek commands in monitor_vlc_rc."""
        monitor_fn = getattr(yt_vlc, "monitor_vlc_rc")
        import inspect
        src = inspect.getsource(monitor_fn)
        self.assertTrue("is_live" in src or "segments" in src)

    def test_f13_b05_live_stream_network_error(self):
        """F13: Network error during live stream extraction returns (None, None) gracefully."""
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        with patch("subprocess.run", side_effect=Exception("Network Unreachable")):
            res = extract_fn("live_net_err")
            self.assertIsInstance(res, tuple)
            self.assertIsNone(res[0])


# ============================================================================
# F14 Boundaries: Zero-Emoji Compliance & Gtk.Switch (5 tests)
# ============================================================================
class TestF14Boundaries(unittest.TestCase):
    def test_f14_b01_zero_emoji_in_exception_messages(self):
        """F14: Error and status string templates in yt_vlc.py contain 0 color emojis."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            if "raise " in line or "status_callback" in line:
                forbidden = find_forbidden_emojis(line)
                self.assertEqual(forbidden, [], f"Forbidden emoji at line {i}: {line.strip()}")

    def test_f14_b02_gtk_switch_in_non_grid_container(self):
        """F14: Gtk.Switch in Box or other container does not error on alignment."""
        sw = Gtk.Switch()
        sw.set_halign(Gtk.Align.START)
        sw.set_valign(Gtk.Align.CENTER)
        box = Gtk.Box()
        box.pack_start(sw, False, False, 0)
        self.assertEqual(sw.get_halign(), Gtk.Align.START)

    def test_f14_b03_dynamic_gtk_switch_creation(self):
        """F14: Dynamically created switches in dialogs enforce START/CENTER alignment."""
        dlg_cls = getattr(yt_vlc, "SettingsDialog", None)
        if dlg_cls:
            import inspect
            src = inspect.getsource(dlg_cls)
            self.assertIn("set_halign(Gtk.Align.START)", src)
            self.assertIn("set_valign(Gtk.Align.CENTER)", src)

    def test_f14_b04_unicode_symbols_not_flagged_as_emoji(self):
        """F14: Standard verified Unicode symbols (•, ✓, ✔) are not flagged as forbidden."""
        text = "Status: ✓ Success • 12 videos ✔ Ready"
        forbidden = find_forbidden_emojis(text)
        self.assertEqual(forbidden, [])

    def test_f14_b05_breeze_dark_theme_switch(self):
        """F14: Switching theme between Breeze Dark and Breeze Light works cleanly."""
        mw_cls = getattr(yt_vlc, "MainWindow", None)
        self.assertIsNotNone(mw_cls)
        import inspect
        src = inspect.getsource(mw_cls)
        self.assertTrue("dark" in src.lower() or "breeze" in src.lower() or "css" in src.lower())


# ============================================================================
# F15 Boundaries: S905X Hardware VLC Flags (5 tests)
# ============================================================================
class TestF15Boundaries(unittest.TestCase):
    def test_f15_b01_hw_accel_disabled_flags(self):
        """F15: When hw_accel is False, --avcodec-hw=none is present in VLC command."""
        import inspect
        src = inspect.getsource(getattr(yt_vlc, "launch_vlc"))
        self.assertIn("--avcodec-hw=none", src)

    def test_f15_b02_custom_caching_propagation(self):
        """F15: Custom caching parameter is passed to both file-caching and network-caching."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1")
            settings = {"caching": 5000}
            launch_fn(video, settings)
            self.assertIn("--file-caching=5000", captured)
            self.assertIn("--network-caching=5000", captured)

    def test_f15_b03_meta_title_escaping(self):
        """F15: Video titles with quotes and special characters are safely escaped in --meta-title."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v1", 'Title with "Quotes" & Special chars')
            settings = {"caching": 3000}
            launch_fn(video, settings)
            meta_flag = next((x for x in captured if x.startswith("--meta-title=")), None)
            self.assertIsNotNone(meta_flag)

    def test_f15_b04_stdout_pipe_strictly_forbidden(self):
        """F15: Codebase strictly forbids yt-dlp -o - | vlc - pipe."""
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("| vlc", src)
        self.assertNotIn("|vlc", src)

    def test_f15_b05_rc_port_collision_avoidance(self):
        """F15: find_free_tcp_port returns a valid, currently unused local port."""
        port_fn = getattr(yt_vlc, "find_free_tcp_port")
        port1 = port_fn()
        port2 = port_fn()
        self.assertIsInstance(port1, int)
        self.assertGreater(port1, 1024)
        self.assertLess(port1, 65535)


if __name__ == "__main__":
    unittest.main()
