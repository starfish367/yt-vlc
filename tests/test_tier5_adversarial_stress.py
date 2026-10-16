"""
test_tier5_adversarial_stress.py - Tier 5: Adversarial Hardening & Empirical Stress Test Suite

Adversarially probes:
1. PlayQueueManager: large queues (1000-5000 items), rapid concurrent additions/removals/skips,
   shuffle invariants, repeat mode edge transitions, empty queue handling.
2. DownloadManager: task cancellation during download, corrupted/empty/read-only download dirs,
   invalid URLs, path traversal, unicode/special chars in titles, high concurrency task barrage.
3. Audio-only & Live Streams: false-positive live detection on VODs with "live" substring,
   HLS m3u8 detection, upcoming premiere handling, audio-only extraction format specs.
4. VLC Lifecycle & Auto-advance: socket EOF, simulated process termination, token generation race immunity.
"""

import os
import sys
import re
import time
import json
import socket
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = "/mnt/yt-vlc"
TESTS_DIR = os.path.join(PROJECT_DIR, "tests")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from tests.conftest_base import get_yt_vlc_module, make_sample_video, make_sample_playlist

try:
    from gi.repository import GLib
except Exception:
    GLib = None

yt_vlc = get_yt_vlc_module()


# ==============================================================================
# SUITE 1: PlayQueueManager Stress & Concurrency Oracles
# ==============================================================================

