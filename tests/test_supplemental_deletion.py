import os
import tempfile
import unittest
from unittest.mock import patch

from pyavalon.avalon.supplementals import (
    SupplementalCsvError,
    describe_overlap,
    is_pdf,
    read_deletion_csv,
    select_files,
)

FIXTURE = os.path.join("fixtures", "supplemental-deletions.csv")

# the real shape returned by t722h9075 on prod
LISTING = [
    {"id": 6947, "type": "transcript", "label": "Transcript in English",
     "language": "English", "treat_as_transcript": False, "machine_generated": True},
    {"id": 7598, "type": "generic", "label": "Transcript in English",
     "language": "English", "treat_as_transcript": False, "machine_generated": False},
]


def write_csv(text):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    handle.write(text)
    handle.close()
    return handle.name


class TestReadDeletionCsv(unittest.TestCase):
    def test_fixture_parses(self):
        rows = read_deletion_csv(FIXTURE)
        self.assertEqual(
            [(r.file_id, r.requested_type) for r in rows],
            [("t722h9075", "pdf"), ("9593tv433", "transcript"), ("nz8060020", "caption")],
        )

    def test_captions_and_caption_are_the_same_request(self):
        for spelling in ("captions", "caption", "Captions", "CAPTION"):
            path = write_csv(f"file id,type\nabc123,{spelling}\n")
            try:
                self.assertEqual(read_deletion_csv(path)[0].requested_type, "caption")
            finally:
                os.unlink(path)

    def test_pdf_maps_to_generic(self):
        path = write_csv("file id,type\nabc123,pdf\n")
        try:
            self.assertEqual(read_deletion_csv(path)[0].avalon_type, "generic")
        finally:
            os.unlink(path)

    def test_file_id_column_aliases(self):
        for header in ("file id", "File ID", "file_id", "id", "Master File ID"):
            path = write_csv(f"{header},type\nabc123,pdf\n")
            try:
                self.assertEqual(read_deletion_csv(path)[0].file_id, "abc123", header)
            finally:
                os.unlink(path)

    def test_audio_description_spellings(self):
        for spelling in ("audio_description", "Audio Description", "description",
                         "descriptions", "audio"):
            path = write_csv(f"file id,type\nabc123,{spelling}\n")
            try:
                row = read_deletion_csv(path)[0]
            finally:
                os.unlink(path)
            self.assertEqual(row.requested_type, "audio_description", spelling)
            self.assertEqual(row.avalon_type, "audio_description", spelling)

    def test_generic_maps_to_generic(self):
        path = write_csv("file id,type\nabc123,generic\n")
        try:
            row = read_deletion_csv(path)[0]
        finally:
            os.unlink(path)
        self.assertEqual(row.requested_type, "generic")
        self.assertEqual(row.avalon_type, "generic")

    def test_pdf_and_generic_are_distinct_requests(self):
        # both target Avalon's generic bucket but differ in verification
        path = write_csv("file id,type\nabc123,pdf\nabc123,generic\n")
        try:
            rows = read_deletion_csv(path)
        finally:
            os.unlink(path)
        self.assertEqual([r.requested_type for r in rows], ["pdf", "generic"])
        self.assertEqual({r.avalon_type for r in rows}, {"generic"})

    def test_unknown_type_is_refused(self):
        path = write_csv("file id,type\nabc123,thumbnail\n")
        try:
            with self.assertRaises(SupplementalCsvError) as caught:
                read_deletion_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("thumbnail", str(caught.exception))

    def test_missing_columns_are_refused(self):
        for text in ("type\npdf\n", "file id\nabc123\n"):
            path = write_csv(text)
            try:
                with self.assertRaises(SupplementalCsvError):
                    read_deletion_csv(path)
            finally:
                os.unlink(path)

    def test_blank_type_is_refused(self):
        path = write_csv("file id,type\nabc123,\n")
        try:
            with self.assertRaises(SupplementalCsvError):
                read_deletion_csv(path)
        finally:
            os.unlink(path)

    def test_duplicate_file_id_and_type_is_refused(self):
        path = write_csv("file id,type\nabc123,pdf\nabc123,pdf\n")
        try:
            with self.assertRaises(SupplementalCsvError):
                read_deletion_csv(path)
        finally:
            os.unlink(path)

    def test_same_file_id_with_different_types_is_allowed(self):
        path = write_csv("file id,type\nabc123,pdf\nabc123,transcript\n")
        try:
            self.assertEqual(len(read_deletion_csv(path)), 2)
        finally:
            os.unlink(path)


