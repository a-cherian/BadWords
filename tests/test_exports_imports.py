import sys
import os
import unittest
from unittest.mock import MagicMock
import tempfile
import json

# Add src to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from engine import AudioEngine

class TestExportsImports(unittest.TestCase):
    def setUp(self):
        self.mock_os_doctor = MagicMock()
        self.mock_resolve_handler = MagicMock()
        self.engine = AudioEngine(self.mock_os_doctor, self.mock_resolve_handler)
        self.temp_dir = tempfile.mkdtemp()
        self.project_file = os.path.join(self.temp_dir, "project.bwproj")

    def test_save_and_load_project_state(self):
        data_packet = {
            "lang_code": "zh",
            "settings": {"ai_use_whisperjav_for_zh": True}, # settings contain the flag
            "words_data": [
                {"word": "test", "start": 1.1234, "end": 2.5678, "is_segment_start": True}
            ]
        }

        # Mock current_srt_content to simulate Whisperjav SRT generation
        self.engine.current_srt_content = "1\n00:00:01,000 --> 00:00:02,000\nTest\n"

        # Save project
        result = self.engine.save_project_state(self.project_file, data_packet)
        self.assertTrue(result)
        
        # Verify JSON was saved correctly and floats were optimized (rounded to 3 decimals)
        with open(self.project_file, 'r', encoding='utf-8') as f:
            saved_json = json.load(f)
        
        self.assertEqual(saved_json["lang_code"], "zh")
        self.assertTrue(saved_json["settings"].get("ai_use_whisperjav_for_zh"))
        
        words = saved_json["words_data"]
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["start"], 1.123) # Rounded from 1.1234
        self.assertEqual(words[0]["end"], 2.568)   # Rounded from 2.5678

        # Verify SRT was saved alongside
        srt_file = self.project_file.rsplit('.', 1)[0] + ".srt"
        self.assertTrue(os.path.exists(srt_file))
        with open(srt_file, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        self.assertEqual(srt_content, "1\n00:00:01,000 --> 00:00:02,000\nTest\n")

        # Load project
        loaded_state, segments = self.engine.load_project_state(self.project_file)
        self.assertEqual(loaded_state["lang_code"], "zh")
        self.assertEqual(len(segments), 1) # One segment reconstructed from is_segment_start
        self.assertEqual(len(segments[0]), 1)
        self.assertEqual(segments[0][0]["word"], "test")

if __name__ == '__main__':
    unittest.main()
