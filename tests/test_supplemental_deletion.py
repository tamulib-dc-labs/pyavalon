import csv
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from pyavalon.avalon import AvalonMediaObject, AvalonSupplementalFile
from pyavalon.avalon.supplementals import (
    SupplementalCsvError,
    delete_supplemental_files,
    parse_csv,
    resolve_type,
    select,
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "fixtures", "supplemental-deletion.csv"
)

# One master file holding every shape that matters.
MIXED = [
    {"id": 1, "type": "caption", "label": "episode.srt", "treat_as_transcript": False},
    {"id": 2, "type": "caption", "label": "flagged.vtt", "treat_as_transcript": True},
    {"id": 3, "type": "transcript", "label": "transcript.vtt", "treat_as_transcript": True},
    {"id": 4, "type": "generic", "label": "Program notes.pdf", "treat_as_transcript": False},
    {"id": 5, "type": "generic", "label": "spreadsheet.xlsx", "treat_as_transcript": False},
]


def write_csv(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class TestParsing(unittest.TestCase):
    def test_fixture_parses(self):
        rows = parse_csv(FIXTURE)
        self.assertEqual(
            [(work, kind) for _row, work, kind in rows],
            [("w6634371m", "generic"), ("nk322d54j", "caption"), ("b2773w02m", "transcript")],
        )

    def test_type_aliases_and_case_fold(self):
        for raw, expected in [("Captions", "caption"), ("  transcript ", "transcript"),
                              ("Generic", "generic"), ("GENERICS", "generic")]:
            self.assertEqual(resolve_type(raw), expected)

    def test_pdf_is_refused_with_guidance(self):
        """PDFs are stored as generic, which also holds unrelated attachments,
        so the caller has to say generic and mean it."""
        for raw in ("pdf", "PDF", "pdfs"):
            with self.assertRaises(SupplementalCsvError) as caught:
                resolve_type(raw)
            self.assertIn("generic", str(caught.exception))

    def test_pdf_in_a_csv_aborts_the_run(self):
        path = write_csv("work id,type\nabc123,pdf\n")
        with self.assertRaises(SupplementalCsvError):
            parse_csv(path)

    def test_unknown_type_aborts(self):
        path = write_csv("work id,type\nabc123,subtitles\n")
        with self.assertRaises(SupplementalCsvError) as caught:
            parse_csv(path)
        self.assertIn("subtitles", str(caught.exception))

    def test_missing_type_column_aborts(self):
        path = write_csv("work id\nabc123\n")
        with self.assertRaises(SupplementalCsvError):
            parse_csv(path)

    def test_missing_work_id_column_aborts(self):
        path = write_csv("type\ngeneric\n")
        with self.assertRaises(SupplementalCsvError):
            parse_csv(path)

    def test_work_id_header_variants(self):
        for header in ("work id", "work_id", "Media Object ID", "id"):
            path = write_csv(f"{header},type\nabc123,generic\n")
            _row, work_id, kind = parse_csv(path)[0]
            self.assertEqual((work_id, kind), ("abc123", "generic"), header)

    def test_row_missing_a_type_aborts(self):
        path = write_csv("work id,type\nabc123,\n")
        with self.assertRaises(SupplementalCsvError):
            parse_csv(path)


class TestSelection(unittest.TestCase):
    def test_caption_selects_only_captions(self):
        self.assertEqual([i["id"] for i in select(MIXED, "caption")], [1, 2])

    def test_transcript_ignores_captions_flagged_as_transcripts(self):
        """id 2 is a caption with treat_as_transcript; the CSV asked for
        transcripts, not captions."""
        self.assertEqual([i["id"] for i in select(MIXED, "transcript")], [3])

    def test_generic_selects_every_generic_regardless_of_label(self):
        self.assertEqual([i["id"] for i in select(MIXED, "generic")], [4, 5])


class TestDeleteSupplementalFiles(unittest.TestCase):
    def setUp(self):
        key = patch.dict(os.environ, {"AVALON_PRE": "test-key"}, clear=False)
        key.start()
        self.addCleanup(key.stop)

        self.report = os.path.join(tempfile.mkdtemp(), "report.csv")
        # one work, two master files -- supplementals hang off the master files
        self.works = {"w1": ["mf1", "mf2"]}
        self.listing = {"mf1": list(MIXED), "mf2": [
            {"id": 8, "type": "generic", "label": "second.pdf"},
        ]}
        self.deleted = []

        def fake_work(inner_self, type="media_object"):
            files = self.works.get(inner_self.identifier)
            if files is None:
                return {"errors": ["Not found."]}
            return {"id": inner_self.identifier, "files": [{"id": f} for f in files]}

        def fake_get_files(inner_self):
            return list(self.listing.get(inner_self.fedora_id, []))

        def fake_delete(inner_self, identifier):
            self.deleted.append((inner_self.fedora_id, identifier))
            return Mock(status_code=200, text="")

        for target, name, replacement in (
            (AvalonMediaObject, "get_object", fake_work),
            (AvalonSupplementalFile, "get_files", fake_get_files),
            (AvalonSupplementalFile, "delete_file", fake_delete),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_csv(self, text, **kwargs):
        return delete_supplemental_files(
            write_csv(text), instance="pre", report_path=self.report, verbose=False, **kwargs
        )

    def test_sweeps_every_master_file_on_the_work(self):
        """The CSV names a work; supplementals live on its master files."""
        self.run_csv("work id,type\nw1,generic\n")
        self.assertEqual(self.deleted, [("mf1", 4), ("mf1", 5), ("mf2", 8)])

    def test_deletes_only_the_matching_type(self):
        self.run_csv("work id,type\nw1,transcript\n")
        self.assertEqual(self.deleted, [("mf1", 3)])

    def test_report_records_the_master_file_each_file_came_from(self):
        self.run_csv("work id,type\nw1,generic\n")
        with open(self.report, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({r["work id"] for r in rows}, {"w1"})
        self.assertEqual([r["master file id"] for r in rows], ["mf1", "mf1", "mf2"])
        self.assertEqual(rows[0]["label"], "Program notes.pdf")
        self.assertEqual(rows[0]["deleted"], "yes")

    def test_dry_run_deletes_nothing_but_still_reports(self):
        records = self.run_csv("work id,type\nw1,generic\n", dry_run=True)
        self.assertEqual(self.deleted, [])
        self.assertEqual({r["status"] for r in records}, {"dry run"})

    def test_no_matches_is_recorded_not_skipped(self):
        """A typo'd id must not look the same as a clean sweep."""
        self.listing = {"mf1": [], "mf2": []}
        records = self.run_csv("work id,type\nw1,caption\n")
        self.assertEqual(self.deleted, [])
        self.assertEqual(len(records), 1)
        self.assertIn("no caption files found", records[0]["status"])

    def test_an_unknown_work_reports_the_read_error(self):
        records = self.run_csv("work id,type\nnope,generic\n")
        self.assertEqual(self.deleted, [])
        self.assertIn("Not found.", records[0]["status"])

    def test_a_work_with_no_master_files(self):
        self.works["empty"] = []
        records = self.run_csv("work id,type\nempty,generic\n")
        self.assertIn("no master files", records[0]["status"])

    def test_a_failed_delete_is_reported_and_the_run_continues(self):
        def flaky(inner_self, identifier):
            if identifier == 4:
                return Mock(status_code=500, text="boom")
            self.deleted.append((inner_self.fedora_id, identifier))
            return Mock(status_code=200, text="")

        with patch.object(AvalonSupplementalFile, "delete_file", flaky):
            records = self.run_csv("work id,type\nw1,generic\n")

        statuses = [r["status"] for r in records]
        self.assertTrue(any("500" in s for s in statuses))
        self.assertEqual(self.deleted, [("mf1", 5), ("mf2", 8)])

    def test_a_refused_listing_reports_the_real_reason(self):
        def refused(inner_self):
            return {"errors": ["Permission denied."]}

        with patch.object(AvalonSupplementalFile, "get_files", refused):
            records = self.run_csv("work id,type\nw1,generic\n")
        self.assertEqual(self.deleted, [])
        self.assertTrue(any("Permission denied." in r["status"] for r in records))

    def test_missing_api_key_aborts_before_any_delete(self):
        with patch.dict(os.environ, {"AVALON_PRE": ""}, clear=False):
            with self.assertRaises(Exception) as caught:
                self.run_csv("work id,type\nw1,generic\n")
        self.assertIn("AVALON_PRE", str(caught.exception))
        self.assertEqual(self.deleted, [])

    def test_dry_run_needs_no_key(self):
        with patch.dict(os.environ, {"AVALON_PRE": ""}, clear=False):
            records = self.run_csv("work id,type\nw1,generic\n", dry_run=True)
        self.assertEqual({r["status"] for r in records}, {"dry run"})


if __name__ == "__main__":
    unittest.main()
