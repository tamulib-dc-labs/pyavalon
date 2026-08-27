import os
import tempfile
import unittest

from pyavalon.avalon.metadata import (
    MetadataCsvError,
    diff_fields,
    preserve_paired_fields,
    read_replacement_csv,
    write_repeated_column_csv,
)

FIXTURE = os.path.join("fixtures", "metadata-replacement.csv")


def write_csv(text):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    handle.write(text)
    handle.close()
    return handle.name


class TestTicketExample(unittest.TestCase):
    """The worked example from the ticket, row for row."""

    @classmethod
    def setUpClass(cls):
        cls.updates = {u.work_id: u for u in read_replacement_csv(FIXTURE)}

    def test_all_three_works_parsed(self):
        self.assertEqual(
            sorted(self.updates), ["4m90dv76w", "b2773w02m", "nk322d54j"]
        )

    def test_repeated_columns_collapse_into_one_list(self):
        # three Contributor columns are one multi-valued field, not three fields
        self.assertEqual(
            self.updates["nk322d54j"].fields["contributor"],
            [
                "Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017",
                "Cushing Memorial Library & Archives",
                "George Bass",
            ],
        )

    def test_absent_column_is_never_mentioned(self):
        # Genre is not in the sheet, so it must not appear in the payload at
        # all -- that is what leaves it untouched in Avalon
        for update in self.updates.values():
            self.assertNotIn("genre", update.fields)
            self.assertFalse(update.mentions("genre"))

    def test_blank_trailing_cell_is_dropped(self):
        # 4m90dv76w has three Contributor columns but only two values
        self.assertEqual(
            self.updates["4m90dv76w"].fields["contributor"],
            ["Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017", "Wade Birch"],
        )

    def test_all_blank_column_clears_the_field(self):
        # b2773w02m's contributors are replaced with nothing
        self.assertEqual(self.updates["b2773w02m"].fields["contributor"], [])
        self.assertTrue(self.updates["b2773w02m"].mentions("contributor"))

    def test_single_valued_field_is_a_scalar(self):
        self.assertEqual(self.updates["4m90dv76w"].fields["date_issued"], "2001-06-23")
        self.assertEqual(self.updates["nk322d54j"].fields["date_issued"], "2000-12-05")

    def test_replacing_a_value_with_itself_is_reported_as_unchanged(self):
        current = {"date_issued": "2000-12-05", "creator": ["Adair, Thomas W."]}
        report = diff_fields(current, self.updates["nk322d54j"].fields)
        self.assertFalse(report["date_issued"][2])
        self.assertTrue(report["creator"][2])


class TestUnquotedCommaDetection(unittest.TestCase):
    """A name whose comma was left unquoted is valid CSV saying the wrong
    thing, so it has to be refused rather than silently split."""

    def test_quoted_name_with_a_comma_stays_one_value(self):
        path = write_csv(
            'work id,Contributor,Contributor\n'
            'p2676v80j,"Lane, Daryl","Crews, David"\n'
        )
        try:
            fields = read_replacement_csv(path)[0].fields
        finally:
            os.unlink(path)
        self.assertEqual(fields["contributor"], ["Lane, Daryl", "Crews, David"])

    def test_unquoted_comma_that_keeps_row_width_is_refused(self):
        # 5 header cells, 5 data cells -- structurally fine, semantically wrong
        path = write_csv(
            "work id,Contributor,Contributor,Contributor,Contributor\n"
            "p2676v80j,Lane, Daryl,Crews, David\n"
        )
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        message = str(caught.exception)
        self.assertIn("Lane, Daryl", message)
        self.assertIn("begins with a space", message)

    def test_unquoted_comma_that_overflows_the_header_is_refused(self):
        path = write_csv(
            "work id,Contributor,Contributor\n"
            "p2676v80j,Lane, Daryl,Crews, David\n"
        )
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("cells but the header has", str(caught.exception))

    def test_trailing_empty_cells_are_not_an_overflow(self):
        path = write_csv("work id,Creator\nabc123,A,,\n")
        try:
            self.assertEqual(read_replacement_csv(path)[0].fields["creator"], ["A"])
        finally:
            os.unlink(path)

    def test_single_valued_field_is_not_comma_checked(self):
        # date_issued takes one value; a space there cannot mean a split name
        path = write_csv("work id,Abstract\nabc123, padded abstract\n")
        try:
            self.assertEqual(
                read_replacement_csv(path)[0].fields["abstract"], "padded abstract"
            )
        finally:
            os.unlink(path)

    def test_backup_output_round_trips_names_containing_commas(self):
        records = [("p2676v80j", {"contributor": ["Lane, Daryl", "Crews, David"]})]
        path = os.path.join(tempfile.mkdtemp(), "backup.csv")
        write_repeated_column_csv(path, records)
        self.assertEqual(
            read_replacement_csv(path)[0].fields["contributor"],
            ["Lane, Daryl", "Crews, David"],
        )


