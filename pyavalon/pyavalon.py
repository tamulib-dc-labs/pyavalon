import click
from pyavalon import AvalonCollection, AvalonSupplementalFile, AvalonMediaObject
from pprint import pprint
from csv import DictWriter, DictReader


@click.group()
def cli() -> None:
    pass

@cli.command(
    "print_all_collections", help="Use to find all Collections in the Repository"
)
@click.option(
    "--instance",
    "-i",
    help="The Avalon Instance you want",
    default="pre"
)
def print_all_collections(instance):
    example = AvalonCollection("whatever", prod_or_pre=instance)
    pprint(example.get_all_collections())


@cli.command(
    "get_file_ids_from_a_collection", help="Find all the ids for master files in a collection"
)
@click.option(
    "--collection",
    "-c",
    help="The id of the collection"
)
@click.option(
    "--instance",
    "-i",
    help="The Avalon Instance you want",
    default="pre"
)
@click.option(
    "--output_csv",
    "-o",
    help="The Path to Where to Write Your CSV",
    default="output.csv"
)
def get_file_ids_from_a_colleciton(collection, instance, output_csv):
    final_files = []
    current_collection = AvalonCollection(collection, prod_or_pre=instance)
    all_items = current_collection.page_items()
    for k, v in all_items.items():
        all_files = v['files']
        for file_id in all_files:
            final_files.append(
                {
                    "id": file_id["id"],
                    "label": file_id["label"],
                    "parent label": v["title"], 
                    "derivative": file_id["files"][0]["derivativeFile"]
                }
            )
    with open(output_csv, 'w') as final_csv:
        writer = DictWriter(final_csv, fieldnames=["id", "label", "parent label", "derivative"])
        writer.writeheader()
        writer.writerows(final_files)

@cli.command(
    "get_media_object", help="Get a media object and pretty print."
)
@click.option(
    "--media_object_id",
    "-m",
    help="The id of the media object"
)
@click.option(
    "--instance",
    "-i",
    help="The Avalon Instance you want",
    default="pre"
)
def get_media_object(media_object_id, instance):
    item = AvalonMediaObject(media_object_id, prod_or_pre=instance)
    pprint(item.get_object())


@cli.command(
    "upload_supplemental_files", help="Upload supplemental files to Avalon based on contents of a spreadsheet"
)
@click.option(
    "--instance",
    "-i",
    help="The Avalon Instance you want",
    default="pre"
)
@click.option(
    "--csv",
    "-c",
    help="The path to your CSV",
)
def upload_supplemental_files(instance, csv):
    """CSV should have: id, filename, label, type"""
    with open(csv, 'r') as my_csv:
        reader = DictReader(my_csv)
        for row in reader:
            supplemental = AvalonSupplementalFile(
                row['id'], 
                prod_or_pre="pre"
            )
            if row.get('type') == 'pdf':
                supplemental.add_pdf(
                    row['filename'], 
                    mime_type="application/pdf", 
                    filename=row['label']
                )
            elif row.get('type') == "caption":
                supplemental.add_caption_or_transcript(
                    row['filename'], 
                    label=row['label']
                )
                supplemental.add_caption_or_transcript(
                    row['filename'], 
                    label=f"{row['label']} - Transcripts",
                    type="transcript", 
                )
            elif row.get('type') == "transcript":
                supplemental.add_caption_or_transcript(
                    row['filename'], 
                    type="transcript", 
                    label=row['label']
                )