#!/usr/bin/env python3
"""
Empirical Stress Test Suite for yt-vlc
Challenger: challenger_2 (teamwork_preview_challenger)

Tests:
1. GTK UI Threading Safety & Concurrency Stress
2. Channel Playlists Edge Cases & Fuzzing (including empirical bug verification)
3. Offline Library Scanner Robustness (including empirical bug verification)
4. S905X Hardware Compliance (Zero-Emoji, Gtk.Switch alignments, VLC flags)
"""

import os
import sys
import json
import time
import shutil
import tempfile
import threading
import unittest
import re
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, "/mnt/yt-vlc")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GLib, Gdk

import yt_vlc


class TestUIThreadingSafety(unittest.TestCase):
    """Stress tests for multi-threading safety and queue concurrency."""

    def test_play_queue_manager_concurrency_stress(self):
        """20 concurrent threads hammering PlayQueueManager operations simultaneously."""
        pq = yt_vlc.PlayQueueManager()
        pq.clear()

        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    item = {"id": f"vid_{thread_id}_{i}", "title": f"Video {thread_id}-{i}"}
                    pq.add_item(item, position="next" if i % 2 == 0 else "end")
                    if i % 5 == 0:
                        pq.add_batch([{"id": f"b_{thread_id}_{i}_{j}", "title": f"B {j}"} for j in range(3)])
                    if i % 7 == 0:
                        pq.remove_item(0)
                    if i % 3 == 0:
                        pq.next_track()
                    if i % 4 == 0:
                        pq.prev_track()
                    if i % 10 == 0:
                        pq.toggle_shuffle()
                    if i % 15 == 0:
                        pq.cycle_repeat_mode()
                    items = pq.get_items()
                    cur = pq.get_current_item()
            except Exception as e:
                errors.append(f"Thread {thread_id} failed: {type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Concurrent queue operations produced errors: {errors}")
        self.assertIsInstance(pq.get_items(), list)

    def test_download_manager_concurrency_stress(self):
        """Concurrent task submission, query, and cancellation in DownloadManager (mocked download)."""
        dm = yt_vlc.DownloadManager.get_instance()
        with tempfile.TemporaryDirectory() as td:
            task_ids = []
            errors = []

            # Mock out the actual yt-dlp downloader so worker loop finishes instantly without network
            with patch.object(yt_vlc.DownloadManager, "_download_task", lambda self, task: None):
                def adder():
                    try:
                        for i in range(50):
                            tid = dm.add_task(f"vid_stress_{i}", f"Title {i}", quality_format="480", download_dir=td)
                            task_ids.append(tid)
                    except Exception as e:
                        errors.append(f"Adder error: {e}")

                def canceller():
                    try:
                        for _ in range(50):
                            tasks = dm.get_tasks()
                            for t in tasks:
                                if t.get("status") == "queued":
                                    dm.cancel_task(t["task_id"])
                    except Exception as e:
                        errors.append(f"Canceller error: {e}")

                def hook_spammer():
                    try:
                        for i in range(50):
                            dm._ytdl_hook({
                                "status": "downloading",
                                "downloaded_bytes": i * 1000,
                                "total_bytes": 50000,
                                "speed": 1024 * 50,
                                "eta": 10
                            })
                    except Exception as e:
                        errors.append(f"Hook error: {e}")

                threads = [
                    threading.Thread(target=adder),
                    threading.Thread(target=canceller),
                    threading.Thread(target=hook_spammer),
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)

            self.assertEqual(len(errors), 0, f"DownloadManager concurrency failed: {errors}")

    def test_all_background_threads_use_glib_idle_add(self):
        """Static inspection that callbacks and UI updates in threads are wrapped in GLib.idle_add."""
        with open("/mnt/yt-vlc/yt_vlc.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Check launch_vlc thread completion
        self.assertIn("GLib.idle_add(status_callback", code)
        self.assertIn("GLib.idle_add(on_playback_done", code)
        # Check download progress hook
        self.assertIn("GLib.idle_add(self.progress_callback", code)
        # Check image loading callback
        self.assertIn("GLib.idle_add(callback", code)


class TestChannelPlaylistsEdgeCases(unittest.TestCase):
    """Stress tests and fuzzing for channel playlists scraping and parsing."""

    def test_parse_empty_and_malformed_json(self):
        """Parser must not crash on non-dict, empty dict, or missing tabs."""
        self.assertEqual(yt_vlc.parse_channel_playlists_json({}), [])
        self.assertEqual(yt_vlc.parse_channel_playlists_json([]), [])
        self.assertEqual(yt_vlc.parse_channel_playlists_json(None), [])
        self.assertEqual(yt_vlc.parse_channel_playlists_json("string"), [])
        self.assertEqual(yt_vlc.parse_channel_playlists_json({"contents": None}), [])
        self.assertEqual(yt_vlc.parse_channel_playlists_json({"contents": {"twoColumnBrowseResultsRenderer": {}}}), [])

    def test_parse_huge_playlist_count(self):
        """Parser must handle large numbers of items without memory exhaustion or crash."""
        items = []
        for i in range(1000):
            items.append({
                "gridPlaylistRenderer": {
                    "playlistId": f"PL_{i}",
                    "title": {"runs": [{"text": f"Playlist {i}"}]},
                    "videoCountText": {"runs": [{"text": f"{i * 10} videos"}]},
                    "thumbnail": {"thumbnails": [{"url": f"https://img/{i}.jpg"}]}
                }
            })
        data = {
            "contents": {
                "twoColumnBrowseResultsRenderer": {
                    "tabs": [
                        {
                            "tabRenderer": {
                                "content": {
                                    "sectionListRenderer": {
                                        "contents": [
                                            {
                                                "itemSectionRenderer": {
                                                    "contents": [
                                                        {"gridRenderer": {"items": items}}
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
        res = yt_vlc.parse_channel_playlists_json(data)
        self.assertEqual(len(res), 1000)
        self.assertEqual(res[500]["playlist_id"], "PL_500")
        self.assertEqual(res[500]["item_count"], 5000)

    def test_string_title_runs_vulnerability(self):
        """EMPIRICAL FINDING: String title containing 'runs' (e.g. 'Speed runs') causes TypeError and drops all playlists."""
        data = {
            "contents": {
                "twoColumnBrowseResultsRenderer": {
                    "tabs": [
                        {
                            "tabRenderer": {
                                "content": {
                                    "sectionListRenderer": {
                                        "contents": [
                                            {
                                                "itemSectionRenderer": {
                                                    "contents": [
                                                        {
                                                            "gridRenderer": {
                                                                "items": [
                                                                    {
                                                                        "gridPlaylistRenderer": {
                                                                            "playlistId": "PL_RUNS",
                                                                            "title": "Speed runs compilation"
                                                                        }
                                                                    }
                                                                ]
                                                            }
                                                        }
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
        res = yt_vlc.parse_channel_playlists_json(data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["playlist_id"], "PL_RUNS")
        self.assertEqual(res[0]["title"], "Speed runs compilation")

    def test_none_title_vulnerability(self):
        """EMPIRICAL FINDING: When title is None in JSON, TypeError argument of type 'NoneType' is not iterable drops tab."""
        data = {
            "contents": {
                "twoColumnBrowseResultsRenderer": {
                    "tabs": [
                        {
                            "tabRenderer": {
                                "content": {
                                    "sectionListRenderer": {
                                        "contents": [
                                            {
                                                "itemSectionRenderer": {
                                                    "contents": [
                                                        {
                                                            "gridRenderer": {
                                                                "items": [
                                                                    {
                                                                        "gridPlaylistRenderer": {
                                                                            "playlistId": "PL_NULL",
                                                                            "title": None
                                                                        }
                                                                    },
                                                                    {
                                                                        "gridPlaylistRenderer": {
                                                                            "playlistId": "PL_VALID",
                                                                            "title": {"simpleText": "Valid"}
                                                                        }
                                                                    }
                                                                ]
                                                            }
                                                        }
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
        res = yt_vlc.parse_channel_playlists_json(data)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["playlist_id"], "PL_NULL")
        self.assertEqual(res[1]["playlist_id"], "PL_VALID")
        self.assertEqual(res[1]["title"], "Valid")


class TestOfflineLibraryRobustness(unittest.TestCase):
    """Stress tests for offline directory scanner."""

    def test_scan_with_hidden_and_non_media_files(self):
        """Scanner must ignore non-media files, hidden files without valid ext, and corrupted items."""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "valid_video.mp4"), "wb") as f:
                f.write(b"video_bytes")
            with open(os.path.join(td, "valid_video.info.json"), "w") as f:
                json.dump({"title": "Valid Video", "uploader": "Creator", "duration": "03:45", "id": "v1"}, f)

            with open(os.path.join(td, ".hidden_video.mp4"), "wb") as f:
                f.write(b"hidden_bytes")

            with open(os.path.join(td, "notes.txt"), "w") as f:
                f.write("text file")
            with open(os.path.join(td, "part_file.mp4.part"), "wb") as f:
                f.write(b"part_bytes")
            with open(os.path.join(td, ".DS_Store"), "wb") as f:
                f.write(b"store")

            with open(os.path.join(td, "corrupt_json_vid.mkv"), "wb") as f:
                f.write(b"mkv_bytes")
            with open(os.path.join(td, "corrupt_json_vid.info.json"), "w") as f:
                f.write("{this is not valid json")

            res = yt_vlc.scan_offline_library(td)
            ids = [r["id"] for r in res]
            self.assertIn("v1", ids)
            self.assertIn("corrupt_json_vid", ids)
            for r in res:
                self.assertIn(r["ext"], ["mp4", "mkv", "webm", "mp3", "m4a"])

    def test_scan_with_non_dict_json_vulnerability(self):
        """EMPIRICAL FINDING: .info.json containing a JSON array [] raises AttributeError and crashes scan."""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "test_array.mp4"), "wb") as f:
                f.write(b"media")
            with open(os.path.join(td, "test_array.info.json"), "w") as f:
                f.write("[]")  # Valid JSON, but not a dict

            crashed = False
            res = []
            try:
                res = yt_vlc.scan_offline_library(td)
            except AttributeError as e:
                crashed = True
                print(f"[EMPIRICAL RESULT] scan_offline_library crashed on non-dict JSON: {e}")
            self.assertFalse(crashed, "scan_offline_library crashed on non-dict JSON")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["id"], "test_array")

    def test_scan_getsize_oserror_vulnerability(self):
        """EMPIRICAL FINDING: Unhandled OSError during os.path.getsize aborts entire scan."""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "perm_err.mp4"), "wb") as f:
                f.write(b"media")
            with patch("os.path.getsize", side_effect=OSError("Permission denied")):
                crashed = False
                res = []
                try:
                    res = yt_vlc.scan_offline_library(td)
                except OSError as e:
                    crashed = True
                    print(f"[EMPIRICAL RESULT] scan_offline_library crashed on getsize OSError: {e}")
                self.assertFalse(crashed, "scan_offline_library crashed on getsize OSError")
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0]["id"], "perm_err")
                self.assertEqual(res[0]["size"], 0)


class TestS905XCompliance(unittest.TestCase):
    """Audit S905X hardware requirements, zero-emoji, and Gtk.Switch alignments."""

    def test_zero_emoji_in_codebase(self):
        """Ensure no emoji Unicode characters exist anywhere in yt_vlc.py, permitting approved symbols (•, ✓, ✔)."""
        with open("/mnt/yt-vlc/yt_vlc.py", "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Emoji pattern excluding explicitly approved standard Unicode symbols (✓ U+2713, ✔ U+2714, • U+2022)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # Emoticons
            "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
            "\U0001F680-\U0001F6FF"  # Transport and Map
            "\U0001F1E0-\U0001F1FF"  # Regional indicator symbols
            "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
            "\U0001FA00-\U0001FA6F"  # Chess Symbols
            "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
            "\U00002700-\U00002712"  # Dingbats before check marks
            "\U00002715-\U000027BF"  # Dingbats after check marks
            "]+",
            flags=re.UNICODE
        )

        violations = []
        for line_num, line in enumerate(lines, 1):
            matches = emoji_pattern.findall(line)
            if matches:
                violations.append((line_num, matches, line.strip()))

        self.assertEqual(len(violations), 0, f"Found {len(violations)} emoji violations: {violations[:5]}")

    def test_switch_alignment_in_grids(self):
        """Ensure all Gtk.Switch instances have START halign and CENTER valign."""
        with open("/mnt/yt-vlc/yt_vlc.py", "r", encoding="utf-8") as f:
            code = f.read()

        switch_instances = re.findall(r"(\w+)\s*=\s*Gtk\.Switch\(\)", code)
        self.assertGreater(len(switch_instances), 0, "No switches found in codebase")

        for sw in set(switch_instances):
            self.assertIn(f"{sw}.set_halign(Gtk.Align.START)", code, f"{sw} missing START halign")
            self.assertIn(f"{sw}.set_valign(Gtk.Align.CENTER)", code, f"{sw} missing CENTER valign")

    def test_vlc_s905x_flags_execution(self):
        """Empirically test VLC command generation for live, audio-only, queue, and VOD modes."""
        with patch("yt_vlc.extract_stream_url", return_value=("http://manifest.googlevideo.com/live.m3u8", None, True)):
            with patch("subprocess.Popen") as mock_popen:
                proc = MagicMock()
                mock_popen.return_value = proc
                yt_vlc.launch_vlc(
                    {"id": "live_vid", "title": "Test Stream", "is_live": True},
                    in_queue=True,
                    is_audio=True
                )
                time.sleep(0.2)
                self.assertTrue(mock_popen.called)
                cmd = mock_popen.call_args[0][0]

                # Check hardware decoding flags
                self.assertIn("--avcodec-skiploopfilter=3", cmd)
                self.assertIn("--drop-late-frames", cmd)
                self.assertIn("--skip-frames", cmd)
                self.assertIn("--no-video-title-show", cmd)

                # Check feature flags
                self.assertIn("--network-caching=3000", cmd)
                self.assertIn("--play-and-exit", cmd)
                self.assertIn("--no-video", cmd)


if __name__ == "__main__":
    unittest.main()
