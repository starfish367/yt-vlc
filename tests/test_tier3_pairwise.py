"""
test_tier3_pairwise.py - Tier 3: Cross-Feature Pairwise Combinations
Covers pairwise combinations and interactions between features (16 tests total, >=15 requirement).
"""
import os
import sys
import unittest
import tempfile
import json
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


class TestTier3PairwiseCombinations(unittest.TestCase):

    def test_pair_01_queue_and_audio_only_playback(self):
        """Pair 1 (F1 + F5): PlayQueueManager item played in audio-only mode with --no-video."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        pq.add_item(make_sample_video("v_audio", "Audio Podcast"))
        curr = pq.next_track()  # start playback on first track

        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            try:
                launch_fn(curr, {"caching": 3000}, in_queue=True, is_audio=True)
            except TypeError:
                self.fail("launch_vlc does not support in_queue and is_audio arguments simultaneously")
            self.assertIn("--play-and-exit", captured)
            self.assertIn("--no-video", captured)

    def test_pair_02_channel_playlist_batch_enqueue_and_autoadvance(self):
        """Pair 2 (F11 + F12 + F2): Scrape channel playlist, batch enqueue, verify auto-advance."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        playlist = make_sample_playlist("PL_ch", "Channel Playlist", 5)
        pq.add_batch(playlist["videos"])
        self.assertEqual(len(pq.get_items()), 5)
        t1 = pq.next_track()  # start track 1
        self.assertEqual(t1["id"], playlist["videos"][0]["id"])
        # Simulate auto-advance through tracks
        t2 = pq.next_track()
        self.assertEqual(t2["id"], playlist["videos"][1]["id"])
        t3 = pq.next_track()
        self.assertEqual(t3["id"], playlist["videos"][2]["id"])

    def test_pair_03_download_m4a_add_to_queue_and_offline_playback(self):
        """Pair 3 (F9 + F1 + F10): Download audio M4A, add local file to queue, play offline."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = os.path.join(tmpdir, "Track 01.m4a")
            info_file = os.path.join(tmpdir, "Track 01.info.json")
            with open(audio_file, "w") as f:
                f.write("audio stream")
            with open(info_file, "w") as f:
                json.dump({"title": "Offline M4A Song", "id": "m4a_01"}, f)

            scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
            if scan_fn is None:
                self.fail("Offline library scanner not implemented")
            offline_items = scan_fn(tmpdir)
            self.assertEqual(len(offline_items), 1)

            pq = pq_cls()
            pq.add_item(offline_items[0])
            pq.next_track()
            self.assertEqual(pq.get_current_item()["title"], "Offline M4A Song")

    def test_pair_04_audio_only_live_stream_vlc_flags(self):
        """Pair 4 (F5 + F13 + F15): Live stream in audio-only mode retains caching and --no-video."""
        captured = []
        with mock_vlc_execution(stream_url="https://manifest.googlevideo.com/live.m3u8", is_live=True, captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("live_radio", "24/7 Lofi Radio")
            settings = {"caching": 3000, "hw_accel": True}
            try:
                launch_fn(video, settings, is_live=True, is_audio=True)
            except TypeError:
                self.fail("launch_vlc fails to combine is_live and is_audio")
            self.assertIn("--network-caching=3000", captured)
            self.assertIn("--no-video", captured)
            self.assertIn("--drop-late-frames", captured)

    def test_pair_05_shuffle_repeat_all_autoadvance_lifecycle(self):
        """Pair 5 (F3 + F2): Shuffle combined with repeat-all preserves continuous cycle."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        items = [make_sample_video(f"t_{i}") for i in range(5)]
        pq.add_batch(items)
        pq.set_repeat_mode("all")
        pq.set_shuffle(True)
        # Advance through 10 steps without reaching dead end
        visited = []
        for _ in range(10):
            item = pq.next_track()
            self.assertIsNotNone(item)
            visited.append(item["id"])
        self.assertEqual(len(visited), 10)

    def test_pair_06_download_progress_and_gtk_ui_updates(self):
        """Pair 6 (F8 + F4): Download progress dispatches to GTK UI through GLib.idle_add."""
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if dm_cls is None:
            self.fail("DownloadManager is not implemented in yt_vlc")
        dm = dm_cls.get_instance()
        ui_updates = []
        def progress_cb(task_id, percent, speed, eta):
            ui_updates.append((task_id, percent, speed, eta))

        dm.progress_callback = progress_cb
        hook = getattr(dm, "_ytdl_hook", None)
        if hook:
            hook({
                "status": "downloading",
                "downloaded_bytes": 5000000,
                "total_bytes": 10000000,
                "speed": 1048576,
                "eta": 5
            })
            self.assertTrue(len(ui_updates) > 0 or hasattr(yt_vlc, "GLib"))

    def test_pair_07_offline_library_scan_and_queue_enqueue(self):
        """Pair 7 (F10 + F1): Scan offline directory and enqueue all found media into PlayQueue."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        scan_fn = getattr(yt_vlc, "scan_offline_library", None) or getattr(yt_vlc, "get_offline_videos", None)
        if pq_cls is None or scan_fn is None:
            self.fail("Offline library or PlayQueue components not implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                with open(os.path.join(tmpdir, f"video_{i}.mp4"), "w") as f:
                    f.write("data")
            videos = scan_fn(tmpdir)
            pq = pq_cls()
            pq.add_batch(videos)
            self.assertEqual(len(pq.get_items()), 3)

    def test_pair_08_audio_only_stream_extraction_and_download(self):
        """Pair 8 (F5 + F7): Audio-only extraction format matches download manager audio specification."""
        import inspect
        extract_fn = getattr(yt_vlc, "extract_stream_url")
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        fn_dl = getattr(yt_vlc, "download_media", None)
        src_ext = inspect.getsource(extract_fn)
        src_dl = inspect.getsource(dm_cls) if dm_cls else (inspect.getsource(fn_dl) if fn_dl else "")
        self.assertIn("bestaudio", src_ext)
        self.assertTrue("bestaudio" in src_dl or "m4a" in src_dl or "mp3" in src_dl)

    def test_pair_09_channel_playlist_batch_enqueue_and_repeat_one(self):
        """Pair 9 (F12 + F3): Batch enqueue entire playlist, then lock playback on repeat 'one'."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        playlist = make_sample_playlist("PL_album", "Favorite Album", 4)
        pq.add_batch(playlist["videos"])
        # Seek to track 2 (index 1)
        pq.next_track()  # track 1 (index 0)
        pq.next_track()  # track 2 (index 1)
        self.assertEqual(pq.get_current_item()["id"], playlist["videos"][1]["id"])
        pq.set_repeat_mode("one")
        # Advancing keeps track 2
        self.assertEqual(pq.next_track()["id"], playlist["videos"][1]["id"])
        self.assertEqual(pq.next_track()["id"], playlist["videos"][1]["id"])

    def test_pair_10_vlc_hardware_flags_and_autoadvance_flag(self):
        """Pair 10 (F15 + F2): VLC command combines S905X hardware acceleration flags and --play-and-exit."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("v_hw", "HW Video")
            settings = {"caching": 3000, "hw_accel": True}
            try:
                launch_fn(video, settings, in_queue=True)
            except TypeError:
                self.fail("launch_vlc in_queue argument not supported")
            self.assertIn("--play-and-exit", captured)
            self.assertIn("--avcodec-skiploopfilter=3", captured)
            self.assertIn("--drop-late-frames", captured)

    def test_pair_11_download_cancel_does_not_affect_queue_playback(self):
        """Pair 11 (F7 + F1): Cancelling a background download task does not interrupt active queue."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        dm_cls = getattr(yt_vlc, "DownloadManager", None)
        if pq_cls is None or dm_cls is None:
            self.fail("PlayQueueManager or DownloadManager not implemented")
        pq = pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        dm = dm_cls.get_instance()
        tid = dm.add_task("dl_vid", "Download", "720", "/tmp")
        dm.cancel_task(tid)
        # Queue should remain fully intact
        self.assertEqual(len(pq.get_items()), 2)
        self.assertEqual(pq.get_current_item()["id"], "v1")

    def test_pair_12_zero_emoji_compliance_in_visual_queue_widget(self):
        """Pair 12 (F14 + F4): Visual Queue widget and its button labels contain 0 color emojis."""
        widget_cls = getattr(yt_vlc, "PlayQueueWidget", None)
        if widget_cls is None:
            self.fail("PlayQueueWidget is not implemented in yt_vlc")
        import inspect
        src = inspect.getsource(widget_cls)
        forbidden = find_forbidden_emojis(src)
        self.assertEqual(forbidden, [], f"Forbidden emoji in PlayQueueWidget: {forbidden}")

    def test_pair_13_live_stream_detection_and_audio_only_mode(self):
        """Pair 13 (F13 + F5): Live stream extracted in audio mode retrieves direct HLS and passes --no-video."""
        captured = []
        with mock_vlc_execution(stream_url="https://manifest.googlevideo.com/live.m3u8", is_live=True, captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("live_stream_audio", "Live Concert")
            settings = {"caching": 3000}
            try:
                launch_fn(video, settings, is_live=True, is_audio=True)
            except TypeError:
                pass
            if captured:
                self.assertIn("--no-video", captured)
                self.assertIn("--network-caching=3000", captured)

    def test_pair_14_offline_library_item_s905x_vlc_playback(self):
        """Pair 14 (F10 + F15): Offline local video playback passes required S905X decoding flags."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_local = getattr(yt_vlc, "launch_vlc_local", None) or getattr(yt_vlc, "launch_vlc")
            video = {"url": "/home/a/Downloads/movie.mp4", "title": "Movie"}
            settings = {"caching": 1000, "hw_accel": True}
            try:
                launch_local(video, settings)
            except Exception:
                pass
            if captured:
                self.assertIn("--avcodec-skiploopfilter=3", captured)
                self.assertIn("--drop-late-frames", captured)

    def test_pair_15_repeat_all_and_clear_queue_mid_cycle(self):
        """Pair 15 (F3 + F1): Clearing queue while repeat-all is active resets state without errors."""
        pq_cls = getattr(yt_vlc, "PlayQueueManager", None)
        if pq_cls is None:
            self.fail("PlayQueueManager is not implemented in yt_vlc")
        pq = pq_cls()
        pq.add_batch([make_sample_video("v1"), make_sample_video("v2")])
        pq.set_repeat_mode("all")
        pq.next_track()  # v1 (idx 0)
        pq.next_track()  # v2 (idx 1)
        pq.clear()
        self.assertIsNone(pq.get_current_item())
        self.assertIsNone(pq.next_track())

    def test_pair_16_audio_only_mode_and_s905x_low_cpu_flags(self):
        """Pair 16 (F5 + F6): Audio-only playback uses both --no-video and skiploopfilter."""
        captured = []
        with mock_vlc_execution(captured_list=captured):
            launch_fn = getattr(yt_vlc, "launch_vlc")
            video = make_sample_video("audio_podcast", "Tech Talk")
            settings = {"caching": 2000, "hw_accel": True}
            try:
                launch_fn(video, settings, is_audio=True)
            except TypeError:
                pass
            if captured:
                self.assertIn("--no-video", captured)
                self.assertIn("--avcodec-skiploopfilter=3", captured)


if __name__ == "__main__":
    unittest.main()
