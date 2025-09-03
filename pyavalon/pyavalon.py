import click
from pyavalon import AvalonMediaObject, AvalonCollection
from pprint import pprint
from csv import DictWriter

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
                    "label": file_id["label"]
                }
            )
    with open(output_csv, 'w') as final_csv:
        writer = DictWriter(final_csv, fieldnames=["id", "label"])
        writer.writeheader()
        writer.writerows(final_files)