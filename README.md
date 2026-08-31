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

On Windows PowerShell:

```powershell
$env:AVALON_PRE = "your-pre-instance-api-key"
$env:AVALON_PROD = "your-prod-instance-api-key"
```

`$env:` variables last only for the current PowerShell window. Use `setx AVALON_PRE "your-key"` to keep them (then open a new window).

Or skip the shell entirely: copy `.env.example` to `.env.local` in the directory you run from and put the keys there. It is read at startup and is gitignored. Anything already set in the environment wins, so an explicit `export`/`$env:` still overrides the file.

```
AVALON_PRE=your-pre-instance-api-key
AVALON_PROD=your-prod-instance-api-key
```

Reads do not need a key — published works are publicly readable — so a missing key only shows up when you try to write, and Avalon rejects an unauthenticated write with a bare `422 Unprocessable Entity` that names no field. Every command checks for the key before making a request rather than letting you hit that.

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

### `create_ami_set`

Builds an AMI set from a collection id.

```
pyavalon create_ami_set -c <collection_id> -i prod -o ami_set.csv
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
- **All values for a named field are replaced**, not merged. `nk322d54j` ends up with exactly the three contributors listed, and `4m90dv76w` loses Cushing because its row does not repeat it.
- **An all-blank column clears the field.** `b2773w02m` loses its contributors entirely. This is why you should delete any column you are not changing rather than leaving it in and empty.
- **Except `Title` and `Date Issued`.** Leaving either blank is reported as an error and the row is skipped; remove the column instead if you do not want to change it. (The API docs badge only `title` as REQUIRED, but Avalon rejects an empty `date_issued` too, with `"Date issued field is required."`)
- Replacing a value with the same value is a no-op, and the report marks it unchanged.

Preview a run without writing anything:

```
pyavalon replace_metadata -c changes.csv -i pre --dry_run
```

Then apply it:

```
pyavalon replace_metadata -c changes.csv -i prod
```

Either way a report is written to `metadata_replacement_report.csv` (`-o` to change it), listing every field with its old value, new value, and whether it actually changed.

**Column names are the field names from the [API docs](https://samvera.atlassian.net/wiki/spaces/AVALON/pages/1957954917/REST+API)**, so what you type in the sheet is what you read there:

`title`, `date_issued`, `creator`, `alternative_title`, `translated_title`, `uniform_title`, `statement_of_responsibility`, `date_created`, `copyright_date`, `abstract`, `note`, `note_type`, `contributor`, `publisher`, `genre`, `subject`, `related_item_url`, `geographic_subject`, `temporal_subject`, `topical_subject`, `bibliographic_id`, `language`, `terms_of_use`, `table_of_contents`, `physical_description`, `other_identifier`, `other_identifier_type`, `comment`.

Title Case with spaces works too — `date_issued` and `Date Issued` are the same column — so a spreadsheet exported from Avalon can be fed straight back in. An unrecognized column aborts the run rather than being skipped, since a typo'd header would otherwise leave a field untouched while the run reported success.

`work id` is not a metadata field and is not part of the request body — it names which object the row updates and goes into the URL. `format` and `resource_type` are in the documented body but describe the media files rather than the description, so they are not offered as columns; they appear on the template's **Fields** sheet marked `NOT A COLUMN` so it is clear they were not simply forgotten.

Two of those are documented but do not work: **`subject`** and **`statement_of_responsibility`** are accepted with a 200 and stored by nobody. They are still offered, because the docs list them, but the command warns on the way in and the read-back reports them as `NOT APPLIED`. Use `topical_subject` instead of `subject` — a GET returns the same values in both, and that is the half that stores.

#### One value per column, and quote your commas

Each value gets its own column. Values are never split on `;` or any other delimiter, so putting several names in one cell gives you one long name, not several:

```
work id,Contributor
p2676v80j,"Lane, Daryl; Crews, David"        <- ONE contributor
```

And because inverted names contain commas, they have to be quoted:

```
work id,Contributor,Contributor
p2676v80j,"Lane, Daryl","Crews, David"       <- two contributors
p2676v80j,Lane, Daryl,Crews, David           <- four values: Lane, Daryl, Crews, David
```

Let a spreadsheet or `csv.writer` do the quoting for you. Run with `--dry_run` first and check the report — an unquoted comma shows up immediately as values landing in the wrong fields.


#### Things worth knowing about Avalon

- **Title and Date Issued are required.** Avalon rejects a work without them, so a blank `Title` or `Date Issued` column is refused up front rather than sent and 422'd.
- **Note, Other Identifier, and Related Item URL are rebuilt on every update**, so a naive update wipes all three even when it never mentions them. This command reads each work first and sends the existing values back, which is what keeps an unrelated edit non-destructive.
- **Avalon can return 200 without storing a value** — a `Bibliographic ID`, for instance, cannot be cleared once set. Every write is read back and compared, and anything that did not stick is reported as `NOT APPLIED`.
- The update body carries the work's `collection_id` alongside `fields`, read from the work before writing. It is not marked REQUIRED in the docs and an update without it works fine, so a work that comes back without one is still updated — the key is simply left out.
- Any update sets the work's uploader to `REST API`. That is Avalon's behaviour and cannot be avoided through the API.


### `delete_supplemental_files`

Delete supplemental files (captions, transcripts, or other attachments) from many works at once. The inverse of `upload_supplemental_files`.

The CSV needs a `work id` column and a `type` column:

```
work id,type
w6634371m,generic
nk322d54j,captions
b2773w02m,transcript
```

Supplemental files hang off master files, not works, so each work is read first and **every master file on it** is swept. One row can therefore delete files from several master files.

`template.xlsx` carries this format on its **Delete Template** sheet, with the valid types documented on **Delete Types**.

Preview first:

```
pyavalon delete_supplemental_files -c cleanup.csv -i pre --dry_run
```

Then apply:

```
pyavalon delete_supplemental_files -c cleanup.csv -i pre
```

A report is written to `supplemental_deletion_report.csv` (`-o` to change it) listing every file considered, with the master file it came from, its id, label, and whether it was deleted. A work where nothing matched still gets a row, so a typo'd id does not look like a clean sweep.

**This cannot be undone.** Avalon returns no body on a delete and the binary is gone, so the report is the only record of what happened. Run `--dry_run` first.

#### The types

| `type` | Deletes |
| --- | --- |
| `caption` / `captions` | supplementals stored as `caption` |
| `transcript` / `transcripts` | supplementals stored as `transcript` |
| `generic` / `generics` | supplementals stored as `generic` |

These are Avalon's own type values, matched exactly as stored. Two things follow from that:

- **`pdf` is not a type and is refused.** A PDF uploaded through `upload_supplemental_files` is stored as `generic`, and so is every other non-caption attachment — a spreadsheet, an image, anything. There is no way to single out the PDFs, so asking for `pdf` gets an error pointing you at `generic`. Use `generic` when you do mean "every attachment of that kind", and check the `--dry_run` report before you commit to it.
- **A caption can carry `treat_as_transcript`** — `upload_supplemental_files` sets that flag on captions and transcripts alike. `transcript` matches only what is actually stored as `transcript`, so a flagged caption is left alone; ask for `captions` to remove those.

An unrecognized `type` aborts the run before anything is deleted.


## Spreadsheet templates

`template.xlsx` in the repo root has four sheets. **Fields** lists every accepted metadata column with its type, whether it is required, and an example; **Template** is a ready-to-fill sheet for `replace_metadata`. **Delete Types** and **Delete Template** do the same for `delete_supplemental_files`. Fill in the sheet you need, delete the columns you are not changing, save as CSV, and feed it to the command.

Regenerate it with `python scripts/make_template.py` (needs `pip install openpyxl`).

There is also a working sample at `fixtures/metadata-replacement-sample.csv`, built from two real works on `pre` and filled with their current values. Running it as-is changes nothing — every field is replaced with what is already there — so it is a safe way to confirm your API key and the round trip before you touch anything:

```
pyavalon replace_metadata -c fixtures/metadata-replacement-sample.csv -i pre --dry_run
```

Edit any cell and that field becomes a real change.

## Running Tests

```
pytest
```