class TestSelection(unittest.TestCase):
    def test_pdf_selects_generic_files(self):
        self.assertEqual([e["id"] for e in select_files(LISTING, "pdf")], [7598])

    def test_transcript_does_not_select_the_generic_pdf(self):
        self.assertEqual([e["id"] for e in select_files(LISTING, "transcript")], [6947])

    def test_caption_selects_nothing_here(self):
        self.assertEqual(select_files(LISTING, "caption"), [])

    def test_is_pdf_by_content_type_and_by_magic_bytes(self):
        self.assertTrue(is_pdf("application/pdf", b"%PDF-1.7"))
        self.assertTrue(is_pdf("application/pdf; charset=binary", b""))
        self.assertTrue(is_pdf("application/octet-stream", b"%PDF-1.4"))
        self.assertFalse(is_pdf("text/vtt", b"WEBVTT"))
        self.assertFalse(is_pdf("", b""))

    def test_audio_description_selects_only_that_type(self):
        listing = LISTING + [
            {"id": 900, "type": "audio_description", "label": "Described audio",
             "treat_as_transcript": False},
        ]
        self.assertEqual(
            [e["id"] for e in select_files(listing, "audio_description")], [900]
        )
        # and it must not be swept up by the generic bucket
        self.assertEqual([e["id"] for e in select_files(listing, "generic")], [7598])

    def test_generic_selects_the_same_candidates_as_pdf(self):
        self.assertEqual(
            [e["id"] for e in select_files(LISTING, "generic")],
            [e["id"] for e in select_files(LISTING, "pdf")],
        )

    def test_describe_overlap_names_dual_tagged_files(self):
        entries = [
            {"id": 1, "label": "Captions", "treat_as_transcript": True},
            {"id": 2, "label": "Plain captions", "treat_as_transcript": False},
        ]
        self.assertEqual(describe_overlap(entries), ["Captions"])