class TestPairedFieldPreservation(unittest.TestCase):
    """Avalon reassigns these three on every update, so a payload that stays
    silent about them deletes them."""

    def test_silent_payload_still_carries_existing_values(self):
        current = {
            "note": ["Interviewee: Thomas W. Adair III"],
            "note_type": ["general"],
            "other_identifier": ["02_00001"],
            "other_identifier_type": ["local"],
            "related_item_url": ["https://findingaids.library.tamu.edu/x"],
            "related_item_label": ["Oral History Project"],
        }
        payload = preserve_paired_fields({"creator": ["New Person"]}, current)
        for key, value in current.items():
            self.assertEqual(payload[key], value)
        self.assertEqual(payload["creator"], ["New Person"])

    def test_empty_current_values_become_empty_lists(self):
        payload = preserve_paired_fields({"creator": ["X"]}, {})
        for key in (
            "note", "note_type", "other_identifier",
            "other_identifier_type", "related_item_url", "related_item_label",
        ):
            self.assertEqual(payload[key], [])

    def test_incoming_values_win_over_current(self):
        current = {"note": ["old"], "note_type": ["general"]}
        payload = preserve_paired_fields(
            {"note": ["new"], "note_type": ["general"]}, current
        )
        self.assertEqual(payload["note"], ["new"])

    def test_does_not_mutate_its_arguments(self):
        new_fields = {"creator": ["X"]}
        preserve_paired_fields(new_fields, {"note": ["a"], "note_type": ["general"]})
        self.assertEqual(new_fields, {"creator": ["X"]})


class TestPairedColumnParsing(unittest.TestCase):
    def test_pairs_are_zipped_positionally_not_compacted(self):
        # the middle Note is blank; dropping blanks per-column would pair
        # 'second' with 'creation/production credits' and corrupt both
        path = write_csv(
            "work id,Note,Note,Note,Note Type,Note Type,Note Type\n"
            "abc123,first,,second,general,general,creation/production credits\n"
        )
        try:
            fields = read_replacement_csv(path)[0].fields
        finally:
            os.unlink(path)
        self.assertEqual(fields["note"], ["first", "second"])
        self.assertEqual(fields["note_type"], ["general", "creation/production credits"])

    def test_primary_without_partner_is_refused(self):
        path = write_csv("work id,Note\nabc123,orphan\n")
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("note_type", str(caught.exception))

    def test_mismatched_pair_column_counts_are_refused(self):
        path = write_csv("work id,Note,Note,Note Type\nabc123,a,b,general\n")
        try:
            with self.assertRaises(MetadataCsvError):
                read_replacement_csv(path)
        finally:
            os.unlink(path)


class TestHeaderValidation(unittest.TestCase):
    def test_unknown_header_is_refused(self):
        path = write_csv("work id,Creatorr\nabc123,X\n")
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("Creatorr", str(caught.exception))

    def test_system_field_is_refused(self):
        path = write_csv("work id,duration\nabc123,900\n")
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("system field", str(caught.exception))

    def test_subject_and_topical_subject_conflict_is_refused(self):
        # both map to topical_subject; honouring either one silently would
        # discard the other operator's column
        path = write_csv("work id,Subject,Topical Subject\nabc123,A,B\n")
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("topical_subject", str(caught.exception))

    def test_work_id_aliases_and_label_spellings(self):
        for header in ("work id", "Work ID", "work_id", "Parent Work", "id"):
            path = write_csv(f"{header},date_issued\nabc123,1999\n")
            try:
                updates = read_replacement_csv(path)
            finally:
                os.unlink(path)
            self.assertEqual(updates[0].work_id, "abc123", header)
            self.assertEqual(updates[0].fields["date_issued"], "1999", header)

    def test_missing_work_id_column_is_refused(self):
        path = write_csv("Creator\nX\n")
        try:
            with self.assertRaises(MetadataCsvError):
                read_replacement_csv(path)
        finally:
            os.unlink(path)

    def test_duplicate_work_id_is_refused(self):
        path = write_csv("work id,Creator\nabc123,A\nabc123,B\n")
        try:
            with self.assertRaises(MetadataCsvError) as caught:
                read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertIn("appears on rows", str(caught.exception))

    def test_blank_rows_are_skipped(self):
        path = write_csv("work id,Creator\nabc123,A\n\n\nxyz789,B\n")
        try:
            updates = read_replacement_csv(path)
        finally:
            os.unlink(path)
        self.assertEqual([u.work_id for u in updates], ["abc123", "xyz789"])

    def test_only_a_work_id_column_is_refused(self):
        path = write_csv("work id\nabc123\n")
        try:
            with self.assertRaises(MetadataCsvError):
                read_replacement_csv(path)
        finally:
            os.unlink(path)


