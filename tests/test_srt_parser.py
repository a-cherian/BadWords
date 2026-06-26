import sys
import os
import unittest
import tempfile
import json

# Add src to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from engine import _process_srt_to_json, _parse_srt_time
from datetime import timedelta

class TestSRTParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.srt_path = os.path.join(self.temp_dir, "test.srt")

    def create_srt(self, content):
        with open(self.srt_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_parse_srt_time(self):
        self.assertEqual(_parse_srt_time("00:00:01,000"), timedelta(seconds=1.0))
        self.assertEqual(_parse_srt_time("00:01:02,500"), timedelta(seconds=62.5))
        self.assertEqual(_parse_srt_time("01:00:00,000"), timedelta(seconds=3600.0))
        self.assertEqual(_parse_srt_time("00:00:00,001"), timedelta(milliseconds=1))

    def test_process_srt_to_json_basic(self):
        srt_content = """1
00:00:01,500 --> 00:00:02,500
Hello world.

2
00:00:03,000 --> 00:00:05,000
This is a test.
"""
        self.create_srt(srt_content)
        result = _process_srt_to_json(self.srt_path, lang="en")
        
        self.assertEqual(result["language"], "en")
        segments = result["segments"]
        
        # It injects a [SILENCE] segment at the beginning because 0.0 -> 1.5 is >= 1.0s gap
        self.assertEqual(segments[0]["text"], "[SILENCE]")
        
        # Check the first real segment
        seg1 = segments[1]
        self.assertEqual(seg1["start"], 1.5)
        self.assertEqual(seg1["end"], 2.5)
        self.assertEqual(seg1["text"], "Hello world.")
        
        words1 = seg1["words"]
        self.assertEqual(len(words1), 10) # "H", "e", "l", "l", "o", "w", "o", "r", "l", "d."
        self.assertEqual(words1[0]["word"], "H")
        self.assertEqual(words1[-1]["word"], "d.")
        
        # Word timing logic in _process_srt_to_json interpolates
        self.assertTrue(1.5 <= words1[0]["start"] <= 2.5)
        
        # Probability should default to 1.0
        self.assertEqual(words1[0]["probability"], 1.0)

    def test_process_srt_to_json_time_scaling(self):
        srt_content = """1
00:00:01,000 --> 00:00:02,000
Testing scaling.
"""
        self.create_srt(srt_content)
        result = _process_srt_to_json(self.srt_path, lang="en", time_scale=2.0)
        
        # In _process_srt_to_json, time_scale is ONLY applied to the rewritten SRT file, not the returned JSON.
        with open(self.srt_path, 'r', encoding='utf-8') as f:
            rewritten_content = f.read()
        
        # 1s * 2 = 2s, 2s * 2 = 4s
        self.assertIn("00:00:02,000 --> 00:00:04,000", rewritten_content)

    def test_process_srt_to_json_empty(self):
        self.create_srt("")
        result = _process_srt_to_json(self.srt_path, lang="zh")
        self.assertEqual(result["segments"], [])

if __name__ == '__main__':
    unittest.main()
