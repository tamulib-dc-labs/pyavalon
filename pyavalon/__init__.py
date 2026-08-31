from .avalon import AvalonMediaObject as AvalonMediaObject, AvalonCollection as AvalonCollection, AvalonSupplementalFile as AvalonSupplementalFile, AvalonMasterFile as AvalonMasterFile
from .avalon import replace_metadata as replace_metadata, MetadataCsvError as MetadataCsvError
from .avalon import delete_supplemental_files as delete_supplemental_files, SupplementalCsvError as SupplementalCsvError

__all__ = [
    "AvalonMediaObject",
    "AvalonCollection",
    "AvalonSupplementalFile",
    "AvalonMasterFile",
    "replace_metadata",
    "MetadataCsvError",
    "delete_supplemental_files",
    "SupplementalCsvError",
    "HTMLPDFBuilder",
]


def __getattr__(name):
    """
    Resolve HTMLPDFBuilder only when it is actually asked for.

    It pulls in weasyprint, which needs GTK native libraries that are not on a
    default Windows install. Importing it up here made every command in the
    package -- including the ones that never touch a PDF -- fail at import
    time on those machines.
    """
    if name == "HTMLPDFBuilder":
        from .pdf import HTMLPDFBuilder

        return HTMLPDFBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
