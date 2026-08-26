"""
CSV-driven deletion of supplemental files from Avalon master files.

Avalon has no "pdf" supplemental type. A file's reported type comes from its
tags and is one of ``caption``, ``transcript``, ``audio_description`` or
``generic`` -- and ``generic`` is the catch-all for anything that is not one of
the other three, so a PDF, a Word document and a stray image all look
identical in the listing. Deleting every ``generic`` file to satisfy a request
for "pdf" would therefore destroy unrelated attachments, so PDFs are confirmed
by content type before anything is removed. See ``is_pdf``.

The reported type also collapses a distinction: ``caption`` wins over
``transcript``, so a file tagged both reports as ``caption`` with
``treat_as_transcript`` set. Matching is on the reported type exactly, which
keeps the behaviour predictable; ``describe_overlap`` flags the dual-tagged
files so an operator can see what a caption deletion is about to take with it.
"""

import csv
import re
from dataclasses import dataclass

PDF_MAGIC = b"%PDF"
PDF_CONTENT_TYPE = "application/pdf"

# What the operator may write in the "type" column -> canonical request type.
TYPE_ALIASES = {
    "caption": "caption",
    "captions": "caption",
    "transcript": "transcript",
    "transcripts": "transcript",
    "pdf": "pdf",
    "pdfs": "pdf",
}

# canonical request type -> the type Avalon reports in supplemental_files.json
AVALON_TYPE_FOR = {
    "caption": "caption",
    "transcript": "transcript",
    "pdf": "generic",
}

FILE_ID_LABELS = frozenset({"file id", "file", "id", "master file id", "master file"})
TYPE_LABELS = frozenset({"type", "file type", "supplemental type"})


class SupplementalCsvError(ValueError):
    """Raised for any input the operator needs to fix before a run."""


@dataclass
class SupplementalDeletion:
    file_id: str
    requested_type: str
    row_number: int

    @property
    def avalon_type(self):
        return AVALON_TYPE_FOR[self.requested_type]


def normalize(label):
    return re.sub(r"[\s_\-]+", " ", (label or "").strip().lower()).strip()


def read_deletion_csv(path):
    """Parse a deletion CSV into SupplementalDeletion rows.

    Wants a file id column and a type column. Unlike the metadata replacement
    CSV this one has no repeated headers, but it is parsed the same way so a
    duplicated column is caught rather than silently ignored.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise SupplementalCsvError("file is empty")

    file_id_index = type_index = None
    for index, raw in enumerate(rows[0]):
        label = normalize(raw)
        if label in FILE_ID_LABELS:
            if file_id_index is not None:
                raise SupplementalCsvError(
                    f"more than one file id column (positions {file_id_index + 1} and {index + 1})"
                )
            file_id_index = index
        elif label in TYPE_LABELS:
            if type_index is not None:
                raise SupplementalCsvError(
                    f"more than one type column (positions {type_index + 1} and {index + 1})"
                )
            type_index = index

    if file_id_index is None:
        raise SupplementalCsvError(
            "no file id column found; expected one of: " + ", ".join(sorted(FILE_ID_LABELS))
        )
    if type_index is None:
        raise SupplementalCsvError(
            "no type column found; expected one of: " + ", ".join(sorted(TYPE_LABELS))
        )

    deletions, seen = [], {}
    for offset, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        file_id = row[file_id_index].strip() if file_id_index < len(row) else ""
        raw_type = row[type_index].strip() if type_index < len(row) else ""
        if not file_id:
            raise SupplementalCsvError(f"row {offset} has no file id")
        if not raw_type:
            raise SupplementalCsvError(f"row {offset} ({file_id}) has no type")

        requested = TYPE_ALIASES.get(normalize(raw_type))
        if requested is None:
            raise SupplementalCsvError(
                f"row {offset} ({file_id}): {raw_type!r} is not a supported type; "
                f"use one of: transcript, captions, pdf"
            )

        key = (file_id, requested)
        if key in seen:
            raise SupplementalCsvError(
                f"row {offset} repeats {file_id!r}/{requested!r} from row {seen[key]}"
            )
        seen[key] = offset
        deletions.append(SupplementalDeletion(file_id, requested, offset))

    if not deletions:
        raise SupplementalCsvError("no data rows found")
    return deletions


def select_files(listing, requested_type):
    """Supplemental files matching a requested type, by reported type alone.

    For 'pdf' this returns every generic file; whether each is really a PDF is
    a separate question that needs the file's content type, which the listing
    does not carry. Callers must run those through is_pdf before deleting.
    """
    wanted = AVALON_TYPE_FOR[requested_type]
    return [entry for entry in listing if entry.get("type") == wanted]


def is_pdf(content_type, first_bytes=b""):
    """Whether a generic supplemental file is actually a PDF."""
    if content_type and content_type.split(";")[0].strip().lower() == PDF_CONTENT_TYPE:
        return True
    return bool(first_bytes) and first_bytes.startswith(PDF_MAGIC)


def describe_overlap(entries):
    """Labels of files tagged both caption and transcript.

    Avalon reports these as 'caption', so deleting captions removes them and
    deleting transcripts does not -- worth saying out loud before a run.
    """
    return [
        entry.get("label") or str(entry.get("id"))
        for entry in entries
        if entry.get("treat_as_transcript")
    ]
