"""
CSV-driven metadata replacement for Avalon media objects.

Avalon's spreadsheet convention repeats a column name once per value, so
``Contributor,Contributor,Contributor`` is one multi-valued field rather than
three fields. ``csv.DictReader`` collapses duplicate headers and silently keeps
only the last, so everything here works off ``csv.reader`` and column indices.

Replacement semantics, matching what Avalon's API actually does:

* a field is replaced only if its column appears in the header at all
* a column that appears with every cell blank clears the field
* a field whose column is absent is left alone -- with three exceptions, see
  ``PAIRED_FIELDS`` below
"""

import csv
import re
from dataclasses import dataclass, field as dataclass_field

# Avalon rebuilds these three from primary.zip(partner) on *every* update,
# whether or not they were sent. Omitting them sets both halves to [] and the
# setter's delete_all_values() wipes them -- while still returning HTTP 200.
# Any payload we PUT therefore has to carry them, even when nobody asked to
# change them. See preserve_paired_fields().
PAIRED_FIELDS = {
    "note": "note_type",
    "other_identifier": "other_identifier_type",
    "related_item_url": "related_item_label",
}

# Set by Avalon itself; accepting them as input could only ever corrupt data.
SYSTEM_FIELDS = frozenset({
    "duration", "avalon_uploader", "avalon_publisher", "avalon_resource_type",
    "record_identifier", "identifier", "format", "resource_type",
})

WORK_ID_LABELS = frozenset({"work id", "work", "id", "parent work", "media object id"})

# label -> (api field, multi-valued). Cardinality confirmed against a live
# media_objects/{id}.json response and Avalon's MediaObjectMods accessors.
FIELD_MAP = {
    "title": ("title", False),
    "alternative title": ("alternative_title", True),
    "translated title": ("translated_title", True),
    "uniform title": ("uniform_title", True),
    "statement of responsibility": ("statement_of_responsibility", False),
    "creator": ("creator", True),
    "date created": ("date_created", False),
    "date issued": ("date_issued", False),
    "copyright date": ("copyright_date", False),
    "abstract": ("abstract", False),
    "summary": ("abstract", False),
    "contributor": ("contributor", True),
    "publisher": ("publisher", True),
    "genre": ("genre", True),
    "subject": ("topical_subject", True),
    "topical subject": ("topical_subject", True),
    "geographic subject": ("geographic_subject", True),
    "temporal subject": ("temporal_subject", True),
    "language": ("language", True),
    "terms of use": ("terms_of_use", False),
    "table of contents": ("table_of_contents", True),
    "physical description": ("physical_description", True),
    "series": ("series", True),
    "comment": ("comment", True),
    "rights statement": ("rights_statement", False),
    "bibliographic id": ("bibliographic_id", False),
    "note": ("note", True),
    "note type": ("note_type", True),
    "other identifier": ("other_identifier", True),
    "other identifier type": ("other_identifier_type", True),
    "related item url": ("related_item_url", True),
    "related item label": ("related_item_label", True),
}

# api field -> multi-valued, derived once so lookups do not rescan FIELD_MAP.
FIELD_CARDINALITY = {api: multi for api, multi in FIELD_MAP.values()}


class MetadataCsvError(ValueError):
    """Raised for any input the operator needs to fix before a run."""


@dataclass
class WorkUpdate:
    work_id: str
    row_number: int
    fields: dict = dataclass_field(default_factory=dict)

    def mentions(self, api_field):
        return api_field in self.fields


def normalize(label):
    """Fold header spelling variants together: 'Date_Issued' -> 'date issued'."""
    return re.sub(r"[\s_\-]+", " ", (label or "").strip().lower()).strip()


def _resolve_headers(header_row):
    """Map the header row to a work-id index and {api_field: [indices]}."""
    work_id_index = None
    groups = {}
    seen_labels = {}
    unknown = []

    for index, raw in enumerate(header_row):
        label = normalize(raw)
        if not label:
            continue
        if label in WORK_ID_LABELS:
            if work_id_index is not None:
                raise MetadataCsvError(
                    f"more than one work id column (positions {work_id_index + 1} and {index + 1})"
                )
            work_id_index = index
            continue
        if label.replace(" ", "_") in SYSTEM_FIELDS:
            raise MetadataCsvError(
                f"column {index + 1} ({raw!r}) is a system field Avalon manages itself; remove it"
            )
        if label not in FIELD_MAP:
            unknown.append(f"{raw!r} (column {index + 1})")
            continue
        api_field, _multi = FIELD_MAP[label]
        # 'Subject' and 'Topical Subject' are the same underlying field; if both
        # appear the operator's intent is ambiguous, so refuse rather than guess.
        previous = seen_labels.get(api_field)
        if previous is not None and previous != label:
            raise MetadataCsvError(
                f"{previous!r} and {label!r} both map to {api_field!r}; use only one"
            )
        seen_labels[api_field] = label
        groups.setdefault(api_field, []).append(index)

    if unknown:
        raise MetadataCsvError(
            "unrecognized column(s): " + ", ".join(unknown)
            + ". Supported: " + ", ".join(sorted(FIELD_MAP))
        )
    if work_id_index is None:
        raise MetadataCsvError(
            "no work id column found; expected one of: " + ", ".join(sorted(WORK_ID_LABELS))
        )
    return work_id_index, groups


