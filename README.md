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

## Running Tests

```
pytest
```
