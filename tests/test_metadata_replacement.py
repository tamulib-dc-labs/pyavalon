import csv
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from pyavalon.avalon import AvalonMediaObject
from pyavalon.avalon.metadata import (
    DOCUMENTED_FIELDS,
    FIELD_MAP,
    NOT_OFFERED,
    MetadataCsvError,
    build_payload,
    normalize,
    parse_csv,
    replace_metadata,
)

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "metadata-replacement.csv")


def write_csv(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class TestParsing(unittest.TestCase):
    def test_repeated_columns_become_one_multivalued_field(self):
        """The whole point of the format: DictReader would keep only the last."""
        rows = parse_csv(FIXTURE)
        _row, work_id, changes = rows[0]
        self.assertEqual(work_id, "nk322d54j")
        self.assertEqual(
            changes["contributor"],
            [
                "Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017",
                "Cushing Memorial Library & Archives",
                "George Bass",
            ],
        )

    def test_quoted_comma_survives_as_one_value(self):
        rows = parse_csv(FIXTURE)
        _row, _work_id, changes = rows[0]
        self.assertEqual(changes["creator"], ["Appelt, Leslie L."])

    def test_absent_column_never_appears_in_changes(self):
        for _row, _work_id, changes in parse_csv(FIXTURE):
            self.assertNotIn("genre", changes)

    def test_blank_cells_are_kept_so_the_field_can_be_cleared(self):
        rows = parse_csv(FIXTURE)
        _row, work_id, changes = rows[2]
        self.assertEqual(work_id, "b2773w02m")
        self.assertEqual(changes["contributor"], ["", "", ""])

    def test_unknown_column_aborts(self):
        path = write_csv("work id,Creater\nabc123,Someone\n")
        with self.assertRaises(MetadataCsvError) as caught:
            parse_csv(path)
        self.assertIn("Creater", str(caught.exception))

    def test_missing_work_id_column_aborts(self):
        path = write_csv("Creator\nSomeone\n")
        with self.assertRaises(MetadataCsvError):
            parse_csv(path)

    def test_header_spelling_is_normalized(self):
        self.assertEqual(normalize("Date_Issued"), "date issued")
        self.assertEqual(normalize("  Other-Identifier  "), "other identifier")
        path = write_csv("Work ID,date_issued\nabc123,1999\n")
        _row, work_id, changes = parse_csv(path)[0]
        self.assertEqual(work_id, "abc123")
        self.assertEqual(changes["date_issued"], ["1999"])

    def test_paired_field_without_its_partner_is_refused(self):
        """Docs: note_type "must be present if values exist for note"."""
        path = write_csv("work id,Note\nabc123,a note\n")
        with self.assertRaises(MetadataCsvError) as caught:
            parse_csv(path)
        self.assertIn("note_type", str(caught.exception))

    def test_partner_without_its_primary_is_refused(self):
        path = write_csv("work id,Other Identifier Type\nabc123,local\n")
        with self.assertRaises(MetadataCsvError):
            parse_csv(path)

    def test_paired_columns_must_match_in_count(self):
        path = write_csv("work id,Note,Note,Note Type\nabc123,a,b,general\n")
        with self.assertRaises(MetadataCsvError) as caught:
            parse_csv(path)
        self.assertIn("position by position", str(caught.exception))

    def test_matched_pairs_are_accepted(self):
        path = write_csv("work id,Note,Note,Note Type,Note Type\nabc123,a,b,general,performers\n")
        _row, _work_id, changes = parse_csv(path)[0]
        self.assertEqual(changes["note"], ["a", "b"])
        self.assertEqual(changes["note_type"], ["general", "performers"])

    def test_subject_and_topical_subject_are_separate_documented_fields(self):
        path = write_csv("work id,Subject,Topical Subject\nabc123,Radio plays,Forestry\n")
        _row, _work_id, changes = parse_csv(path)[0]
        self.assertEqual(changes["subject"], ["Radio plays"])
        self.assertEqual(changes["topical_subject"], ["Forestry"])

    def test_only_documented_fields_are_accepted(self):
        """Series, Rights Statement and Related Item Label are not in the
        documented request body, so they are not columns."""
        for header in ("Series", "Rights Statement", "Related Item Label", "Summary"):
            path = write_csv(f"work id,{header}\nabc123,x\n")
            with self.assertRaises(MetadataCsvError, msg=header):
                parse_csv(path)

    def test_documented_fields_match_the_api_docs_exactly(self):
        """Locked in both directions: nothing offered that the docs do not
        list, and nothing in the docs silently dropped."""
        documented = {
            "title", "date_issued", "creator", "alternative_title", "translated_title",
            "uniform_title", "statement_of_responsibility", "date_created",
            "copyright_date", "abstract", "note", "note_type", "format", "resource_type",
            "contributor", "publisher", "genre", "subject", "related_item_url",
            "geographic_subject", "temporal_subject", "topical_subject",
            "bibliographic_id", "language", "terms_of_use", "table_of_contents",
            "physical_description", "other_identifier", "other_identifier_type", "comment",
        }
        self.assertEqual(set(DOCUMENTED_FIELDS), documented)
        offered = {api for api, _ in FIELD_MAP.values()}
        self.assertEqual(offered, documented - set(NOT_OFFERED))

    def test_columns_can_be_written_the_api_way_or_the_spreadsheet_way(self):
        """`date_issued` and `Date Issued` are the same column, so a sheet
        exported from Avalon and one typed from the docs both work."""
        for header in ("date_issued", "Date Issued", "DATE-ISSUED"):
            path = write_csv(f"work id,{header}\nabc123,1999\n")
            _row, _work_id, changes = parse_csv(path)[0]
            self.assertEqual(changes["date_issued"], ["1999"], header)

    def test_fields_not_offered_are_rejected_as_columns(self):
        """format and resource_type are documented but describe the files."""
        for header in NOT_OFFERED:
            path = write_csv(f"work id,{header}\nabc123,x\n")
            with self.assertRaises(MetadataCsvError, msg=header):
                parse_csv(path)

    def test_sample_csv_parses(self):
        """fixtures/metadata-replacement-sample.csv is generated from live works
        and is meant to run against pre without error."""
        sample = os.path.join(os.path.dirname(FIXTURE), "metadata-replacement-sample.csv")
        rows = parse_csv(sample)
        self.assertEqual([work_id for _row, work_id, _changes in rows],
                         ["pk02c9724", "d791sg16q"])
        _row, _work_id, changes = rows[1]
        self.assertEqual(len(changes["genre"]), 6)
        self.assertIn("Elliott, Jelly", changes["creator"])

    def test_rows_without_a_work_id_are_skipped(self):
        path = write_csv("work id,Creator\nabc123,Someone\n,Orphan\n")
        self.assertEqual(len(parse_csv(path)), 1)


class TestBuildPayload(unittest.TestCase):
    def setUp(self):
        self.existing = {
            "title": "A Work",
            "date_issued": "2000-12-05",
            "creator": ["Adair, Thomas W."],
            "contributor": ["Monroe, Haskell M.", "Cushing Memorial Library & Archives"],
            "genre": ["Interview", "Oral histories"],
            "abstract": "An abstract",
            "duration": "570044",
            "avalon_uploader": "someone@tamu.edu",
        }

    def test_named_field_is_replaced_outright(self):
        payload = build_payload(self.existing, {"contributor": ["Wade Birch"]})
        self.assertEqual(payload["contributor"], ["Wade Birch"])

    def test_absent_field_is_carried_through_untouched(self):
        """Avalon wipes note/other_identifier/related_item_url unless they are resent."""
        payload = build_payload(self.existing, {"creator": ["Appelt, Leslie L."]})
        self.assertEqual(payload["genre"], ["Interview", "Oral histories"])
        self.assertEqual(payload["abstract"], "An abstract")

    def test_all_blank_column_clears_a_multivalued_field(self):
        payload = build_payload(self.existing, {"contributor": ["", "", ""]})
        self.assertEqual(payload["contributor"], [])

    def test_all_blank_column_clears_a_single_valued_field(self):
        payload = build_payload(self.existing, {"abstract": [""]})
        self.assertEqual(payload["abstract"], "")

    def test_blanks_are_dropped_from_a_partly_filled_field(self):
        payload = build_payload(self.existing, {"contributor": ["Monroe, Haskell M.", "Wade Birch", ""]})
        self.assertEqual(payload["contributor"], ["Monroe, Haskell M.", "Wade Birch"])

    def test_single_valued_field_takes_the_first_value(self):
        payload = build_payload(self.existing, {"date_issued": ["2001-06-23"]})
        self.assertEqual(payload["date_issued"], "2001-06-23")

    def test_system_fields_are_stripped(self):
        payload = build_payload(self.existing, {"creator": ["Someone"]})
        self.assertNotIn("duration", payload)
        self.assertNotIn("avalon_uploader", payload)

    def test_payload_values_are_plain_strings_and_arrays(self):
        """The documented shape: every value under fields is a string or a
        list of strings -- never a nested object."""
        payload = build_payload(self.existing, {"contributor": ["A", "B"], "abstract": ["x"]})
        for key, value in payload.items():
            if isinstance(value, list):
                self.assertTrue(all(isinstance(v, str) for v in value), key)
            else:
                self.assertIsInstance(value, (str, type(None)), key)

    def test_replacing_a_value_with_itself_is_a_noop(self):
        payload = build_payload(self.existing, {"date_issued": ["2000-12-05"]})
        self.assertEqual(payload["date_issued"], self.existing["date_issued"])


class TestEnvFileLoading(unittest.TestCase):
    """A .env.local in the project looks like configuration, so it has to be
    read -- otherwise a shell that never exported the variable sails through
    every read and fails on the first write."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        import pyavalon.avalon.avalon as module
        self.module = module
        module._ENV_FILES_LOADED = False
        self.addCleanup(setattr, module, "_ENV_FILES_LOADED", False)

    def write_env(self, name, text):
        with open(os.path.join(self.directory, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_reads_keys_from_env_local(self):
        self.write_env(".env.local", 'AVALON_PRE="from-file"\n# a comment\n\n')
        with patch.dict(os.environ, {}, clear=True):
            self.module.load_env_file(self.directory)
            self.assertEqual(os.environ["AVALON_PRE"], "from-file")

    def test_the_shell_wins_over_the_file(self):
        self.write_env(".env.local", "AVALON_PRE=from-file\n")
        with patch.dict(os.environ, {"AVALON_PRE": "from-shell"}, clear=True):
            self.module.load_env_file(self.directory)
            self.assertEqual(os.environ["AVALON_PRE"], "from-shell")

    def test_falls_back_to_plain_env(self):
        self.write_env(".env", "AVALON_PROD='quoted-value'\n")
        with patch.dict(os.environ, {}, clear=True):
            self.module.load_env_file(self.directory)
            self.assertEqual(os.environ["AVALON_PROD"], "quoted-value")

    def test_no_file_is_not_an_error(self):
        with patch.dict(os.environ, {}, clear=True):
            self.module.load_env_file(self.directory)
            self.assertNotIn("AVALON_PRE", os.environ)

    def test_env_file_is_not_opened_when_the_key_is_in_the_environment(self):
        """People who export the key in their terminal should never have a
        stray .env.local read at all."""
        opened = []
        real_isfile = os.path.isfile

        def spy(path):
            if str(path).endswith((".env.local", ".env")):
                opened.append(path)
            return real_isfile(path)

        with patch.dict(os.environ, {"AVALON_PRE": "from-shell"}, clear=True):
            with patch("os.path.isfile", spy):
                client = AvalonMediaObject("abc123", prod_or_pre="pre")
        self.assertEqual(client.key, "from-shell")
        self.assertEqual(opened, [], "no .env file should have been looked at")

    def test_env_file_is_read_when_the_key_is_absent(self):
        self.write_env(".env.local", "AVALON_PRE=from-file\n")
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.getcwd", lambda: self.directory):
                client = AvalonMediaObject("abc123", prod_or_pre="pre")
        self.assertEqual(client.key, "from-file")


class TestApiKeyGuard(unittest.TestCase):
    """Reads are public, so a missing key only surfaces on a write -- as a bare
    422 that names no field. Both layers refuse before sending one."""

    def test_update_metadata_refuses_without_a_key(self):
        with patch.dict(os.environ, {"AVALON_PRE": ""}, clear=False):
            work = AvalonMediaObject("abc123", prod_or_pre="pre")
            with self.assertRaises(ValueError) as caught:
                work.update_metadata({"title": "x"}, "some-collection")
        self.assertIn("AVALON_PRE", str(caught.exception))

    def test_replace_metadata_names_the_variable_for_the_instance(self):
        for instance, variable in (("pre", "AVALON_PRE"), ("prod", "AVALON_PROD")):
            with patch.dict(os.environ, {variable: ""}, clear=False):
                with self.assertRaises(MetadataCsvError) as caught:
                    replace_metadata(FIXTURE, instance=instance,
                                     report_path=None, verbose=False)
            self.assertIn(variable, str(caught.exception))

    def test_dry_run_needs_no_key(self):
        """Nothing is written, so a preview should still work."""
        with patch.dict(os.environ, {"AVALON_PRE": ""}, clear=False):
            with patch.object(AvalonMediaObject, "get_object",
                              lambda s, type="media_object": {
                                  "fields": {"title": "T", "date_issued": "2000"},
                                  "collection_id": "c1"}):
                records = replace_metadata(FIXTURE, instance="pre", dry_run=True,
                                           report_path=None, verbose=False)
        self.assertTrue(all(r["status"] == "dry run" for r in records))


class TestReplaceMetadata(unittest.TestCase):
    """The task's worked example, driven end to end against a mocked Avalon."""

    def setUp(self):
        # replace_metadata refuses to start without a key, so the mocked run
        # needs one even though no request leaves the process.
        key = patch.dict(os.environ, {"AVALON_PRE": "test-key"}, clear=False)
        key.start()
        self.addCleanup(key.stop)

        self.report = os.path.join(tempfile.mkdtemp(), "report.csv")
        self.stored = {
            "nk322d54j": {
                "title": "Adair Interview", "date_issued": "2000-12-05",
                "creator": ["Adair, Thomas W."],
                "contributor": ["Monroe, Haskell M.", "Cushing Memorial Library & Archives"],
                "genre": ["Interview", "Oral histories"],
            },
            "4m90dv76w": {
                "title": "Adkisson Interview", "date_issued": "2000-06-23",
                "creator": ["Adkisson, Perry L."],
                "contributor": ["Monroe, Haskell M.", "Cushing Memorial Library & Archives"],
                "genre": ["Interview", "Oral histories"],
            },
            "b2773w02m": {
                "title": "Albritton Interview", "date_issued": "1998-02-27",
                "creator": ["Albritton, Ford"],
                "contributor": ["Monroe, Haskell M.", "Cushing Memorial Library & Archives"],
                "genre": ["Interview", "Oral histories"],
            },
        }
        self.sent = {}

        self.sent_collection = {}

        def fake_get(inner_self, type="media_object"):
            return {
                "fields": dict(self.stored[inner_self.identifier]),
                "collection_id": "jh343s37c",
            }

        def fake_put(inner_self, fields, collection_id=None):
            self.sent[inner_self.identifier] = fields
            self.sent_collection[inner_self.identifier] = collection_id
            self.stored[inner_self.identifier] = dict(fields)
            return Mock(status_code=200, text="{}")

        self.get_patch = patch.object(AvalonMediaObject, "get_object", fake_get)
        self.put_patch = patch.object(AvalonMediaObject, "update_metadata", fake_put)
        self.get_patch.start()
        self.put_patch.start()
        self.addCleanup(self.get_patch.stop)
        self.addCleanup(self.put_patch.stop)

    def run_fixture(self, dry_run=False):
        return replace_metadata(FIXTURE, instance="pre", dry_run=dry_run,
                                report_path=self.report, verbose=False)

    def test_creator_replaced_and_contributor_gains_a_value(self):
        self.run_fixture()
        self.assertEqual(self.sent["nk322d54j"]["creator"], ["Appelt, Leslie L."])
        self.assertEqual(
            self.sent["nk322d54j"]["contributor"],
            ["Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017",
             "Cushing Memorial Library & Archives", "George Bass"],
        )

    def test_genre_is_untouched_because_it_has_no_column(self):
        self.run_fixture()
        for work_id in self.stored:
            self.assertEqual(self.sent[work_id]["genre"], ["Interview", "Oral histories"])

    def test_contributor_is_replaced_not_merged(self):
        """4m90dv76w loses Cushing because the CSV replaces the whole field."""
        self.run_fixture()
        self.assertEqual(
            self.sent["4m90dv76w"]["contributor"],
            ["Monroe, Haskell M., Jr. (Haskell Moorman), 1931-2017", "Wade Birch"],
        )

    def test_blank_contributor_columns_clear_the_field(self):
        self.run_fixture()
        self.assertEqual(self.sent["b2773w02m"]["contributor"], [])

    def test_report_marks_identical_values_unchanged(self):
        records = self.run_fixture()
        by_key = {(r["work id"], r["field"]): r for r in records}
        self.assertEqual(by_key[("b2773w02m", "creator")]["changed"], "no")
        self.assertEqual(by_key[("4m90dv76w", "date_issued")]["changed"], "yes")
        self.assertEqual(by_key[("nk322d54j", "creator")]["changed"], "yes")

    def test_report_is_written_with_old_and_new_values(self):
        self.run_fixture()
        with open(self.report, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        row = next(r for r in rows if r["work id"] == "nk322d54j" and r["field"] == "creator")
        self.assertEqual(row["old value"], "Adair, Thomas W.")
        self.assertEqual(row["new value"], "Appelt, Leslie L.")
        self.assertEqual(row["status"], "ok")

    def test_collection_id_is_sent_with_every_update(self):
        """The documented body is {"collection_id": ..., "fields": {...}}."""
        self.run_fixture()
        self.assertEqual(
            set(self.sent_collection.values()), {"jh343s37c"},
            "every update must carry the work's collection_id",
        )

    def test_a_refused_read_reports_the_real_reason(self):
        """A bad key makes the GET return {"errors": [...]}; that must not be
        reported as a missing collection_id."""
        def refused(inner_self, type="media_object"):
            return {"errors": ["Permission denied."]}

        with patch.object(AvalonMediaObject, "get_object", refused):
            records = replace_metadata(FIXTURE, instance="pre",
                                       report_path=self.report, verbose=False)
        self.assertEqual(self.sent, {})
        self.assertTrue(all("Permission denied." in r["status"] for r in records))

    def test_a_work_with_no_collection_id_still_updates(self):
        """collection_id is not REQUIRED in the docs; omit it and carry on."""
        def no_collection(inner_self, type="media_object"):
            return {"fields": dict(self.stored[inner_self.identifier])}

        with patch.object(AvalonMediaObject, "get_object", no_collection):
            replace_metadata(FIXTURE, instance="pre",
                             report_path=self.report, verbose=False)
        self.assertEqual(self.sent["nk322d54j"]["creator"], ["Appelt, Leslie L."])
        self.assertIsNone(self.sent_collection["nk322d54j"])

    def test_missing_api_key_aborts_before_any_write(self):
        """Reads are public, so a keyless run otherwise 422s on every write
        with a body that names no field."""
        with patch.dict(os.environ, {"AVALON_PRE": ""}, clear=False):
            with self.assertRaises(MetadataCsvError) as caught:
                replace_metadata(FIXTURE, instance="pre",
                                 report_path=self.report, verbose=False)
        self.assertIn("AVALON_PRE", str(caught.exception))
        self.assertEqual(self.sent, {})

    def test_dry_run_writes_nothing(self):
        records = self.run_fixture(dry_run=True)
        self.assertEqual(self.sent, {})
        self.assertTrue(all(r["status"] == "dry run" for r in records))

    def test_blank_required_field_is_an_error_and_nothing_is_sent(self):
        """Only title and date_issued are REQUIRED in the API docs."""
        path = write_csv("work id,Title\nnk322d54j,\n")
        records = replace_metadata(path, instance="pre", report_path=self.report, verbose=False)
        self.assertEqual(self.sent, {})
        self.assertIn("required", records[0]["status"])
        self.assertIn("title", records[0]["field"])

    def test_blank_date_issued_is_also_an_error(self):
        path = write_csv("work id,Date Issued\nnk322d54j,\n")
        records = replace_metadata(path, instance="pre", report_path=self.report, verbose=False)
        self.assertEqual(self.sent, {})
        self.assertIn("date_issued", records[0]["field"])

    def test_a_required_field_not_in_the_csv_keeps_its_stored_value(self):
        """No Title column at all is fine -- the stored title is carried through."""
        self.run_fixture()
        self.assertEqual(self.sent["nk322d54j"]["title"], "Adair Interview")
        self.assertEqual(self.sent["nk322d54j"]["date_issued"], "2000-12-05")

    def test_blank_non_required_field_still_wipes(self):
        """Everything that is not title/date_issued clears on an empty column."""
        path = write_csv("work id,Genre,Genre\nnk322d54j,,\n")
        replace_metadata(path, instance="pre", report_path=self.report, verbose=False)
        self.assertEqual(self.sent["nk322d54j"]["genre"], [])

    def test_write_failure_is_reported_and_the_run_continues(self):
        def failing_put(inner_self, fields, collection_id=None):
            if inner_self.identifier == "nk322d54j":
                return Mock(status_code=422, text='{"errors":["Title field is required."]}')
            self.sent[inner_self.identifier] = fields
            self.stored[inner_self.identifier] = dict(fields)
            return Mock(status_code=200, text="{}")

        with patch.object(AvalonMediaObject, "update_metadata", failing_put):
            records = replace_metadata(FIXTURE, instance="pre", report_path=self.report, verbose=False)

        statuses = {r["work id"]: r["status"] for r in records}
        self.assertIn("422", statuses["nk322d54j"])
        self.assertEqual(statuses["4m90dv76w"], "ok")
        self.assertIn("4m90dv76w", self.sent)

    def test_a_value_that_does_not_stick_is_reported_not_applied(self):
        """Avalon can return 200 and still not store a value."""
        def lying_put(inner_self, fields, collection_id=None):
            kept = dict(fields)
            kept["creator"] = ["Something Else"]
            self.stored[inner_self.identifier] = kept
            return Mock(status_code=200, text="{}")

        with patch.object(AvalonMediaObject, "update_metadata", lying_put):
            records = replace_metadata(FIXTURE, instance="pre", report_path=self.report, verbose=False)

        self.assertTrue(any("NOT APPLIED" in r["status"] for r in records))


if __name__ == "__main__":
    unittest.main()
