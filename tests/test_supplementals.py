from pyavalon.avalon import AvalonSupplementalFile
import unittest


class TestSupplementalFile(unittest.TestCase):
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