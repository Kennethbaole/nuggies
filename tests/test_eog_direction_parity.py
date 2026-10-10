import tempfile
import unittest
from scripts.eog_direction_parity import compare


class DirectionParityTests(unittest.TestCase):
    def test_historical_direction_path_matches_across_resets_and_faults(self):
        from test_eog_exact_replay import ExactReplayTests
        with tempfile.TemporaryDirectory() as directory:
            csv_path,log_path,profile=ExactReplayTests().make_session(directory,pulse_mode=True)
            result=compare(csv_path,log_path,profile)
            self.assertTrue(result['identical'])
            self.assertGreater(len(result['events'][0]),0)
            self.assertIn('centering',result['phase_seconds'][0])
