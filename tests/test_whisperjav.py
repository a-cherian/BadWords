import sys
import os
import unittest
from unittest.mock import patch, MagicMock, mock_open
import tempfile
import json
import shlex

# Add src to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from engine import AudioEngine

class TestWhisperjav(unittest.TestCase):
    def setUp(self):
        # Create a mock engine instance
        self.mock_os_doctor = MagicMock()
        self.mock_os_doctor.is_linux = False
        self.mock_resolve_handler = MagicMock()
        
        # We patch some Engine methods/properties to avoid full initialization issues
        with patch.object(AudioEngine, 'verify_hardware_compute', return_value=True):
            self.engine = AudioEngine(self.mock_os_doctor, self.mock_resolve_handler)
            self.engine.models_dir = "/mock/models/dir"
            
        self.output_dir = tempfile.mkdtemp()
        self.audio_path = "/mock/audio/test_file.wav"
        self.mock_os_doctor.get_temp_folder.return_value = self.output_dir
        
        # Default prefs to force whisperjav
        self.prefs = {
            'ai_use_whisperjav_for_zh': True,
            'ai_whisperjav_path': '/mock/bin/whisperjav',
            'ai_whisperjav_args': '--mode qwen --language chinese'
        }
        self.mock_os_doctor.get_all_prefs.return_value = self.prefs

    @patch('engine.os.path.exists')
    @patch('engine.subprocess.Popen')
    @patch('engine._process_srt_to_json')
    @patch('glob.glob')
    @patch('shutil.copy')
    @patch('builtins.open', new_callable=mock_open)
    def test_whisperjav_command_construction(self, mock_file, mock_copy, mock_glob, mock_process_srt, mock_popen, mock_exists):
        # Mock os.path.exists to return True ONLY for the whisperjav path
        def side_effect_exists(path):
            if path == '/mock/bin/whisperjav':
                return True
            return os.path.exists(path) # fallback
        mock_exists.side_effect = side_effect_exists
        
        # Mock glob to return a fake srt
        mock_glob.return_value = [os.path.join(self.output_dir, "test_file.srt")]
        
        # Mock JSON processing return
        mock_process_srt.return_value = {"segments": [], "words": []}
        
        # Mock subprocess to return empty stdout
        process_mock = MagicMock()
        process_mock.stdout.readline.side_effect = [""]
        process_mock.poll.return_value = 0
        mock_popen.return_value = process_mock

        # Call run_whisper for a Chinese language
        json_path = self.engine.run_whisper(
            audio_path=self.audio_path,
            model="large-v3",
            lang="zh",
            verbatim=True,
            device_mode="cpu",
            compute_type="float32",
            initial_prompt="custom prompt",
            script_content="This is the script context",
            time_scale_correction=1.0
        )
        
        # Verify subprocess.Popen was called with correct command
        self.assertTrue(mock_popen.called)
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        
        # Base command checks
        self.assertEqual(cmd[0], '/mock/bin/whisperjav')
        self.assertEqual(cmd[1], '/mock/audio/test_file.wav')
        self.assertIn('--mode', cmd)
        self.assertIn('qwen', cmd)
        
        # Context file checks
        context_path = os.path.join(self.output_dir, "test_file_context.txt")
        self.assertIn('--qwen-context-file', cmd)
        self.assertEqual(cmd[cmd.index('--qwen-context-file') + 1], context_path)
        
        # Initial prompt check
        self.assertIn('--initial-prompt', cmd)
        # Verify script_content is written to the context file
        mock_file.assert_any_call(context_path, 'w', encoding='utf-8')
        mock_file().write.assert_any_call("This is the script context")
        
        # Verify JSON post-processing was appended with is_whisperjav
        mock_process_srt.assert_called_once()
        
        # Check that the json result was saved with is_whisperjav appended
        # We need to find the call to json.dump (which writes to the file)
        # Because we mocked open, the written content is not actually parsed by us here,
        # but mock_process_srt.return_value gets mutated in engine.py: json_data["is_whisperjav"] = True
        self.assertTrue(mock_process_srt.return_value.get("is_whisperjav"))
        
        self.assertEqual(json_path, os.path.join(self.output_dir, "test_file.json"))

    @patch('engine.os.path.exists')
    @patch('engine.subprocess.Popen')
    @patch('engine._process_srt_to_json')
    @patch('glob.glob')
    @patch('shutil.copy')
    @patch('builtins.open', new_callable=mock_open)
    def test_whisperjav_progress_parsing(self, mock_file, mock_copy, mock_glob, mock_process_srt, mock_popen, mock_exists):
        # Mock os.path.exists to return True ONLY for the whisperjav path
        def side_effect_exists(path):
            if path == '/mock/bin/whisperjav':
                return True
            return os.path.exists(path) # fallback
        mock_exists.side_effect = side_effect_exists
        
        mock_glob.return_value = [os.path.join(self.output_dir, "test_file.srt")]
        mock_process_srt.return_value = {}
        
        # We'll simulate a stream of output lines from whisperjav
        simulated_output = [
            "[DecoupledPipeline] Generating scene 1/2\n",
            "ASR Text Gen | Scene 1/2 | 50%|\n",
            "Aligning | Scene 1/2\n",
            "[DecoupledPipeline] Aligning scene 1/2\n",
            ""
        ]
        
        process_mock = MagicMock()
        process_mock.stdout.readline.side_effect = simulated_output
        process_mock.poll.return_value = 0
        mock_popen.return_value = process_mock

        # Callbacks
        prog_cb = MagicMock()
        status_cb = MagicMock()
        align_cb = MagicMock()

        self.engine.run_whisper(
            audio_path=self.audio_path,
            model="large-v3",
            lang="zh",
            verbatim=True,
            device_mode="cpu",
            compute_type="float32",
            initial_prompt="",
            script_content="",
            time_scale_correction=1.0,
            progress_callback=prog_cb,
            status_callback=status_cb,
            align_progress_callback=align_cb
        )
        
        # Verify that progress tracking updated correctly
        # The first call is usually 0 when starting
        prog_cb.assert_any_call(0)
        # Final call is 100
        prog_cb.assert_any_call(100)
        
        # We verify that status_callback was called for "Transcribing..." and "Aligning..."
        status_cb.assert_any_call("Transcribing...")
        status_cb.assert_any_call("Aligning...")
        
        # Verify alignment callback was called based on regex
        align_cb.assert_called()

if __name__ == '__main__':
    unittest.main()
