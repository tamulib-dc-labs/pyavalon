"""
CSV-driven metadata replacement for Avalon media objects.

Avalon's spreadsheet convention repeats a column name once per value, so
``Contributor,Contributor,Contributor`` is one field with three values rather
than three fields. The replacement rules follow from that:

* a field is replaced only if its column appears in the header at all
* a column present with every cell blank clears the field
* a field whose column is absent is left alone
* replacing a value with itself is a no-op

The API docs give the request shape: ``{"fields": {...}}`` with ``fields``
REQUIRED and ``title`` REQUIRED inside it. Every value is a plain string or an
array of strings -- never a nested object -- and empty means ``[]`` for an
array field or ``null`` for a string one. The paired fields are parallel
arrays: ``note_type`` "must be present if values exist for note",
``other_identifier_type`` "must be present if other_identifier is used". The
docs' own example sends the entire fields hash back, including server-managed
keys like avalon_uploader, duration and record_identifier.

The rest was established by probing the pre instance, because the docs do not
cover it (and their GET example is misleading -- it shows date_issued as an
array; it is a string):

* ``PUT /media_objects/{id}.json`` takes ``{"fields": {...}}`` and MERGES:
  a field left out of the payload keeps its current value...
* ...except ``note``, ``other_identifier`` and ``related_item_url`` with their
  partner columns, which Avalon rebuilds from scratch on every update and
  therefore WIPES if they are not sent. This is why every update here is a
  read-modify-write: the work is fetched, the CSV changes are applied over the
  top, and the whole thing is sent back.
* ``date_issued`` is not badged REQUIRED in the docs, but the server rejects an
  empty one with "Date issued field is required.", so both it and ``title`` are
  treated as required and clearing either is refused before the request.
* ``subject`` and ``statement_of_responsibility`` are listed in the request body
  but accepted-and-ignored; see ACCEPTED_BUT_IGNORED.
* server-managed keys are safe to leave out -- they survive an update that
  omits them -- so SYSTEM_FIELDS are stripped rather than echoed.
* a key Avalon does not recognize returns a 500, which is why an unknown
  column aborts the run instead of being passed through.
* multi-valued fields clear with ``[]``, single-valued ones with ``""``.
"""

import csv
import re

from .avalon import AvalonMediaObject

# Server-derived. Confirmed safe to omit -- unlike the paired fields above,
# these survive an update that leaves them out.
SYSTEM_FIELDS = frozenset({
    "duration", "avalon_uploader", "avalon_publisher", "avalon_resource_type",
    "record_identifier", "identifier", "format", "resource_type",
})

# The docs badge only `title` REQUIRED on the update body, but the running API
# also rejects an empty date_issued with "Date issued field is required." Both
# are treated as required here because that is what the server enforces.
REQUIRED_FIELDS = ("title", "date_issued")

# In the docs' request body and accepted with a 200, but the server stores
# nothing -- verified against pre with valid values. They stay available as
# columns because the docs list them; the read-back after each write reports
# them as NOT APPLIED so a run never claims a change that did not happen.
# For subject, set Topical Subject instead: a GET returns the same values in
# both, and topical_subject is the half that actually stores.
ACCEPTED_BUT_IGNORED = ("subject", "statement_of_responsibility")

# The only two partner rules the docs state: note_type "must be present if
# values exist for note", other_identifier_type "must be present if
# other_identifier is used". related_item_url has no documented partner, so it
# is treated as a plain array field.
PAIRED_FIELDS = {
    "note": "note_type",
    "other_identifier": "other_identifier_type",
}

WORK_ID_LABELS = frozenset({"work id", "work", "id", "parent work", "media object id"})


def normalize(label):
    """Fold header spelling variants together: 'Date_Issued' -> 'date issued'."""
    return re.sub(r"[\s_-]+", " ", (label or "").strip().lower()).strip()


# Transcribed from the "Update existing media object" request body, in the order
# the docs list them, so the names here are the names a developer reads there:
# https://samvera.atlassian.net/wiki/spaces/AVALON/pages/1957954917/REST+API
# True = array<string>, False = string.
#
# Two cardinalities are taken from the live API instead, because the docs are
# wrong about them: physical_description is written "<string>" but comes back as
# an array, and format is listed "string" but comes back as an array too.
DOCUMENTED_FIELDS = {
    "title": False,
    "date_issued": False,
    "creator": True,
    "alternative_title": True,
    "translated_title": True,
    "uniform_title": True,
    "statement_of_responsibility": False,
    "date_created": False,
    "copyright_date": False,
    "abstract": False,
    "note": True,
    "note_type": True,
    "format": True,
    "resource_type": True,
    "contributor": True,
    "publisher": True,
    "genre": True,
    "subject": True,
    "related_item_url": True,
    "geographic_subject": True,
    "temporal_subject": True,
    "topical_subject": True,
    "bibliographic_id": False,
    "language": True,
    "terms_of_use": False,
    "table_of_contents": True,
    "physical_description": True,
    "other_identifier": True,
    "other_identifier_type": True,
    "comment": True,
}

