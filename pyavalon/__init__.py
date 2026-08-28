from .avalon import AvalonMediaObject as AvalonMediaObject, AvalonCollection as AvalonCollection, AvalonSupplementalFile as AvalonSupplementalFile, AvalonMasterFile as AvalonMasterFile, replace_metadata_from_csv as replace_metadata_from_csv, delete_supplemental_files_from_csv as delete_supplemental_files_from_csv, MetadataCsvError as MetadataCsvError, SupplementalCsvError as SupplementalCsvError, read_replacement_csv as read_replacement_csv, read_deletion_csv as read_deletion_csv
try:
    from .pdf import HTMLPDFBuilder as HTMLPDFBuilder
except Exception:  # pragma: no cover
    # weasyprint needs GTK native libraries that are usually absent on Windows.
    # Importing it here made every command in the CLI fail, including ones that
    # have nothing to do with PDFs, so the failure is deferred to first use.
    HTMLPDFBuilder = None
