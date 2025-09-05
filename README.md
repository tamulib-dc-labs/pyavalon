# pyavalon

Tools for doing things in batches in Avalon at TAMU.

## Installing

To install and use as a command line utility, just use pipx:

```
pipx install pyavalon
```

To use as a library, use pip:

```
pip install pyavalon
```

## Get File Ids in a Collection

Creates a CSV with `id,label,parent label,derivative`

```
pyavalon get_file_ids_from_a_collection -c "mk61rh127"
```

## Add PDFs, Transcripts or Captions to Files

Requires a CSV with `id,filename,label,type`

```
pyavalon upload_supplemental_files -c test_avalon.csv
```

## Running Tests

```
pytest
```