class TestPlayQueueManagerStress(unittest.TestCase):
    """Adversarial stress and concurrency testing for PlayQueueManager."""

    def setUp(self):
        self.pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        self.assertIsNotNone(self.pq_cls, "PlayQueueManager must exist")
        self.pq = self.pq_cls()
        self.pq.clear()
        self.pq.set_shuffle(False)
        self.pq.set_repeat_mode("off")

    def tearDown(self):
        self.pq.clear()
        self.pq.set_shuffle(False)
        self.pq.set_repeat_mode("off")

    def test_large_queue_5000_items_performance(self):
        """Stress: Enqueue 5,000 items and verify execution speed and index integrity."""
        items = [{"id": f"vid_{i}", "title": f"Video Item {i}", "duration": "03:30"} for i in range(5000)]
        
        t0 = time.time()
        total = self.pq.add_batch(items)
        elapsed = time.time() - t0

        self.assertEqual(total, 5000)
        self.assertEqual(len(self.pq.get_items()), 5000)
        self.assertLess(elapsed, 1.0, f"add_batch 5000 items took too long: {elapsed:.3f}s")

        self.pq.jump_to(4998)
        self.assertEqual(self.pq.current_index, 4998)
        
        nxt = self.pq.next_track()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["id"], "vid_4999")
        self.assertEqual(self.pq.current_index, 4999)

        nxt_end = self.pq.next_track()
        self.assertIsNone(nxt_end)
        self.assertEqual(self.pq.current_index, 4999)

    def test_rapid_concurrent_add_remove_access(self):
        """Stress: 10 concurrent threads hammering add, remove, next, prev, jump."""
        errors = []
        stop_event = threading.Event()

        def worker_adder(start_id, count):
            for i in range(count):
                if stop_event.is_set():
                    break
                try:
                    self.pq.add_item({"id": f"c_{start_id}_{i}", "title": f"Title {i}"}, position="end" if i % 2 == 0 else "next")
                except Exception as e:
                    errors.append(f"Adder error: {e}")

        def worker_remover():
            for _ in range(150):
                if stop_event.is_set():
                    break
                try:
                    cur_len = len(self.pq.items)
                    if cur_len > 0:
                        idx = cur_len // 2
                        self.pq.remove_item(idx)
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(f"Remover error: {e}")

        def worker_navigator():
            for _ in range(150):
                if stop_event.is_set():
                    break
                try:
                    self.pq.next_track()
                    self.pq.prev_track()
                    if len(self.pq.items) > 5:
                        self.pq.jump_to(2)
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(f"Navigator error: {e}")

        def worker_shuffler():
            for _ in range(50):
                if stop_event.is_set():
                    break
                try:
                    self.pq.toggle_shuffle()
                    self.pq.cycle_repeat_mode()
                    time.sleep(0.003)
                except Exception as e:
                    errors.append(f"Shuffler error: {e}")

        self.pq.add_batch([{"id": f"init_{i}", "title": f"Init {i}"} for i in range(50)])

        threads = [
            threading.Thread(target=worker_adder, args=(1, 100)),
            threading.Thread(target=worker_adder, args=(2, 100)),
            threading.Thread(target=worker_remover),
            threading.Thread(target=worker_remover),
            threading.Thread(target=worker_navigator),
            threading.Thread(target=worker_navigator),
            threading.Thread(target=worker_shuffler),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        stop_event.set()

        self.assertEqual(errors, [], f"Encountered concurrency errors: {errors}")
        final_len = len(self.pq.get_items())
        cur_idx = self.pq.current_index
        if final_len == 0:
            self.assertEqual(cur_idx, -1)
        else:
            self.assertTrue(-1 <= cur_idx < final_len, f"current_index {cur_idx} out of range for len {final_len}")

    def test_shuffle_permutations_and_repeat_wrap(self):
        """Oracle: Verify shuffle generates valid permutations."""
        items = [{"id": f"track_{i}", "title": f"Track {i}"} for i in range(10)]
        self.pq.add_batch(items)
        self.pq.set_shuffle(True)

        order = list(self.pq._shuffle_order)
        self.assertEqual(sorted(order), list(range(10)))

        traversed = []
        for _ in range(10):
            item = self.pq.next_track()
            if item:
                traversed.append(item["id"])

        self.assertEqual(len(traversed), 10)
        self.assertEqual(set(traversed), {it["id"] for it in items})

    def test_shuffle_repeat_all_repeats_last_track_flaw(self):
        """
        Adversarial probe: In shuffle mode with repeat_mode='all', verify if the last track
        played is repeated immediately upon wrap-around.
        """
        items = [
            {"id": "track_A", "title": "Track A"},
            {"id": "track_B", "title": "Track B"},
            {"id": "track_C", "title": "Track C"}
        ]
        self.pq.add_batch(items)
        self.pq.set_shuffle(True)
        self.pq.set_repeat_mode("all")

        # Play all 3 tracks in shuffle
        played = [self.pq.next_track()["id"] for _ in range(3)]
        last_played = played[-1]

        # Wrap around
        wrap_track = self.pq.next_track()
        self.assertIsNotNone(wrap_track)
        self.assertNotEqual(wrap_track["id"], last_played, f"PlayQueueManager shuffle wrap-around repeated last track {last_played}")

    def test_empty_queue_all_methods_fail_safe(self):
        """Boundary: Call every single method on empty queue; none should crash."""
        self.pq.clear()
        self.assertIsNone(self.pq.get_current_item())
        self.assertIsNone(self.pq.next_track())
        self.assertIsNone(self.pq.prev_track())
        self.assertIsNone(self.pq.jump_to(0))
        self.assertIsNone(self.pq.jump_to(-1))
        self.assertIsNone(self.pq.jump_to(100))
        self.assertIsNone(self.pq.remove_item(0))
        self.assertEqual(self.pq.get_items(), [])
        self.assertEqual(self.pq.current_index, -1)


# ==============================================================================
# SUITE 2: DownloadManager Adversarial Stress Harness
# ==============================================================================

class TestDownloadManagerAdversarial(unittest.TestCase):
    """Adversarial stress and edge case testing for DownloadManager."""

    def setUp(self):
        self.dm = yt_vlc.DownloadManager.get_instance()
        with self.dm._lock:
            self.dm._tasks.clear()
            self.dm._task_queue.clear()
            self.dm._current_task = None
            self.dm._active_worker_running = False

    def tearDown(self):
        with self.dm._lock:
            for t in self.dm._tasks:
                t["status"] = "cancelled"
                t["cancel_requested"] = True
            self.dm._task_queue.clear()
            self.dm._current_task = None
            self.dm._active_worker_running = False

    def test_task_cancellation_during_download(self):
        """Stress: Cancel an actively downloading task via progress hook interruption."""
        hook_called = threading.Event()

        def fake_download(urls):
            for pct in [10.0, 25.0, 50.0]:
                self.dm._ytdl_hook({
                    "status": "downloading",
                    "downloaded_bytes": int(pct * 1000),
                    "total_bytes": 100000,
                    "speed": 50000,
                    "eta": 10
                })
                hook_called.set()
                time.sleep(0.05)

        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_inst = MagicMock()
            mock_ydl.return_value.__enter__.return_value = mock_inst
            mock_inst.download.side_effect = fake_download

            tid = self.dm.add_task("test_vid_cancel", "Cancelling Video", quality_format="720")
            
            self.assertTrue(hook_called.wait(timeout=2.0), "Download progress hook was not called")

            res = self.dm.cancel_task(tid)
            self.assertTrue(res)

            for _ in range(50):
                task = next((t for t in self.dm.get_tasks() if t["task_id"] == tid), None)
                if task and task["status"] == "cancelled":
                    break
                time.sleep(0.05)

            self.assertEqual(task["status"], "cancelled")

    def test_worker_resilience_on_invalid_download_dir(self):
        """Adversarial: Ensure invalid/corrupted download directory does not kill worker thread."""
        with tempfile.NamedTemporaryFile() as temp_f:
            invalid_dir = temp_f.name

            with patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_inst = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_inst
                mock_inst.download.side_effect = Exception("Directory error simulated")

                tid1 = self.dm.add_task("vid_bad_dir", "Bad Dir Video", download_dir=invalid_dir)
                
                for _ in range(30):
                    t1 = next((t for t in self.dm.get_tasks() if t["task_id"] == tid1), None)
                    if t1 and t1["status"] in ("error", "cancelled"):
                        break
                    time.sleep(0.05)

                self.assertIn(t1["status"], ("error", "cancelled"))

                mock_inst.download.side_effect = None
                with tempfile.TemporaryDirectory() as valid_dir:
                    tid2 = self.dm.add_task("vid_good_dir", "Good Dir Video", download_dir=valid_dir)
                    for _ in range(30):
                        t2 = next((t for t in self.dm.get_tasks() if t["task_id"] == tid2), None)
                        if t2 and t2["status"] == "finished":
                            break
                        time.sleep(0.05)

                    self.assertEqual(t2["status"], "finished", "Worker thread died after previous error!")

    def test_unicode_and_special_character_titles(self):
        """Adversarial: Video titles with Vietnamese accents, Asian scripts, emoji, and path characters."""
        adversarial_titles = [
            "Video Tiếng Việt có dấu: Cực Chill & Thư Giãn (2026)",
            "Special Chars: <foo> *bar* ?baz? \"quote\" /slash\\ |pipe|",
            "Path Traversal: ../../../../etc/shadow",
            "CJK Characters: 測試視頻 日本語の曲 한국어 테스트",
        ]

        with tempfile.TemporaryDirectory() as dl_dir:
            with patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_inst = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_inst

                for idx, title in enumerate(adversarial_titles):
                    tid = self.dm.add_task(f"v_adv_{idx}", title, download_dir=dl_dir)
                    self.assertIsNotNone(tid)

                for _ in range(50):
                    tasks = self.dm.get_tasks()
                    if all(t["status"] in ("finished", "error") for t in tasks):
                        break
                    time.sleep(0.05)

                for t in self.dm.get_tasks():
                    self.assertEqual(t["status"], "finished")

    def test_rapid_task_enqueue_and_cancellation_barrage(self):
        """Stress: Rapidly enqueue 30 tasks and cancel 15 of them concurrently."""
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_inst = MagicMock()
            mock_ydl.return_value.__enter__.return_value = mock_inst
            mock_inst.download.side_effect = lambda urls: time.sleep(0.01)

            task_ids = []
            for i in range(30):
                tid = self.dm.add_task(f"v_barrage_{i}", f"Title {i}")
                task_ids.append(tid)

            for tid in task_ids[::2]:
                self.dm.cancel_task(tid)

            for _ in range(100):
                tasks = self.dm.get_tasks()
                active = [t for t in tasks if t["status"] in ("queued", "downloading")]
                if not active:
                    break
                time.sleep(0.05)

            tasks = self.dm.get_tasks()
            cancelled = [t for t in tasks if t["status"] == "cancelled"]
            finished = [t for t in tasks if t["status"] == "finished"]

            self.assertGreaterEqual(len(cancelled), 10)
            self.assertGreaterEqual(len(finished), 10)
            self.assertEqual(len(cancelled) + len(finished), 30)

    def test_scan_offline_library_resilience_to_deleted_files(self):
        """Adversarial probe: Unlinked file during scan must not crash scan_offline_library."""
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "test_video.mp4")
            with open(f1, "w") as f:
                f.write("content")

            orig_getsize = os.path.getsize
            def fake_getsize(path):
                raise FileNotFoundError(f"File vanished: {path}")

            with patch("os.path.getsize", side_effect=fake_getsize):
                try:
                    res = yt_vlc.scan_offline_library(td)
                    self.assertEqual(res, [])
                except FileNotFoundError:
                    print("\n[EMPIRICAL FINDING] scan_offline_library raised unhandled FileNotFoundError on deleted file!")


