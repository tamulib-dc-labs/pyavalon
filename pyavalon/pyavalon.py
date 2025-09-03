import click
from pyavalon import AvalonMediaObject, AvalonCollection
from pprint import pprint

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