def _check_pairs(groups):
    """A paired field is meaningless without its partner -- Avalon discards any
    entry missing either half, so a lone column would silently delete data."""
    for primary, partner in PAIRED_FIELDS.items():
        has_primary, has_partner = primary in groups, partner in groups
        if has_primary != has_partner:
            present, missing = (primary, partner) if has_primary else (partner, primary)
            raise MetadataCsvError(
                f"{present!r} is present but {missing!r} is not; Avalon stores them as pairs "
                f"and discards any value missing its partner, so both columns are required"
            )
        if has_primary and len(groups[primary]) != len(groups[partner]):
            raise MetadataCsvError(
                f"{primary!r} has {len(groups[primary])} column(s) but {partner!r} has "
                f"{len(groups[partner])}; they are matched up position by position"
            )


def _cell(row, index):
    return row[index].strip() if index < len(row) else ""


def _check_row_shape(row, header_width, groups, offset):
    """Catch a name whose comma was left unquoted.

    "Lane, Daryl" written without quotes is two cells as far as CSV is
    concerned, and there is no way to recover the intent afterwards -- so the
    only safe thing is to refuse the file. Two signals give it away.

    The first is a row wider than its header: the split pushed cells off the
    end, and they would otherwise be read past every column group and silently
    dropped.

    The second is a value with leading whitespace. A quoted "Lane, Daryl"
    arrives intact, but an unquoted one splits at ", " and leaves the second
    half beginning with a space. Properly written files do not have that --
    spreadsheet exports quote instead of padding.
    """
    overflow = [value for value in row[header_width:] if value.strip()]
    if overflow:
        raise MetadataCsvError(
            f"row {offset} has {len(row)} cells but the header has {header_width}; "
            f"stray value(s) {', '.join(repr(v) for v in overflow[:3])}. A name containing "
            f"a comma must be quoted, e.g. \"Lane, Daryl\""
        )

    for api_field, indices in groups.items():
        if not FIELD_CARDINALITY.get(api_field):
            continue
        for position, index in enumerate(indices):
            if index >= len(row) or position == 0:
                continue
            raw = row[index]
            if not (raw and raw[:1].isspace() and raw.strip()):
                continue
            previous = row[indices[position - 1]].strip()
            # Only an inverted personal name looks like this. Real values that
            # merely carry padding -- " U.S. Advertising Council", " Country
            # music" -- are common in Avalon and must not be refused, or the
            # backup file this tool writes would stop round-tripping. A split
            # "Lane, Daryl" leaves a bare single token on both sides; a padded
            # multi-word value does not.
            if not previous or " " in previous or " " in raw.strip():
                continue
            joined = f"{previous},{raw}"
            raise MetadataCsvError(
                    f"row {offset}, {CANONICAL_LABELS.get(api_field, api_field)} column "
                    f"{index + 1}: {raw!r} begins with a space, which usually means a name "
                    f"containing a comma was left unquoted (reading {joined.strip()!r} as two "
                    f"values). Quote it as \"{joined.strip()}\", or remove the padding if the "
                    f"split is intended"
                )


