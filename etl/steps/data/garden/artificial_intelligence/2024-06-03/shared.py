from typing import List

import pandas as pd
from owid.catalog import Table


def calculate_aggregates(tb: Table, agg_column: str, short_name: str, unused_columns: List[str]) -> Table:
    """
    This function calculates aggregates for a given column in a Table. It is used to calculate the total yearly and cumulative number of notable AI systems for each domain or country.

    Parameters:
    tb (Table): The input Table.
    agg_column (str): The column to aggregate on.
    short_name (str): The short name to set for the table.
    unused_columns (List[str]): The list of columns to drop from the table.

    Returns:
    Table: The output Table with calculated aggregates.
    """
    # Select the rows where the 'notability_criteria' column is not null (only consider notable systems)
    tb = tb[tb["notability_criteria"].notna()].reset_index(drop=True)

    # Store the origins metadata for later use
    origins = tb[agg_column].metadata.origins

    # Drop the unused columns
    tb = tb.drop(unused_columns, axis=1)

    # Convert the 'publication_date' column to datetime format and extract the year
    tb["publication_date"] = pd.to_datetime(tb["publication_date"])
    tb["year"] = tb["publication_date"].dt.year

    # Split the column to be aggregated by comma (several countries/domains can exist in each cell)
    tb[agg_column] = tb[agg_column].str.split(",")

    # Explode the table to create separate rows for each country or domain
    tb_exploded = tb.explode(agg_column)

    # Convert the column to category type so that the missing values will be considered as 0
    tb_exploded[agg_column] = tb_exploded[agg_column].astype("category")

    # Drop duplicates where the year, system and country/domain are the same
    tb_unique = tb_exploded.drop_duplicates(subset=["year", "system", agg_column])

    # Group by year and country/domain and count the number of systems (consider all categories which will assume 0 for missing values)
    tb_agg = tb_unique.groupby(["year", agg_column], observed=False).size().reset_index(name="yearly_count")

    # Add the origins metadata to the 'number_of_systems' column
    tb_agg["yearly_count"].metadata.origins = origins

    # Calculate the cumulative count (consider all categories which will assume 0 for missing values)
    tb_agg["cumulative_count"] = tb_agg.groupby(agg_column, observed=False)["yearly_count"].cumsum()

    # Add the origins metadata to the columns
    for col in ["yearly_count", "cumulative_count"]:
        tb_agg[col].metadata.origins = origins

    # Set the short_name metadata of the table
    tb_agg.metadata.short_name = short_name

    return tb_agg
