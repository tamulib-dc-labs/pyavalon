import click
from pyavalon import AvalonCollection, AvalonSupplementalFile, AvalonMediaObject, AvalonMasterFile
from pprint import pprint
from csv import DictWriter, DictReader
import os
import subprocess


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
@click.option(
    "--download",
    is_flag=True,
    help="Download resources in addition to creating CSV."
)
@click.option(
    "--file_output",
    "-f",
    help="The path where to write your files",
    default="tmp"
)
@click.option(
    "--username",
    "-u",
    default="username",
    help="The username you want to download your files"
)
def get_file_ids_from_a_colleciton(collection, instance, output_csv, download, file_output, username):
    final_files = []
    current_collection = AvalonCollection(collection, prod_or_pre=instance)
    all_items = current_collection.page_items()
    for k, v in all_items.items():
        all_files = v['files']
        low = medium = ""
        work_id = v.get('id', "")
        title = v.get('title', "")
        creator = v.get('main_contributors')
        date = v['fields'].get('date_issued', "")
        contributor = v['fields'].get('contributor', [])
        genre = v['fields'].get('genre', [])
        subject = ",".join(v['fields'].get('subject', []))
        topical_subject = ",".join(v['fields'].get('topical_subject', []))
        geographic_subject = ",".join(v['fields'].get('geographic_subject', []))
        temporal_subject = ",".join(v['fields'].get('temporal_subject', []))
        rights = v['fields'].get('terms_of_use', "")
        identifier = ",".join(v['fields'].get('other_identifier', []))
        publisher = ",".join(v['fields'].get('publisher', []))
        for file_id in all_files:
            for derivative in file_id["files"]:
                if 'low' in derivative["derivativeFile"]:
                    low = derivative["derivativeFile"]
                if 'medium' in derivative['derivativeFile']:
                    medium = derivative["derivativeFile"]
            if low != "":
                best = low
            elif medium != "":
                best = medium
            else:
                best = file_id["files"][0]["derivativeFile"]
            final_files.append(
                {
                    "Parent work": work_id,
                    "Creator": ",".join(creator),
                    "Date": date,
                    "Contributor": ",".join(contributor),
                    "File id": file_id['id'],
                    "File title": file_id['label'],
                    "Work title": title,
                    "Subject": f"{subject} {genre} {temporal_subject} {geographic_subject} {topical_subject}",
                    "Rights": rights,
                    "Identifier": identifier,
                    "Publisher": publisher,
                    "derivative": best.replace("file://", "").replace("avalon", f"avalon_{instance}")
                }
            )
    if download:
        os.makedirs(file_output, exist_ok=True)
        for derivative in final_files:
            command = [
                "scp",
                f"{username}@access.library.tamu.edu:{derivative['derivative']}",
                file_output
            ]
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError:
                print(
                    f"Failed to download {derivative.get('derivative')} from {derivative.get('parent label')} - {derivative.get('label')}.")

            
    with open(output_csv, 'w') as final_csv:
        writer = DictWriter(final_csv, fieldnames=final_files[0].keys())
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
@click.option(
    "--type",
    "-t",
    help="The Avalon Instance you want",
    default="media_object"
)
def get_media_object(media_object_id, instance, type):
    item = AvalonMediaObject(media_object_id, prod_or_pre=instance)
    pprint(item.get_object(type=type))


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
                prod_or_pre=instance
            )
            if row.get('type').strip() == 'pdf':
                supplemental.add_pdf(
                    row['filename'], 
                    mime_type="application/pdf", 
                    filename=row['label']
                )
            elif row.get('type').strip() == "caption":
                supplemental.add_caption_or_transcript(
                    row['filename'], 
                    label=row['label']
                )
            elif row.get('type').strip() == "transcript":
                supplemental.add_caption_or_transcript(
                    row['filename'], 
                    type="transcript", 
                    label=row['label']
                )

@cli.command(
    "find_files_missing_supplementals", help="Find all master files in a collection that are missing a particular file type"
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
    "--file_type",
    "-t",
    help="The type you are looking for: caption, transcript, or pdf",
    default="transcript"
)
def find_files_missing_supplementals(collection, instance, file_type):
    bad_files = []
    current_collection = AvalonCollection(collection, prod_or_pre=instance)
    all_items = current_collection.page_items()
    for k, v in all_items.items():
        all_files = v['files']
        for filename in all_files:
            present = False
            master_file = filename['id']
            master = AvalonMasterFile(master_file, prod_or_pre=instance)
            suppls = master.get_supplemental_files()
            for suppl in suppls:
                if file_type == "pdf":
                    if 'generic' in suppl['type'] or 'pdf' in suppl['type']:
                        present = True
                else:
                    if file_type == suppl['type']:
                        present = True
            if not present:
                bad_files.append(
                    {
                        "master_file_id": master_file,
                        "label": filename["label"],
                        "parent label": v["title"], 
                    }
                )
    pprint(bad_files)