# Documented in the request body but deliberately not offered as CSV columns.
# They describe the media files rather than the description, and Avalon derives
# them from the files themselves.
NOT_OFFERED = {
    "format": "describes the media files; Avalon derives it from them",
    "resource_type": "describes the media files; Avalon derives it from them",
}

# Column header -> (api field, is multi-valued). Keyed on the normalized API
# name, which means a header can be written either way: `date_issued` and
# `Date Issued` fold to the same key, so a spreadsheet exported from Avalon and
# one typed from the API docs both work.
FIELD_MAP = {
    normalize(name): (name, multi)
    for name, multi in DOCUMENTED_FIELDS.items()
    if name not in NOT_OFFERED
}

IS_MULTI = dict(DOCUMENTED_FIELDS)

REPORT_COLUMNS = ["work id", "field", "old value", "new value", "changed", "status"]


class MetadataCsvError(ValueError):
    """Raised for input the operator has to fix before anything is written."""


def _check_pairs(groups):
    """A paired field is invalid without its partner, so refuse the CSV rather
    than let Avalon reject the whole work with an unhelpful 422."""
    for primary, partner in PAIRED_FIELDS.items():
        has_primary, has_partner = primary in groups, partner in groups
        if has_primary != has_partner:
            present, missing = (primary, partner) if has_primary else (partner, primary)
            raise MetadataCsvError(
                f"{present!r} is present but {missing!r} is not; Avalon stores them as "
                f"parallel lists and requires both, so add the {missing!r} column"
            )
        if has_primary and len(groups[primary]) != len(groups[partner]):
            raise MetadataCsvError(
                f"{primary!r} has {len(groups[primary])} column(s) but {partner!r} has "
                f"{len(groups[partner])}; they are matched up position by position"
            )


def _resolve_header(header):
    """Map the header row to a work-id index and {api field: [column indices]}."""
    work_id_index = None
    groups = {}
    unknown = []
    seen_labels = {}

    for index, raw in enumerate(header):
        label = normalize(raw)
        if not label:
            continue
        if label in WORK_ID_LABELS:
            if work_id_index is not None:
                raise MetadataCsvError(
                    f"more than one work id column (columns {work_id_index + 1} and {index + 1})"
                )
            work_id_index = index
        elif label in FIELD_MAP:
            api_field, _ = FIELD_MAP[label]
            # 'Subject' and 'Topical Subject' are the same underlying field; if
            # both appear the intent is ambiguous, so refuse rather than guess.
            previous = seen_labels.get(api_field)
            if previous is not None and previous != label:
                raise MetadataCsvError(
                    f"{previous!r} and {label!r} both map to {api_field!r}; use only one"
                )
            seen_labels[api_field] = label
            groups.setdefault(api_field, []).append(index)
        else:
            unknown.append(f"{raw!r} (column {index + 1})")

    if unknown:
        raise MetadataCsvError(
            "unrecognized column(s): " + ", ".join(unknown) + ". Supported columns: "
            + ", ".join(sorted(FIELD_MAP))
        )
    if work_id_index is None:
        raise MetadataCsvError(
            "no work id column; expected one of: " + ", ".join(sorted(WORK_ID_LABELS))
        )
    _check_pairs(groups)
    return work_id_index, groups