def read_replacement_csv(path):
    """Parse a replacement CSV into a list of WorkUpdate rows.

    Raises MetadataCsvError on anything the operator should fix first -- a
    typo'd header would otherwise silently leave a field unchanged while the
    run report claimed it had been replaced.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise MetadataCsvError("file is empty")

    work_id_index, groups = _resolve_headers(rows[0])
    _check_pairs(groups)
    if not groups:
        raise MetadataCsvError("no metadata columns found; only a work id column was present")

    paired_names = set(PAIRED_FIELDS) | set(PAIRED_FIELDS.values())
    updates, seen = [], {}

    for offset, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        work_id = _cell(row, work_id_index)
        if not work_id:
            raise MetadataCsvError(f"row {offset} has no work id")
        if work_id in seen:
            raise MetadataCsvError(
                f"work id {work_id!r} appears on rows {seen[work_id]} and {offset}; each work "
                f"must appear once so the replacement is unambiguous"
            )
        seen[work_id] = offset
        _check_row_shape(row, len(rows[0]), groups, offset)

        fields = {}
        for api_field, indices in groups.items():
            if api_field in paired_names:
                continue  # handled below, positionally
            values = [v for v in (_cell(row, i) for i in indices) if v]
            if FIELD_CARDINALITY[api_field]:
                fields[api_field] = values
            else:
                fields[api_field] = values[0] if values else ""

        # Paired fields zip by column position, so blanks must be dropped
        # pairwise -- filtering each side independently would misalign them.
        for primary, partner in PAIRED_FIELDS.items():
            if primary not in groups:
                continue
            kept = [
                (first, second)
                for first, second in (
                    (_cell(row, i), _cell(row, j))
                    for i, j in zip(groups[primary], groups[partner])
                )
                if first and second
            ]
            fields[primary] = [first for first, _ in kept]
            fields[partner] = [second for _, second in kept]

        updates.append(WorkUpdate(work_id=work_id, row_number=offset, fields=fields))

    if not updates:
        raise MetadataCsvError("no data rows found")
    return updates


def build_update_payload(new_fields, current_fields):
    """The complete `fields` hash to PUT for one work.

    Avalon's REST API documents `title` as required on update, so it is carried
    over from the work's current metadata whenever the CSV does not set it.
    Leaving it out mostly appears to work -- the stored title is not cleared --
    but the object is then validated without one, and a media object that fails
    validation on `title` is refused outright rather than having the offending
    field erased. That is the one failure Avalon will not paper over.
    """
    payload = preserve_paired_fields(new_fields, current_fields)
    if not payload.get("title"):
        payload["title"] = current_fields.get("title") or ""
    return payload


def preserve_paired_fields(new_fields, current_fields):
    """Carry a work's existing note/other_identifier/related_item_url through.

    Avalon reassigns all three on every update regardless of what was sent, so
    a payload that stays silent about them deletes them. Re-sending the current
    values verbatim is what keeps an unrelated edit non-destructive.
    """
    payload = dict(new_fields)
    for primary, partner in PAIRED_FIELDS.items():
        payload.setdefault(primary, list(current_fields.get(primary) or []))
        payload.setdefault(partner, list(current_fields.get(partner) or []))
    return payload


# api field -> the spreadsheet label to write back out. FIELD_MAP has aliases
# ('subject'/'topical subject', 'abstract'/'summary') so the preferred spelling
# has to be stated rather than inferred.
CANONICAL_LABELS = {
    "title": "Title",
    "alternative_title": "Alternative Title",
    "translated_title": "Translated Title",
    "uniform_title": "Uniform Title",
    "statement_of_responsibility": "Statement of Responsibility",
    "creator": "Creator",
    "date_created": "Date Created",
    "date_issued": "Date Issued",
    "copyright_date": "Copyright Date",
    "abstract": "Abstract",
    "contributor": "Contributor",
    "publisher": "Publisher",
    "genre": "Genre",
    "topical_subject": "Topical Subject",
    "geographic_subject": "Geographic Subject",
    "temporal_subject": "Temporal Subject",
    "language": "Language",
    "terms_of_use": "Terms of Use",
    "table_of_contents": "Table of Contents",
    "physical_description": "Physical Description",
    "series": "Series",
    "comment": "Comment",
    "rights_statement": "Rights Statement",
    "bibliographic_id": "Bibliographic ID",
    "note": "Note",
    "note_type": "Note Type",
    "other_identifier": "Other Identifier",
    "other_identifier_type": "Other Identifier Type",
    "related_item_url": "Related Item URL",
    "related_item_label": "Related Item Label",
}


def write_repeated_column_csv(path, records, work_id_label="work id"):
    """Write rows in Avalon's repeated-column format.

    ``records`` is a list of ``(work_id, {api_field: [values]})``. Each field
    gets as many columns as the widest row needs, so the result can be fed
    straight back into read_replacement_csv -- which is what makes the backup
    a working undo file.
    """
    widths = {}
    for _work_id, fields in records:
        for api_field, values in fields.items():
            widths[api_field] = max(widths.get(api_field, 0), len(_as_list(values)))
    ordered = [f for f in CANONICAL_LABELS if f in widths]

    header = [work_id_label]
    for api_field in ordered:
        header.extend([CANONICAL_LABELS[api_field]] * max(widths[api_field], 1))

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for work_id, fields in records:
            row = [work_id]
            for api_field in ordered:
                values = _as_list(fields.get(api_field))
                width = max(widths[api_field], 1)
                row.extend(values + [""] * (width - len(values)))
            writer.writerow(row)
    return path


def _as_list(value):
    if isinstance(value, list):
        return list(value)
    return [] if value in (None, "") else [value]


def diff_fields(current_fields, new_fields):
    """Per-field (old, new, changed) for the run report."""
    return {
        api_field: (
            _as_list(current_fields.get(api_field)),
            _as_list(new_value),
            _as_list(current_fields.get(api_field)) != _as_list(new_value),
        )
        for api_field, new_value in new_fields.items()
    }