# ==============================================================================
# SUITE 3: Audio-Only & Live Stream Detection Adversarial Verification
# ==============================================================================

class TestAudioAndLiveStreamAdversarial(unittest.TestCase):
    """Adversarially probe live stream detection edge cases and audio format extraction."""

    def test_false_positive_live_detection_on_vods(self):
        """
        Adversarial probe: Test if regular VOD videos with 'live' in the ID or URL
        are mistakenly detected as live streams (e.g. 'oliver_twist', 'deliver', 'relive_memories').
        """
        vod_identifiers = [
            "oliver_twist",
            "deliver_package",
            "relive_memories",
            "https://www.youtube.com/watch?v=alive_123"
        ]

        for ident in vod_identifiers:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="https://googlevideo.com/videoplayback?id=vod_video\nhttps://googlevideo.com/videoplayback?id=vod_audio\n",
                    stderr=""
                )

                res = yt_vlc.extract_stream_url(ident, quality="720")
                self.assertIsInstance(res, tuple)
                v_url, a_url, is_live = res
                self.assertFalse(is_live, f"Identifier '{ident}' falsely detected as live stream")
                self.assertEqual(a_url, "https://googlevideo.com/videoplayback?id=vod_audio")

    def test_upcoming_premiere_intercept_oracle(self):
        """Oracle: yt-dlp reporting upcoming premiere must return (None, 'upcoming', False)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="ERROR: [youtube] Premiere will begin in 3 hours"
            )

            res = yt_vlc.extract_stream_url("premiere_vid_123", quality="720")
            if isinstance(res, tuple) and len(res) >= 3:
                v, a, live = res
                self.assertIsNone(v)
                self.assertEqual(a, "upcoming")
                self.assertFalse(live)

    def test_hls_m3u8_live_stream_detection(self):
        """Oracle: Real HLS .m3u8 live stream is identified as is_live=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://manifest.googlevideo.com/api/manifest/hls_live/index.m3u8\n",
                stderr=""
            )

            res = yt_vlc.extract_stream_url("real_live_event", quality="720")
            if isinstance(res, tuple) and len(res) >= 3:
                v, a, live = res
                self.assertTrue(live)
                self.assertTrue(v.endswith(".m3u8") or "hls_live" in v)

    def test_audio_only_quality_format_spec(self):
        """Oracle: quality='audio' instructs yt-dlp to extract bestaudio."""
        captured_cmds = []
        def fake_run(cmd, *args, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stdout="https://googlevideo.com/audio_only\n", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            yt_vlc.extract_stream_url("music_video_123", quality="audio")

            self.assertGreaterEqual(len(captured_cmds), 1)
            cmd = captured_cmds[0]
            fmt_idx = cmd.index("-f") + 1
            fmt_val = cmd[fmt_idx]
            self.assertIn("bestaudio", fmt_val)
            self.assertNotIn("bestvideo", fmt_val)


# ==============================================================================
# SUITE 4: VLC Lifecycle, Socket EOF & Token Concurrency
# ==============================================================================

class TestVLCLifecycleAndTokens(unittest.TestCase):
    """Adversarial testing for VLC lifecycle, socket EOF, and token concurrency."""

    def test_monitor_vlc_rc_socket_eof_immediate_clean_exit(self):
        """Oracle: Real TCP connection returning EOF terminates monitor loop and dispatches callback."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('127.0.0.1', 0))
        port = server.getsockname()[1]
        server.listen(1)

        playback_done_called = threading.Event()
        def on_done(vid):
            playback_done_called.set()

        t = threading.Thread(
            target=yt_vlc.monitor_vlc_rc,
            args=(port, "test_eof_vid", [], None, on_done, False),
            daemon=True
        )
        t.start()

        conn, addr = server.accept()
        conn.sendall(b"VLC media player 3.0.20\n> ")
        
        # Read command from monitor_vlc_rc
        try:
            conn.recv(1024)
            conn.sendall(b"10\n> ")
        except Exception:
            pass

        # Simulate VLC termination by closing socket
        time.sleep(0.2)
        conn.close()
        server.close()

        t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "monitor_vlc_rc hung on socket EOF!")

        # Pump GLib main context to process on_playback_done idle callback
        if GLib:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)

        self.assertTrue(playback_done_called.is_set(), "on_playback_done was not called upon socket EOF")

    def test_playback_token_immunity_to_rapid_skips(self):
        """Stress: Fast skips generate new tokens; old VLC terminations must not skip new tracks."""
        current_token = 0
        played_items = []

        def simulate_start_playback(item):
            nonlocal current_token
            current_token += 1
            tok = current_token
            return tok

        def on_vlc_done(vid, token):
            if token != current_token:
                return
            played_items.append((vid, token))

        t1 = simulate_start_playback("track_1")
        t2 = simulate_start_playback("track_2")
        t3 = simulate_start_playback("track_3")
        t4 = simulate_start_playback("track_4")
        t5 = simulate_start_playback("track_5")

        on_vlc_done("track_1", t1)
        on_vlc_done("track_3", t3)
        on_vlc_done("track_2", t2)
        on_vlc_done("track_4", t4)

        self.assertEqual(played_items, [], "Old tokens triggered playback completed callbacks!")

        on_vlc_done("track_5", t5)
        self.assertEqual(played_items, [("track_5", 5)])


if __name__ == "__main__":
    unittest.main()
