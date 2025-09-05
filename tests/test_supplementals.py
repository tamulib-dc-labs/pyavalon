from pyavalon.avalon import AvalonSupplementalFile
import unittest
from unittest.mock import patch, Mock


class TestSupplementalFile(unittest.TestCase):
    def setUp(self):
        self.avalon_file = AvalonSupplementalFile("v118rd76r", "pre")

    @patch.object(AvalonSupplementalFile, 'get')
    def test_get_file_success(self, mock_get):
        mock_response = {
            'id': 131,
            'label': 'Part 1: PDF Transcript',
            'language': 'English',
            'machine_generated': False,
            'treat_as_transcript': False,
            'type': 'generic'
        }
        mock_get.return_value = mock_response
        identifier = "131"
        result = self.avalon_file.get_file(identifier)
        expected_url = f"{self.avalon_file.base}/master_files/v118rd76r/supplemental_files/131.json"
        mock_get.assert_called_once_with(expected_url)
        self.assertEqual(result, mock_response)

    def test_bad_captions(self):
        suppl = AvalonSupplementalFile(fedora_id="qv33rw73v")
        valid = suppl.is_valid_vtt("fixtures/bad-captions.vtt")
        self.assertFalse(valid)

    def test_good_captions(self):
        suppl = AvalonSupplementalFile(fedora_id="qv33rw73v")
        valid = suppl.is_valid_vtt("fixtures/good-captions.vtt")
        self.assertTrue(valid)

if __name__ == "__main__":
    unittest.main()