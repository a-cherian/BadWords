import sys
import os
import unittest
from unittest.mock import MagicMock

# Add src to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from engine import AudioEngine

class TestPipelineDataStructure(unittest.TestCase):
    def setUp(self):
        self.mock_os_doctor = MagicMock()
        self.mock_resolve_handler = MagicMock()
        self.engine = AudioEngine(self.mock_os_doctor, self.mock_resolve_handler)
        # Mock prefs for padding
        self.mock_os_doctor.get_all_prefs.return_value = {
            'pad': 0.0,
            'silence_min_dur': 1.0
        }

    def test_silence_smearing_skipped_for_whisperjav(self):
        # When a word overlaps a detected silence
        # Faster-whisper normally gets clipped to the silence boundary
        # Whisperjav should skip this clipping because it smears words
        
        json_data_wj = {
            "segments": [{
                "start": 1.0, "end": 3.0,
                "text": "Smeared",
                "words": [{"word": "Smeared", "start": 1.0, "end": 3.0, "probability": 1.0}]
            }],
            "is_whisperjav": True
        }
        
        json_data_fw = {
            "segments": [{
                "start": 1.0, "end": 3.0,
                "text": "Smeared",
                "words": [{"word": "Smeared", "start": 1.0, "end": 3.0, "probability": 1.0}]
            }],
            "is_whisperjav": False
        }
        
        # Silence completely engulfs the end of the word
        silence_ranges = [{'s': 2.0, 'e': 4.0}]
        
        # Test WhisperJav (Skipped clipping)
        all_words_wj, merged_wj = self.engine._build_data_structure(
            json_data_wj, silence_ranges, filler_words=[], fps=24.0, time_scale_correction=1.0
        )
        
        # Find the word "Smeared" in the merged output
        # all_words_wj is a list of words.
        smeared_word_wj = next(w for w in all_words_wj if w.get('text') == "Smeared" or w.get('word') == "Smeared")
        self.assertEqual(smeared_word_wj['start'], 1.0)
        self.assertEqual(smeared_word_wj['end'], 3.0) # Not clipped
        
        # Test Faster Whisper (Gets clipped)
        all_words_fw, merged_fw = self.engine._build_data_structure(
            json_data_fw, silence_ranges, filler_words=[], fps=24.0, time_scale_correction=1.0
        )
        
        smeared_word_fw = next(w for w in all_words_fw if w.get('text') == "Smeared" or w.get('word') == "Smeared")
        self.assertEqual(smeared_word_fw['start'], 1.0)
        # In engine.py: elif s['s'] > w['start'] and s['e'] >= w['end']: w['end'] = s['s']
        # Due to default pad of 0.05, the silence start is shifted to 2.05
        self.assertEqual(smeared_word_fw['end'], 2.05) # Clipped to silence start

    def test_auto_tune_silence_db(self):
        # Create a dummy json data with 3s of gaps
        json_data = {
            'segments': [
                {'words': [
                    {'start': 0.0, 'end': 1.0},
                    {'start': 3.0, 'end': 5.0}, # gap of 2s
                    {'start': 6.0, 'end': 7.0}  # gap of 1s
                ]}
            ]
        }
        
        # Mock detect_silence to return different total silence durations for different dB
        def mock_detect_silence(wav, db, min_dur):
            if db == -50.0:
                return [{'s': 0.0, 'e': 100.0}] # 100s
            elif db == -45.0:
                return [{'s': 1.0, 'e': 3.0}, {'s': 5.0, 'e': 6.0}] # Exactly 3s total
            elif db == -40.0:
                return [{'s': 1.0, 'e': 2.0}] # 1s total
            return []
            
        self.engine.detect_silence = mock_detect_silence
        
        best_ranges = self.engine.auto_tune_silence_db('dummy.wav', json_data, min_dur=0.2, time_scale=1.0)
        
        # Should pick -45.0dB because it perfectly matches the 3s target
        self.assertEqual(len(best_ranges), 2)
        self.assertEqual(best_ranges[0]['s'], 1.0)
        self.assertEqual(best_ranges[0]['e'], 3.0)

if __name__ == '__main__':
    unittest.main()