class TestReplaceMetadataFromCsv(unittest.TestCase):
    """The driver, with the network mocked out."""

    EXISTING = {
        "creator": ["Adair, Thomas W."],
        "date_issued": "2000-12-05",
        "contributor": ["Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017"],
        "genre": ["Sound", "Interview", "Oral histories"],
        "note": ["Interviewee: Thomas W. Adair III", "Digitized 2019"],
        "note_type": ["creation/production credits", "general"],
        "other_identifier": ["02_00001"],
        "other_identifier_type": ["local"],
        "related_item_url": ["https://findingaids.library.tamu.edu/x"],
        "related_item_label": ["Oral History Project"],
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.report = os.path.join(self.tmp, "report.csv")
        self.backup = os.path.join(self.tmp, "backup.csv")
        self.sent = {}

    def run_driver(self, dry_run=False, applied=True):
        from unittest.mock import patch
        from pyavalon.avalon import avalon as avalon_module

        def fake_current(inner_self):
            merged = dict(self.EXISTING)
            if applied and inner_self.identifier in self.sent:
                merged.update(self.sent[inner_self.identifier])
            return merged

        def fake_replace(inner_self, fields):
            self.sent[inner_self.identifier] = fields
            return None

        with patch.object(avalon_module.AvalonMediaObject, "current_fields", fake_current), \
             patch.object(avalon_module.AvalonMediaObject, "replace_metadata", fake_replace), \
             patch.object(avalon_module.AvalonMediaObject, "_AvalonBase__get_key", staticmethod(lambda x: "k")):
            return avalon_module.replace_metadata_from_csv(
                FIXTURE, prod_or_pre="pre", dry_run=dry_run,
                report_csv=self.report, backup_csv=self.backup, verbose=False,
            )

    def test_payload_carries_paired_fields_through_untouched(self):
        self.run_driver()
        payload = self.sent["nk322d54j"]
        for key in (
            "note", "note_type", "other_identifier",
            "other_identifier_type", "related_item_url", "related_item_label",
        ):
            self.assertEqual(payload[key], self.EXISTING[key], key)

    def test_unmentioned_ordinary_field_is_absent_from_payload(self):
        self.run_driver()
        # Genre has no column, so it must never reach Avalon
        self.assertNotIn("genre", self.sent["nk322d54j"])

    def test_mentioned_fields_are_replaced(self):
        self.run_driver()
        self.assertEqual(self.sent["nk322d54j"]["creator"], ["Appelt, Leslie L."])
        self.assertEqual(self.sent["b2773w02m"]["contributor"], [])

    def test_dry_run_writes_no_changes(self):
        rows = self.run_driver(dry_run=True)
        self.assertEqual(self.sent, {})
        self.assertTrue(all(row["status"] == "dry run" for row in rows))

    def test_backup_round_trips_back_through_the_parser(self):
        self.run_driver()
        restored = {u.work_id: u for u in read_replacement_csv(self.backup)}
        self.assertEqual(restored["nk322d54j"].fields["creator"], ["Adair, Thomas W."])
        self.assertEqual(restored["nk322d54j"].fields["note"], self.EXISTING["note"])
        self.assertEqual(
            restored["nk322d54j"].fields["contributor"], self.EXISTING["contributor"]
        )

    def test_report_flags_identical_replacement_as_unchanged(self):
        rows = self.run_driver()
        dates = {
            r["work id"]: r["changed"] for r in rows if r["field"] == "date_issued"
        }
        self.assertEqual(dates["nk322d54j"], "no")   # replaced with itself
        self.assertEqual(dates["4m90dv76w"], "yes")  # 2000-06-23 -> 2001-06-23

    def test_write_that_does_not_stick_is_reported(self):
        # Avalon erases fields failing validation and still returns 200
        rows = self.run_driver(applied=False)
        statuses = {r["status"] for r in rows}
        self.assertTrue(
            any(s.startswith("NOT APPLIED") for s in statuses),
            f"expected a NOT APPLIED status, got {statuses}",
        )


if __name__ == "__main__":
    unittest.main()
