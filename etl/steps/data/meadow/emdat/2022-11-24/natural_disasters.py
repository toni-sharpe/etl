"""Load snapshot of EM-DAT natural disasters data and prepare a table with basic metadata.

"""

import warnings

import pandas as pd
from owid.catalog import Dataset, Table, TableMeta
from owid.catalog.utils import underscore_table

from etl.helpers import Names
from etl.paths import SNAPSHOTS_DIR
from etl.snapshot import Snapshot
from etl.steps.data.converters import convert_snapshot_metadata

# Snapshot version.
SNAPSHOT_VERSION = "2022-11-24"
# Current Meadow dataset version.
VERSION = SNAPSHOT_VERSION

# Get naming conventions.
N = Names(__file__)

# Columns to extract from raw data, and how to rename them.
COLUMNS = {
    "Country": "country",
    "Year": "year",
    "Disaster Group": "group",
    "Disaster Subgroup": "subgroup",
    "Disaster Type": "type",
    "Disaster Subtype": "subtype",
    "Disaster Subsubtype": "subsubtype",
    "Event Name": "event",
    "Region": "region",
    "Continent": "continent",
    "Total Deaths": "dead",
    "No Injured": "injured",
    "No Affected": "affected",
    "No Homeless": "homeless",
    "Total Affected": "total_affected",
    "Reconstruction Costs, Adjusted ('000 US$)": "reconstructed_costs_adjusted",
    "Insured Damages, Adjusted ('000 US$)": "insured_damages_adjusted",
}


def run(dest_dir: str) -> None:
    # Load snapshot.
    snap = Snapshot(SNAPSHOTS_DIR / "emdat" / SNAPSHOT_VERSION / "natural_disasters.xlsx")
    with warnings.catch_warnings(record=True):
        df = pd.read_excel(snap.path, sheet_name="emdat data", skiprows=6)

    # Select and rename columns.
    df = df[list(COLUMNS)].rename(columns=COLUMNS)

    # Create a new dataset and reuse snapshot metadata.
    ds = Dataset.create_empty(dest_dir)
    ds.metadata = convert_snapshot_metadata(snap.metadata)
    ds.metadata.version = VERSION

    # Create a table with metadata from dataframe.
    table_metadata = TableMeta(
        short_name=snap.metadata.short_name,
        title=snap.metadata.name,
        description=snap.metadata.description,
    )
    tb = Table(df, metadata=table_metadata)

    # Ensure all tables have underscore columns.
    tb = underscore_table(tb)

    # Add table to new dataset and save dataset.
    ds.add(tb)
    ds.save()
