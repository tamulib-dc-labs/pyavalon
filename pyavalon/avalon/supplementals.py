"""
CSV-driven deletion of supplemental files.

The inverse of ``upload_supplemental_files``: a CSV of ``work id`` and ``type``,
where every supplemental of that type on that work is deleted. Deletion is
irreversible -- Avalon returns no body and there is no undo -- so a run is
previewable with ``dry_run`` and always writes a report of what it did.

Supplementals hang off master files, not works, so each work is read first and
every master file it lists (``files[].id`` on the media object) is swept.

The types are Avalon's own, matched exactly as stored:

* ``caption``    -> type == "caption"
* ``transcript`` -> type == "transcript". A caption carrying
  ``treat_as_transcript`` stays a caption; the CSV did not ask for it.
* ``generic``    -> type == "generic", Avalon's catch-all, which is where a PDF
  uploaded through this tool ends up (add_pdf sends no type, so Avalon defaults
  it). ``pdf`` is deliberately not a type -- see PDF_GUIDANCE.
"""

import csv

from .avalon import AvalonMediaObject, AvalonSupplementalFile
from .metadata import normalize

WORK_ID_LABELS = frozenset({
    "work id", "work", "id", "media object id", "media object", "parent work",
})

TYPE_MATCHERS = {
    "caption": lambda item: item.get("type") == "caption",
    "transcript": lambda item: item.get("type") == "transcript",
    "generic": lambda item: item.get("type") == "generic",
}

# Plurals fold onto the same rule so a spreadsheet saying "Captions" works.
TYPE_ALIASES = {
    "captions": "caption",
    "transcripts": "transcript",
    "generics": "generic",
}

# Avalon has no pdf type. A PDF is stored as "generic", which is a catch-all
# that can equally hold a spreadsheet or an image, so deleting "pdf" would
# either miss files or destroy unrelated ones depending on how it guessed.
# Refuse the word outright and make the caller say what they mean.
PDF_GUIDANCE = (
    "'pdf' is not an Avalon supplemental type. PDFs are stored as 'generic', "
    "which also holds any other non-caption attachment, so use 'generic' if you "
    "really do want to delete all of them"
)

REPORT_COLUMNS = [
    "work id", "master file id", "type", "supplemental id", "label", "deleted", "status",
]


class SupplementalCsvError(ValueError):
    """Raised for input the operator has to fix before anything is deleted."""


def resolve_type(raw):
    """Fold a CSV type value onto a matcher key, or raise."""
    label = normalize(raw)
    label = TYPE_ALIASES.get(label, label)
    if label in {"pdf", "pdfs"}:
        raise SupplementalCsvError(PDF_GUIDANCE)
    if label not in TYPE_MATCHERS:
        raise SupplementalCsvError(
            f"unknown type {raw!r}; expected one of: " + ", ".join(sorted(TYPE_MATCHERS))
        )
    return label


def parse_csv(path):
    """
    Read the deletion CSV into [(row number, work id, type)].

    Unlike the metadata CSV this has no repeated columns, so a plain reader over
    two named columns is enough. Anything wrong with the file raises before a
    single delete is sent.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        raise SupplementalCsvError(f"{path} is empty")

    header = [normalize(column) for column in rows[0]]
    work_id_index = next((i for i, name in enumerate(header) if name in WORK_ID_LABELS), None)
    type_index = next((i for i, name in enumerate(header) if name == "type"), None)

    if work_id_index is None:
        raise SupplementalCsvError(
            "no work id column; expected one of: " + ", ".join(sorted(WORK_ID_LABELS))
        )
    if type_index is None:
        raise SupplementalCsvError("no 'type' column")

    parsed = []
    for offset, row in enumerate(rows[1:], start=2):
        work_id = row[work_id_index].strip() if work_id_index < len(row) else ""
        raw_type = row[type_index].strip() if type_index < len(row) else ""
        if not work_id and not raw_type:
            continue
        if not work_id:
            raise SupplementalCsvError(f"row {offset} has a type but no work id")
        if not raw_type:
            raise SupplementalCsvError(f"row {offset} ({work_id}) has no type")
        parsed.append((offset, work_id, resolve_type(raw_type)))

    if not parsed:
        raise SupplementalCsvError("no data rows")
    return parsed


def select(supplementals, file_type):
    """The supplementals a given CSV type should delete."""
    matcher = TYPE_MATCHERS[file_type]
    return [item for item in supplementals if matcher(item)]


def _error_detail(payload):
    detail = payload.get("errors") or payload.get("error") or payload
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    return str(detail)


def delete_supplemental_files(
    csv_path,
    instance="pre",
    dry_run=False,
    report_path="supplemental_deletion_report.csv",
    verbose=True,
):
    """
    Delete every supplemental of the named type from each work in `csv_path`.

    Returns the report records and writes them to `report_path`. With `dry_run`
    nothing is deleted and the report shows what would have gone.
    """
    rows = parse_csv(csv_path)
    records = []

    # Reading a work is public, so without this a keyless run would look fine
    # right up until every delete failed.
    if not dry_run:
        AvalonMediaObject("", prod_or_pre=instance).require_key()

    def record(work_id, file_type, status, master_file="", supplemental="", label="", deleted="no"):
        records.append({
            "work id": work_id, "master file id": master_file, "type": file_type,
            "supplemental id": supplemental, "label": label,
            "deleted": deleted, "status": status,
        })
        if verbose:
            where = f"{work_id}/{master_file}" if master_file else work_id
            # Name the matched type, not just the label. A generic file can be
            # labelled "Transcript in English", and printing the label alone
            # made a generic sweep read as though it had deleted transcripts.
            what = f" {file_type} #{supplemental} {label!r} --" if supplemental != "" else ""
            print(f"{where}:{what} {status}")

    for _row_number, work_id, file_type in rows:
        try:
            work = AvalonMediaObject(work_id, prod_or_pre=instance).get_object()
        except Exception as error:
            record(work_id, file_type, f"error reading work: {error}")
            continue

        if not isinstance(work, dict) or "files" not in work:
            record(work_id, file_type, f"error reading work: {_error_detail(work)}")
            continue

        master_files = [entry.get("id") for entry in (work.get("files") or []) if entry.get("id")]
        if not master_files:
            record(work_id, file_type, "no master files on this work")
            continue

        found = 0
        for master_file in master_files:
            supplemental = AvalonSupplementalFile(master_file, prod_or_pre=instance)
            try:
                listing = supplemental.get_files()
            except Exception as error:
                record(work_id, file_type, f"error listing: {error}", master_file=master_file)
                continue

            # A refused or missing read comes back as an object, not a list.
            if not isinstance(listing, list):
                record(work_id, file_type, f"error listing: {_error_detail(listing)}",
                       master_file=master_file)
                continue

            for item in select(listing, file_type):
                found += 1
                identifier = item.get("id")
                status, deleted = "dry run", "no"
                if not dry_run:
                    response = supplemental.delete_file(identifier)
                    if response.status_code >= 400:
                        status = f"error deleting: {response.status_code} {response.text[:150]}"
                    else:
                        status, deleted = "deleted", "yes"
                record(work_id, file_type, status, master_file=master_file,
                       supplemental=identifier, label=item.get("label", ""), deleted=deleted)

        if not found:
            # Recorded rather than skipped: a typo'd id would otherwise look
            # exactly like a work that had nothing to delete.
            record(work_id, file_type,
                   f"no {file_type} files found across {len(master_files)} master file(s)")

    if report_path:
        with open(report_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(records)
        if verbose:
            print(f"Wrote report to {report_path}")

    return records