class TestDeletionDriver(unittest.TestCase):
    """The driver, with the network mocked out."""

    CONTENT = {6947: ("text/vtt", b"WEBVTT\n\n"), 7598: ("application/pdf", b"%PDF-1.4 body")}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.report = os.path.join(self.tmp, "report.csv")
        self.backups = os.path.join(self.tmp, "backups")
        self.deleted = []

    def run_driver(self, csv_text="file id,type\nt722h9075,pdf\n", listing=None, **kwargs):
        from pyavalon.avalon import avalon as avalon_module

        entries = LISTING if listing is None else listing
        path = write_csv(csv_text)

        def fake_list(inner_self):
            return [dict(e) for e in entries]

        def fake_fetch(inner_self, supplemental_id, max_bytes=None):
            return self.CONTENT[supplemental_id]

        def fake_delete(inner_self, supplemental_id):
            self.deleted.append((inner_self.identifier, supplemental_id))

        try:
            with patch.object(avalon_module.AvalonMasterFile, "get_supplemental_files", fake_list), \
                 patch.object(avalon_module.AvalonMasterFile, "fetch_supplemental_file", fake_fetch), \
                 patch.object(avalon_module.AvalonMasterFile, "delete_supplemental_file", fake_delete), \
                 patch.object(avalon_module.AvalonMasterFile, "_AvalonBase__get_key", staticmethod(lambda x: "k")):
                return avalon_module.delete_supplemental_files_from_csv(
                    path, prod_or_pre="pre",
                    backup_directory=self.backups, report_csv=self.report,
                    verbose=False, **kwargs,
                )
        finally:
            os.unlink(path)

    def test_deletes_the_pdf_from_the_ticket_example(self):
        rows = self.run_driver()
        self.assertEqual(self.deleted, [("t722h9075", 7598)])
        self.assertEqual([r["action"] for r in rows], ["deleted"])

    def test_does_not_touch_the_vtt_transcript(self):
        self.run_driver()
        self.assertNotIn(("t722h9075", 6947), self.deleted)

    def test_generic_file_that_is_not_a_pdf_is_left_alone(self):
        listing = [{"id": 7598, "type": "generic", "label": "Notes.docx",
                    "treat_as_transcript": False}]
        self.CONTENT[7598] = ("application/vnd.openxmlformats-officedocument", b"PK\x03\x04")
        try:
            rows = self.run_driver(listing=listing)
        finally:
            self.CONTENT[7598] = ("application/pdf", b"%PDF-1.4 body")
        self.assertEqual(self.deleted, [])
        self.assertEqual(rows[0]["action"], "skipped")
        self.assertIn("not a PDF", rows[0]["detail"])

    def test_content_is_backed_up_before_deletion(self):
        self.run_driver()
        saved = os.path.join(self.backups, "t722h9075_7598")
        self.assertTrue(os.path.exists(saved))
        with open(saved, "rb") as handle:
            self.assertEqual(handle.read(), b"%PDF-1.4 body")

    def test_generic_deletes_a_non_pdf_that_pdf_would_skip(self):
        listing = [{"id": 7598, "type": "generic", "label": "Notes.docx",
                    "treat_as_transcript": False}]
        self.CONTENT[7598] = ("application/vnd.openxmlformats-officedocument", b"PK\x03\x04")
        try:
            rows = self.run_driver(
                csv_text="file id,type\nt722h9075,generic\n", listing=listing
            )
        finally:
            self.CONTENT[7598] = ("application/pdf", b"%PDF-1.4 body")
        self.assertEqual(self.deleted, [("t722h9075", 7598)])
        self.assertEqual(rows[0]["action"], "deleted")

    def test_generic_still_backs_up_before_deleting(self):
        self.run_driver(csv_text="file id,type\nt722h9075,generic\n")
        self.assertTrue(os.path.exists(os.path.join(self.backups, "t722h9075_7598")))

    def test_audio_description_is_deleted(self):
        listing = [{"id": 900, "type": "audio_description", "label": "Described audio",
                    "treat_as_transcript": False}]
        self.CONTENT[900] = ("audio/mpeg", b"ID3\x03")
        rows = self.run_driver(
            csv_text="file id,type\nt722h9075,audio_description\n", listing=listing
        )
        self.assertEqual(self.deleted, [("t722h9075", 900)])
        self.assertEqual(rows[0]["action"], "deleted")

    def test_audio_description_is_not_content_checked(self):
        # no PDF verification should apply, whatever the bytes look like
        listing = [{"id": 900, "type": "audio_description", "label": "Described audio",
                    "treat_as_transcript": False}]
        self.CONTENT[900] = ("audio/mpeg", b"not a pdf at all")
        self.run_driver(
            csv_text="file id,type\nt722h9075,audio_description\n", listing=listing
        )
        self.assertEqual(self.deleted, [("t722h9075", 900)])

    def test_dry_run_deletes_nothing_and_writes_no_backups(self):
        rows = self.run_driver(dry_run=True)
        self.assertEqual(self.deleted, [])
        self.assertFalse(os.path.exists(self.backups))
        self.assertEqual([r["action"] for r in rows], ["would delete"])

    def test_skip_backup_still_deletes(self):
        self.run_driver(skip_backup=True)
        self.assertEqual(self.deleted, [("t722h9075", 7598)])
        self.assertFalse(os.path.exists(self.backups))

    def test_nothing_of_that_type_is_reported_not_errored(self):
        rows = self.run_driver(csv_text="file id,type\nt722h9075,captions\n")
        self.assertEqual(self.deleted, [])
        self.assertEqual(rows[0]["action"], "nothing to delete")

    def test_failed_backup_aborts_the_delete(self):
        from pyavalon.avalon import avalon as avalon_module
        path = write_csv("file id,type\nt722h9075,transcript\n")

        def boom(inner_self, supplemental_id, max_bytes=None):
            raise RuntimeError("network died")

        try:
            with patch.object(avalon_module.AvalonMasterFile, "get_supplemental_files",
                              lambda s: [dict(e) for e in LISTING]), \
                 patch.object(avalon_module.AvalonMasterFile, "fetch_supplemental_file", boom), \
                 patch.object(avalon_module.AvalonMasterFile, "delete_supplemental_file",
                              lambda s, i: self.deleted.append((s.identifier, i))), \
                 patch.object(avalon_module.AvalonMasterFile, "_AvalonBase__get_key",
                              staticmethod(lambda x: "k")):
                rows = avalon_module.delete_supplemental_files_from_csv(
                    path, prod_or_pre="pre", backup_directory=self.backups,
                    report_csv=self.report, verbose=False,
                )
        finally:
            os.unlink(path)
        self.assertEqual(self.deleted, [])
        self.assertEqual(rows[0]["action"], "error")
        self.assertIn("nothing deleted", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()
