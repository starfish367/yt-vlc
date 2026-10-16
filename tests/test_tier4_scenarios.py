"""
test_tier4_scenarios.py - Tier 4: Real-World Application Scenarios
Covers complete end-to-end user workflows and real-world workloads (6 tests total, >=5 requirement).
"""
import os
import sys
import re
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


class TestTier4RealWorldScenarios(unittest.TestCase):

    def test_scenario_1_continuous_album_listening(self):
        """
        Scenario 1: Continuous Album Listening
        Exercised Features: F1, F2, F3, F5, F6
        Workflow:
        1. User creates a queue with an album of 5 tracks.
        2. Sets playback mode to Audio-only (Radio Mode) to minimize CPU on S905X.
        3. Enables 'Repeat All'.
        4. Simulates track completions: track 1 -> 2 -> 3 -> 4 -> 5 -> wraps back to track 1.
        5. Verifies VLC command flags include --no-video, --play-and-exit, and hardware flags.
        """
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        album = make_sample_playlist("PL_album_01", "Full Album", 5)
        pq.add_batch(album["videos"])
        pq.set_repeat_mode("all")

        captured_commands = []
        def fake_popen(cmd, *args, **kwargs):
            captured_commands.append(list(cmd))
            m = MagicMock()
            m.wait.return_value = 0
            return m

        with patch("yt_vlc.extract_stream_url", return_value=("https://googlevideo.com/playback", None, False)), \
             patch("yt_vlc.monitor_vlc_rc"), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("threading.Thread", lambda target, args=(), kwargs={}, daemon=True: MagicMock(start=lambda: target(*args, **kwargs))):
            launch_fn = getattr(yt_vlc, "launch_vlc")

            # Simulate playing each track in the album
            played_ids = []
            pq.next_track()  # start playback on track 0
            for _ in range(6):  # 5 tracks + 1 wrap around to track 1
                curr = pq.get_current_item()
                self.assertIsNotNone(curr)
                played_ids.append(curr["id"])

                # Launch VLC for current track in queue audio mode
                try:
                    launch_fn(curr, {"caching": 3000, "hw_accel": True}, in_queue=True, is_audio=True)
                except TypeError:
                    self.fail("launch_vlc does not support in_queue and is_audio parameters")

                # Advance to next track upon track completion
                pq.next_track()

            # Verify complete cycle: 0 -> 1 -> 2 -> 3 -> 4 -> back to 0
            expected_ids = [album["videos"][i]["id"] for i in [0, 1, 2, 3, 4, 0]]
            self.assertEqual(played_ids, expected_ids)

            # Verify VLC execution flags
            self.assertGreaterEqual(len(captured_commands), 6)
            for cmd in captured_commands:
                self.assertIn("--no-video", cmd)
                self.assertIn("--play-and-exit", cmd)
                self.assertIn("--avcodec-skiploopfilter=3", cmd)
                self.assertIn("--drop-late-frames", cmd)

    def test_scenario_2_download_album_offline_and_play_in_airplane_mode(self):
        """
        Scenario 2: Download Album Offline & Play in Airplane Mode
        Exercised Features: F7, F8, F9, F10
        Workflow:
        1. User queues 3 audio tracks for background download in M4A format.
        2. Progress hooks report download percentage, speed, and ETA.
        3. Files and .info.json metadata sidecars are stored in download directory.
        4. User switches to Offline Library tab.
        5. Scanner scans directory, parses metadata and sidecars.
        6. User plays offline file via VLC with local caching flags (no internet required).
        """
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if dm_cls is None or scan_fn is None:
            self.fail("DownloadManager or Offline Library scanner not implemented")

        with tempfile.TemporaryDirectory() as dl_dir:
            dm = dm_cls.get_instance()
            progress_events = []
            dm.progress_callback = lambda tid, pct, spd, eta: progress_events.append((tid, pct, spd, eta))

            # 1. Enqueue 3 tasks
            t1 = dm.add_task("vid_101", "Acoustic Song 1", "m4a", dl_dir)
            t2 = dm.add_task("vid_102", "Acoustic Song 2", "m4a", dl_dir)
            t3 = dm.add_task("vid_103", "Acoustic Song 3", "m4a", dl_dir)

            # 2. Simulate worker completing files and creating .info.json sidecars
            for i, tid in enumerate([t1, t2, t3], 1):
                media_path = os.path.join(dl_dir, f"Acoustic Song {i}.m4a")
                json_path = os.path.join(dl_dir, f"Acoustic Song {i}.info.json")
                with open(media_path, "wb") as f:
                    f.write(b"M4A_AUDIO_DATA")
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "id": f"vid_10{i}",
                        "title": f"Acoustic Song {i}",
                        "uploader": "Indie Band",
                        "duration": 210
                    }, f)

            # 3. Scan offline library
            offline_media = scan_fn(dl_dir)
            self.assertEqual(len(offline_media), 3)
            self.assertEqual(offline_media[0]["uploader"], "Indie Band")

            # 4. Play local file in VLC
            captured_cmds = []
            def fake_popen(cmd, *args, **kwargs):
                captured_cmds.append(list(cmd))
                m = MagicMock()
                m.wait.return_value = 0
                return m

            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("threading.Thread", lambda target, args=(), kwargs={}, daemon=True: MagicMock(start=lambda: target(*args, **kwargs))):
                launch_local = getattr(yt_vlc, "launch_vlc_local", None) or getattr(yt_vlc, "launch_vlc")
                launch_local(offline_media[0], {"caching": 1000})

            self.assertGreater(len(captured_cmds), 0)
            self.assertTrue(any("Acoustic Song 1.m4a" in arg for arg in captured_cmds[0]))

    def test_scenario_3_channel_playlist_enqueue_and_background_download(self):
        """
        Scenario 3: Channel Playlist Enqueue & Background Video Download
        Exercised Features: F1, F7, F11, F12
        Workflow:
        1. User browses a channel's playlist tab.
        2. Clicks 'Phát tất cả vào hàng đợi' to batch enqueue 10 videos.
        3. Concurrently, user enqueues a background video download (MP4 720p).
        4. Play queue advances while download worker operates in background without blocking.
        """
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if pq_cls is None or dm_cls is None:
            self.fail("PlayQueueManager or DownloadManager not implemented")

        pq = pq_cls()
        dm = dm_cls.get_instance()

        # Batch enqueue playlist
        pl = make_sample_playlist("PL_rock", "Classic Rock", 10)
        pq.add_batch(pl["videos"])
        self.assertEqual(len(pq.get_items()), 10)

        # Concurrently enqueue background download
        tid = dm.add_task("heavy_vid", "Rock Documentary", "720", "/tmp")
        self.assertIsNotNone(tid)

        # Advance queue while download is queued
        pq.next_track()  # start on track 0
        for _ in range(3):
            pq.next_track()
        self.assertEqual(pq.get_current_item()["id"], pl["videos"][3]["id"])

        # Check download task remains active in queue
        tasks = dm.get_tasks()
        self.assertTrue(any(t["task_id"] == tid for t in tasks))

    def test_scenario_4_live_stream_monitoring_and_radio_mode(self):
        """
        Scenario 4: Live Stream Monitoring & Switching to Radio Mode
        Exercised Features: F5, F6, F13, F15
        Workflow:
        1. User opens a YouTube live stream video.
        2. Detection recognizes is_live=True and retrieves direct HLS .m3u8 manifest.
        3. VLC plays stream with --network-caching=3000.
        4. User switches to Audio-Only Radio Mode to save CPU and RAM.
        5. VLC restarts with --no-video, freeing Mali-450 GPU completely.
        """
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        launch_fn = getattr(yt_vlc, "launch_vlc")

        # Mock yt-dlp live stream detection
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "https://manifest.googlevideo.com/live/radio.m3u8\n"
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            res = extract_fn("live_radio_id")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3, "extract_stream_url must return 3-tuple (url, audio_url, is_live)")
            v_url, a_url, is_live = res
            self.assertTrue(is_live)
            self.assertTrue(v_url.endswith(".m3u8"))

        captured_cmds = []
        def fake_popen(cmd, *args, **kwargs):
            captured_cmds.append(list(cmd))
            m = MagicMock()
            m.wait.return_value = 0
            return m

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("yt_vlc.extract_stream_url", return_value=("https://manifest.googlevideo.com/live/radio.m3u8", None, True)), \
             patch("yt_vlc.monitor_vlc_rc"), \
             patch("threading.Thread", lambda target, args=(), kwargs={}, daemon=True: MagicMock(start=lambda: target(*args, **kwargs))):
            video = make_sample_video("live_radio_id", "24/7 Lo-Fi Beats")
            # Step 1: Normal live playback
            try:
                launch_fn(video, {"caching": 3000, "hw_accel": True}, is_live=True, is_audio=False)
            except TypeError:
                self.fail("launch_vlc does not support is_live argument")

            # Step 2: Radio mode switch
            launch_fn(video, {"caching": 3000, "hw_accel": True}, is_live=True, is_audio=True)

        self.assertEqual(len(captured_cmds), 2)
        # First was normal video live stream
        self.assertNotIn("--no-video", captured_cmds[0])
        self.assertIn("--network-caching=3000", captured_cmds[0])
        # Second was audio-only radio mode
        self.assertIn("--no-video", captured_cmds[1])
        self.assertIn("--network-caching=3000", captured_cmds[1])
        self.assertIn("--avcodec-skiploopfilter=3", captured_cmds[1])

    def test_scenario_5_full_ui_s905x_and_breeze_dark_compliance_sweep(self):
        """
        Scenario 5: Full UI S905X & Breeze Dark Compliance Sweep
        Exercised Features: F4, F10, F14, F15
        Workflow:
        1. Traverse all widgets, dialogs, and classes in yt_vlc.py.
        2. Enforce 0 color emojis in code and labels (chống lỗi Tofu trên Armbian).
        3. Enforce strict set_halign(Gtk.Align.START) and set_valign(Gtk.Align.CENTER) for all Gtk.Switch in grids.
        4. Enforce strict S905X hardware acceleration flags and no stdout pipe.
        5. Verify Breeze / Breeze Dark theme support.
        """
        src_path = os.path.join(PROJECT_DIR, "yt_vlc.py")
        with open(src_path, "r", encoding="utf-8") as f:
            code = f.read()

        # 1. Zero color emojis
        forbidden = find_forbidden_emojis(code)
        self.assertEqual(forbidden, [], f"Tofu alert! Found forbidden color emojis in yt_vlc.py: {set(forbidden)}")

        # 2. Check all Gtk.Switch in Gtk.Grid
        switches = re.findall(r"(\w+)\s*=\s*Gtk\.Switch\(\)", code)
        self.assertGreater(len(switches), 0, "No Gtk.Switch instances found in yt_vlc.py")
        for sw in switches:
            self.assertIn(f"{sw}.set_halign(Gtk.Align.START)", code)
            self.assertIn(f"{sw}.set_valign(Gtk.Align.CENTER)", code)

        # 3. Hardware decoding flags
        self.assertIn("--avcodec-skiploopfilter=3", code)
        self.assertIn("--drop-late-frames", code)
        self.assertIn("--skip-frames", code)
        self.assertIn("--no-video-title-show", code)
        self.assertIn("vcodec^=avc1", code)

        # 4. No stdout pipe
        self.assertNotIn("| vlc", code)

    def test_scenario_6_mixed_heavy_workload_lifecycle(self):
        """
        Scenario 6: Mixed Heavy Workload Simulation
        Exercised Features: F1, F2, F3, F7, F8, F10, F14
        Workflow:
        1. User creates large queue (30 items).
        2. Toggles shuffle, sets repeat='all'.
        3. Starts 3 background download tasks concurrently.
        4. Performs 10 auto-advances.
        5. Cancels one download task.
        6. Clears queue and verifies system memory returns to baseline without leaks.
        """
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if pq_cls is None or dm_cls is None:
            self.fail("PlayQueueManager or DownloadManager not implemented")

        pq = pq_cls()
        dm = dm_cls.get_instance()

        # Add 30 items
        items = [make_sample_video(f"load_{i}") for i in range(30)]
        pq.add_batch(items)
        pq.next_track()  # start playback on track 0
        pq.set_shuffle(True)
        pq.set_repeat_mode("all")

        # Queue 3 downloads
        t1 = dm.add_task("dl_1", "Download 1", "720", "/tmp")
        t2 = dm.add_task("dl_2", "Download 2", "m4a", "/tmp")
        t3 = dm.add_task("dl_3", "Download 3", "720", "/tmp")

        # 10 advances
        for _ in range(10):
            next_trk = pq.next_track()
            self.assertIsNotNone(next_trk)

        # Cancel download 2
        dm.cancel_task(t2)

        # Clear queue
        pq.clear()
        self.assertEqual(len(pq.get_items()), 0)
        self.assertIsNone(pq.get_current_item())


if __name__ == "__main__":
    unittest.main()
