# pyavalon

Tools for doing things in batches in Avalon.

**This is a work in progress.**

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