def parse_csv(path):
    """
    Read the replacement CSV into [(row number, work id, {api field: [values]})].

    Uses csv.reader rather than DictReader on purpose: DictReader collapses
    duplicate headers and keeps only the last, which would silently reduce
    ``Contributor,Contributor,Contributor`` to a single value.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        raise MetadataCsvError(f"{path} is empty")

    work_id_index, groups = _resolve_header(rows[0])
    if not groups:
        raise MetadataCsvError("no metadata columns found; the CSV only has a work id column")

    parsed = []
    for offset, row in enumerate(rows[1:], start=2):
        work_id = row[work_id_index].strip() if work_id_index < len(row) else ""
        if not work_id:
            continue
        changes = {
            api_field: [row[i].strip() if i < len(row) else "" for i in indices]
            for api_field, indices in groups.items()
        }
        parsed.append((offset, work_id, changes))

    if not parsed:
        raise MetadataCsvError("no data rows with a work id")
    return parsed


def build_payload(existing, changes):
    """
    Merge the CSV changes over the work's current fields.

    Everything the work already has is carried through so the fields Avalon
    rebuilds on update are not wiped; every field named in the CSV is replaced
    outright, and an all-blank column clears it.

    A required field the CSV does not mention keeps its stored value, which
    falls out of starting from `existing`. A required field the CSV mentions
    but leaves blank is a mistake -- see `blank_required`.
    """
    payload = {k: v for k, v in existing.items() if k not in SYSTEM_FIELDS}
    for api_field, values in changes.items():
        kept = [value for value in values if value]
        payload[api_field] = kept if IS_MULTI.get(api_field) else (kept[0] if kept else "")
    return payload


def blank_required(changes):
    """
    Required fields the CSV names but leaves empty.

    Only title and date_issued are REQUIRED in the API docs. Clearing either
    is not something Avalon will do -- it rejects the whole work -- so this is
    reported as an error against the row rather than guessed at. Every other
    field blanks out normally: an empty column means wipe the field.
    """
    return [
        field for field in REQUIRED_FIELDS
        if field in changes and not any(value for value in changes[field])
    ]


def missing_required(payload):
    """Required fields that would go out empty. Never PUT one of these."""
    return [field for field in REQUIRED_FIELDS if not payload.get(field)]


def _display(value):
    if isinstance(value, list):
        return " | ".join(value)
    return "" if value is None else str(value)


def replace_metadata(
    csv_path,
    instance="pre",
    dry_run=False,
    report_path="metadata_replacement_report.csv",
    verbose=True,
):
    """
    Replace metadata on every work named in `csv_path`.

    Returns the report records, and writes them to `report_path`. With
    `dry_run` nothing is written to Avalon and the report shows what would
    have changed.
    """
    rows = parse_csv(csv_path)
    records = []

    # Checked before anything is read or written. Reads are public, so without
    # this a keyless run does the whole GET pass and then fails every write
    # with a bare 422 that looks like a validation error.
    if not dry_run and not AvalonMediaObject("", prod_or_pre=instance).key:
        variable = "AVALON_PROD" if instance == "prod" else "AVALON_PRE"
        raise MetadataCsvError(
            f"{variable} is not set, so every write would be rejected with a 422 that "
            f"says nothing useful. Set it and run again:\n"
            f'    PowerShell:  $env:{variable} = "your-api-key"\n'
            f'    bash:        export {variable}="your-api-key"'
        )

    if verbose:
        named = {field for _row, _work_id, changes in rows for field in changes}
        for field in ACCEPTED_BUT_IGNORED:
            if field in named:
                print(f"Warning: Avalon accepts {field!r} and stores nothing; it will be "
                      f"reported as NOT APPLIED"
                      + (". Use 'Topical Subject' instead" if field == "subject" else ""))

    for _row_number, work_id, changes in rows:
        work = AvalonMediaObject(work_id, prod_or_pre=instance)

        blank = blank_required(changes)
        if blank:
            records.append({
                "work id": work_id, "field": ", ".join(blank),
                "old value": "", "new value": "", "changed": "no",
                "status": f"error: {' and '.join(blank)} is required by Avalon and "
                          f"cannot be blank; fill it in or remove the column",
            })
            if verbose:
                print(f"{work_id}: {records[-1]['status']}")
            continue

        try:
            stored = work.get_object() or {}
        except Exception as error:
            records.append({
                "work id": work_id, "field": "", "old value": "", "new value": "",
                "changed": "no", "status": f"error reading: {error}",
            })
            continue

        # A refused or missing read comes back as {"errors": [...]} with a 200-
        # shaped body, so report that rather than letting it look like the work
        # merely has no collection or no fields.
        if "fields" not in stored:
            detail = stored.get("errors") or stored.get("error") or stored
            if isinstance(detail, list):
                detail = "; ".join(str(item) for item in detail)
            records.append({
                "work id": work_id, "field": "", "old value": "", "new value": "",
                "changed": "no", "status": f"error reading: {detail}",
            })
            if verbose:
                print(f"{work_id}: {records[-1]['status']}")
            continue

        existing = stored.get("fields") or {}
        # Sent when the work has one, since the docs' example includes it, but
        # it is not REQUIRED and an update without it still works.
        collection_id = stored.get("collection_id")

        payload = build_payload(existing, changes)

        # Only possible if the work itself is missing one, since build_payload
        # falls back to the stored value. Sending it would 422 the whole work.
        empty_required = missing_required(payload)
        if empty_required:
            records.append({
                "work id": work_id, "field": ", ".join(empty_required),
                "old value": "", "new value": "", "changed": "no",
                "status": f"skipped: {' and '.join(empty_required)} required by Avalon "
                          f"but empty on the work and in the CSV",
            })
            continue

        status = "dry run"

        if not dry_run:
            response = work.update_metadata(payload, collection_id=collection_id)
            if response.status_code >= 400:
                status = f"error writing: {response.status_code} {response.text[:200]}"
            else:
                # Avalon can accept a value and still not store it -- a
                # bibliographic_id, for instance, cannot be cleared once set --
                # so read back rather than trusting the 200.
                stored = work.get_object().get("fields") or {}
                missed = [
                    field for field in changes
                    if _display(stored.get(field)) != _display(payload.get(field))
                ]
                status = f"NOT APPLIED: {', '.join(missed)}" if missed else "ok"

        for api_field in changes:
            old, new = existing.get(api_field), payload.get(api_field)
            records.append({
                "work id": work_id,
                "field": api_field,
                "old value": _display(old),
                "new value": _display(new),
                "changed": "no" if _display(old) == _display(new) else "yes",
                "status": status,
            })

        if verbose:
            print(f"{work_id}: {status}")

    if report_path:
        with open(report_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(records)
        if verbose:
            print(f"Wrote report to {report_path}")

    return records
