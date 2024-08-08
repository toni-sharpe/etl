"""Load a garden dataset and create a grapher dataset."""

from shared import to_grapher_date

from etl.helpers import PathFinder, create_dataset

# Get paths and naming conventions for current step.
paths = PathFinder(__file__)


def run(dest_dir: str) -> None:
    #
    # Load inputs.
    #
    # Load garden dataset.
    ds_garden = paths.load_dataset("yougov")

    # Read table from garden dataset.
    tb = ds_garden["yougov"]
    tb_composite = ds_garden["yougov_composite"]

    #
    # Process data.
    #
    tables = [
        to_grapher_date(tb, "2020-01-21"),
        to_grapher_date(tb_composite, "2020-01-21"),
    ]

    #
    # Save outputs.
    #
    # Create a new grapher dataset with the same metadata as the garden dataset.
    ds_grapher = create_dataset(
        dest_dir, tables=tables, check_variables_metadata=True, default_metadata=ds_garden.metadata
    )

    # Save changes in the new grapher dataset.
    ds_grapher.save()
