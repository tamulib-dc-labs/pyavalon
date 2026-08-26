# pyavalon

Tools for doing things in batches in [Avalon](https://avalonmediasystem.org/) at TAMU — as a command line utility and as a Python library.

## Installing

To install and use as a command line utility, use pipx:

```
pipx install pyavalon
```

To use as a library, use pip:

```
pip install pyavalon
```

## Configuration

Commands talk to either the `pre` (staging) or `prod` Avalon instance, selected with `--instance`/`-i` (default: `pre`). Each instance requires an Avalon API key, set via environment variable:

```
export AVALON_PRE="your-pre-instance-api-key"
export AVALON_PROD="your-prod-instance-api-key"
```

## Commands

Run `pyavalon --help` or `pyavalon COMMAND --help` for full details on any command.

### `print_all_collections`

List all collections in the repository.

```
pyavalon print_all_collections -i pre
```

### `create_iiif_collection`

Create a IIIF Collection manifest for a given Avalon collection.

```
pyavalon create_iiif_collection -c "mk61rh127" -o collection.json
```

### `get_file_ids_from_a_collection`

Create a CSV of master files in a collection, with metadata and a path to the best-available derivative. Optionally download the derivatives via `scp`.

```
pyavalon get_file_ids_from_a_collection -c "mk61rh127" -o output.csv
```

Download files while building the CSV:

```
pyavalon get_file_ids_from_a_collection -c "mk61rh127" --download -u myusername -f tmp
```

Only page through a range of results (10 items per page) instead of the whole collection:

```
pyavalon get_file_ids_from_a_collection -c "mk61rh127" --get_range --start 1 --end 5
```

### `get_media_object`

Fetch a media object (or other Avalon object type) and pretty-print it, also writing it to `media_object.json`.

```
pyavalon get_media_object -m "mk61rh127" -t media_object
```

### `upload_supplemental_files`

Upload PDFs, transcripts, or captions to existing files based on a CSV manifest.

CSV columns: `id,filename,label,type` (`type` is one of `pdf`, `caption`, or `transcript`).

```
pyavalon upload_supplemental_files -c supplementals.csv
```

### `delete_supplemental_files`

Delete every supplemental file of a given type from each master file listed in a CSV.

CSV columns: `file id,type`, where type is `transcript`, `captions`, `audio_description`, `pdf`, or `generic`.

```
file id,type
t722h9075,pdf
9593tv433,transcript
bk128b20t,generic
```

Preview first:

```
pyavalon delete_supplemental_files -c deletions.csv -i pre --dry_run
```

Then run it:

```
pyavalon delete_supplemental_files -c deletions.csv -i prod
```

**Deletion cannot be undone through the API**, so every file is downloaded to `deleted_supplemental_files/` before it is removed. If the download fails, nothing is deleted. `--skip_backup` turns that off. A report of every file considered, with its content type and what happened to it, is written to `supplemental_deletion_report.csv`.

#### How types are matched

Avalon has no `pdf` supplemental type. A file's type comes from its tags and is one of `caption`, `transcript`, `audio_description`, or `generic` — and `generic` is the catch-all for anything that is not one of the other three. A PDF, a Word document, and a stray image are indistinguishable in the listing, which carries no content type.

So there are two ways to reach that bucket:

| type in your CSV | what it deletes |
| --- | --- |
| `pdf` | generic files **confirmed by content** to be PDFs. Anything else is left in place and reported as `skipped`. |
| `generic` | every generic attachment whatever its format, PDFs included. |

`generic` is a superset of `pdf`, so listing both for one file id is redundant rather than additive. Use `pdf` when you mean PDFs and `generic` when you mean "clear the attachments" — without that distinction, asking to delete PDFs would quietly take every other attachment with it.

`audio_description` covers files tagged as descriptions. Note that none were present anywhere in a survey of TAMU's production instance, and its API responses lack the `private` and `forced` fields that current Avalon returns — so that deployment appears to predate them. Worth a `--dry_run` to confirm the type resolves at all before relying on it.

One more wrinkle worth knowing: `caption` outranks `transcript`, so a file tagged both reports as `caption` with `treat_as_transcript` set. Deleting captions removes those files; deleting transcripts does not. Matching is on the reported type exactly, and any dual-tagged file caught by a caption deletion is flagged in the report as `also tagged transcript`.

### `find_files_missing_supplementals`

Find all master files in a collection missing a given supplemental file type (`caption`, `transcript`, or `pdf`).

```
pyavalon find_files_missing_supplementals -c "mk61rh127" -t transcript
```

### `get_json_for_whisper_reviewer`

Build a JSON manifest (audio/vtt/url per item) for use with a Whisper transcript reviewer site, from a CSV of media object ids.

CSV columns: `media_object_id,path_to_json,path_to_vtts`.

```
pyavalon get_json_for_whisper_reviewer -c input.csv -o output.json
```

### `replace_metadata`

Replace descriptive metadata on many works at once from a CSV.

The CSV needs a `work id` column plus one column per value you are setting. Repeat a column name to give a field several values, the same way Avalon's own spreadsheets do:

```
work id,Creator,Date Issued,Contributor,Contributor,Contributor
nk322d54j,"Appelt, Leslie L.",2000-12-05,"Monroe, Haskell M.",Cushing Memorial Library & Archives,George Bass
4m90dv76w,"Adkisson, Perry L.",2001-06-23,"Monroe, Haskell M.",Wade Birch,
b2773w02m,"Albritton, Ford",1998-02-27,,,
```

The rules:

- **A field is replaced only if its column appears at all.** `Genre` is missing above, so nobody's genres change.
- **All values for a named field are replaced**, not merged. `nk322d54j` ends up with exactly the three contributors listed.
- **An all-blank column clears the field.** `b2773w02m` loses its contributors entirely.
- Replacing a value with the same value is a no-op, and the report marks it unchanged.

Preview a run without writing anything:

```
pyavalon replace_metadata -c changes.csv -i pre --dry_run
```

Then apply it:

```
pyavalon replace_metadata -c changes.csv -i prod
```

Two files are written either way. `metadata_replacement_report.csv` lists every field with its old value, new value, and whether it actually changed. `metadata_replacement_backup.csv` holds the old values in the same repeated-column format, so a run can be undone by feeding the backup straight back in:

```
pyavalon replace_metadata -c metadata_replacement_backup.csv -i prod
```

Supported columns are the Avalon batch-ingest labels: Title, Creator, Contributor, Publisher, Genre, Abstract, Date Created, Date Issued, Copyright Date, Language, Physical Description, Topical Subject, Geographic Subject, Temporal Subject, Terms of Use, Table of Contents, Statement of Responsibility, Series, Comment, Rights Statement, Bibliographic ID, and the paired Note/Note Type, Other Identifier/Other Identifier Type, Related Item URL/Related Item Label. An unrecognized column is an error rather than a silent skip, since a typo'd header would otherwise leave a field untouched while appearing to have been replaced.

#### Two things worth knowing

Avalon rebuilds **Note, Other Identifier, and Related Item URL** on every update whether or not you send them, so a naive update wipes all three. This command reads each work first and sends its existing values back, which is what keeps an unrelated edit non-destructive. The three paired fields must always be given together with their partner column.

Avalon also erases any field that fails validation and still returns HTTP 200, so every write is read back and compared. Anything that did not stick is reported as `NOT APPLIED`. Note that any update sets the work's uploader to `REST API`; that is Avalon's behaviour and cannot be avoided through the API.

### `create_ami_set`

Builds an AMI set from a collection id.

```
pyavalon create_ami_set -c <collection_id> -i prod -o ami_set.csv
```

## Running Tests

```
pytest
```
