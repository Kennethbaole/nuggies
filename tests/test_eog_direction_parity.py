import tempfile
import unittest
from unittest.mock import patch
from scripts.eog_direction_parity import compare


class DirectionParityTests(unittest.TestCase):
    def test_comparator_aligns_resets_faults_and_nonzero_csv_origin(self):
        from test_eog_exact_replay import ExactReplayTests
        with tempfile.TemporaryDirectory() as directory:
            csv_path,log_path,profile=ExactReplayTests().make_session(directory,pulse_mode=True)
            from backend.guided_eog import GuidedEOGTest
            from backend.eog_waveform import WaveformProfile
            with patch('scripts.eog_direction_parity.historical_detector',return_value=('fixture',GuidedEOGTest,WaveformProfile)):
                result=compare(csv_path,log_path,profile)
            self.assertTrue(result['identical'])
            self.assertGreater(len(result['events'][0]),0)
            self.assertIn('centering',result['phase_seconds'][0])
