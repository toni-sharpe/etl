"""Common processing of FAOSTAT datasets.

We have created a manual ranking of FAOSTAT flags. These flags are only used when there is ambiguity in the data,
namely, when there is more than one data value for a certain country-year-item-element-unit.
NOTES:
* We check that the definitions in our manual ranking agree with the ones provided by FAOSTAT.
* We do not include all flags: We include only the ones that solve an ambiguity in a particular case,
  and add more flags as we see need.
* We have found at least one flag that appeared in a dataset, but was not included in the additional metadata
  (namely flag "R", found in qcl dataset).
  This flag was added manually, using the definition in List / Flags in:
  https://www.fao.org/faostat/en/#definitions
* Unfortunately, flags do not remove all ambiguities: remaining duplicates are dropped without any meaningful criterion.

"""

from copy import deepcopy
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
from owid import catalog
from owid.datautils import geo

from etl.paths import DATA_DIR, STEP_DIR


NAMESPACE = Path(__file__).parent.parent.name
VERSION = Path(__file__).parent.name

# Regions to add to the data.
# TODO: Add region aggregates to relevant columns.
REGIONS_TO_ADD = [
    "North America",
    "South America",
    "Europe",
    "European Union (27)",
    "Africa",
    "Asia",
    "Oceania",
    "Low-income countries",
    "Upper-middle-income countries",
    "Lower-middle-income countries",
    "High-income countries",
]

# Rank flags by priority (where lowest index is highest priority).
# TODO: Discuss this flag ranking with others (they are quite arbitrary at the moment).
FLAGS_RANKING = (
    pd.DataFrame.from_records(
        columns=["flag", "description"],
        data=[
            (np.nan, "Official data"),
            ("F", "FAO estimate"),
            (
                "A",
                "Aggregate, may include official, semi-official, estimated or calculated data",
            ),
            ("Fc", "Calculated data"),
            (
                "I",
                "Country data reported by International Organizations where the country is a member (Semi-official) - WTO, EU, UNSD, etc.",
            ),
            (
                "W",
                "Data reported on country official publications or web sites (Official) or trade country files",
            ),
            ("Fm", "Manual Estimation"),
            ("Q", "Official data reported on FAO Questionnaires from countries"),
            ("*", "Unofficial figure"),
            ("Im", "FAO data based on imputation methodology"),
            ("M", "Data not available"),
            ("R", "Estimated data using trading partners database"),
            ("SD", "Statistical Discrepancy"),
            ("S", "Standardized data"),
            (
                "Qm",
                "Official data from questionnaires and/or national sources and/or COMTRADE (reporters)",
            ),
            ("Fk", "Calculated data on the basis of official figures"),
            ("Fb", "Data obtained as a balance"),
            ("E", "Expert sources from FAO (including other divisions)"),
            ("X", "International reliable sources"),
            ("Bk", "Break in series"),
            ("NV", "Data not available"),
            ("FC", "Calculated data"),
        ],
    )
    .reset_index()
    .rename(columns={"index": "ranking"})
)


def check_that_flag_definitions_in_dataset_agree_with_those_in_flags_ranking(additional_metadata):
    """TODO"""
    for table_name in additional_metadata.table_names:
        if "flag" in table_name:
            flag_df = additional_metadata[table_name].reset_index()
            comparison = pd.merge(FLAGS_RANKING, flag_df, on="flag", how="inner")
            error_message = (
                f"Flag definitions in file {table_name} are different to those in our flag ranking. "
                f"Redefine flag ranking."
            )
            assert (
                comparison["description"] == comparison["flags"]
            ).all(), error_message


def check_that_all_flags_in_dataset_are_in_ranking(data, additional_metadata_for_flags):
    """TODO"""
    if not set(data['flag']) < set(FLAGS_RANKING["flag"]):
        missing_flags = list(
            set(
                data[data.duplicated(subset=["country", "year", "item", "element"])][
                    "flag"
                ]
            )
            - set(FLAGS_RANKING["flag"])
        )
        flags_data = pd.DataFrame(additional_metadata_for_flags).reset_index()
        if set(missing_flags) < set(flags_data["flag"]):
            print(
                "Manually copy the following lines to FLAGS_RANKING (and put them in the right order):"
            )
            for i, j in (
                pd.DataFrame(additional_metadata_for_flags)
                .loc[missing_flags]
                .iterrows()
            ):
                print(f"{(i, j['flags'])},")
        else:
            print(
                f"Not all flags ({missing_flags}) are defined in additional metadata. Get their definition from "
                f"https://www.fao.org/faostat/en/#definitions"
            )
        raise AssertionError("Flags in dataset not found in FLAGS_RANKING. Manually add those flags.")


def check_that_there_are_as_many_entity_codes_as_entities(data):
    """TODO"""
    # Check that there are as many codes for area, element and unit and actual areas, elements and units.
    for entity in ["area", "element", "item"]:
        if len(data[f"{entity}_code"].unique()) != len(data[f"{entity}"].unique()):
            print(
                f"WARNING: The number of unique {entity} codes is different to the number "
                f"of unique {entity}s. Consider ignoring '{entity}' column, and instead mapping '{entity}_code' "
                f"using the {entity} from metadata."
            )


def remove_rows_with_nan_value(data, verbose=True):
    """TODO"""
    data = data.copy()
    # Number of rows with a nan in column "value".
    # We could also remove rows with any nan, however, before doing that, we would need to assign a value to nan flags.
    n_rows_with_nan_value = len(data[data["value"].isnull()])
    if n_rows_with_nan_value > 0:
        if verbose:
            print(f"Removing {n_rows_with_nan_value} rows ({n_rows_with_nan_value / len(data): .2%}) "
                  f"with nan in column 'value'.")
        data = data.dropna(subset="value").reset_index(drop=True)

    return data


def remove_columns_that_only_have_nans(data, verbose=True):
    """TODO"""
    data = data.copy()
    # Remove columns that only have nans.
    columns_of_nans = data.columns[data.isnull().all(axis=0)]
    if len(columns_of_nans) > 0:
        if verbose:
            print(f"Removing {len(columns_of_nans)} columns ({len(columns_of_nans) / len(data.columns): .2%}) "
                  f"that have only nans.")
        data = data.drop(columns=columns_of_nans)

    return data


def create_wide_table_with_metadata_from_long_dataframe(data_long, table_metadata):
    """TODO"""
    data_long = data_long.copy()
    table_metadata = deepcopy(table_metadata)

    # Combine item, element and unit into one column.
    data_long["title"] = (
        data_long["item"].astype(str)
        + " - "
        + data_long["element"].astype(str)
        + " ("
        + data_long["unit"].astype(str)
        + ")"
    )

    # Keep a dataframe of just units (which will be required later on).
    units = data_long.pivot(index=["country", "year"], columns=["title"], values="unit")

    # This will create a table with just one column and country-year as index.
    data = data_long.pivot(index=["country", "year"], columns=["title"], values="value")

    # Remove columns that only have nans.
    data = remove_columns_that_only_have_nans(data)

    # Sort data columns and rows conveniently.
    data = data[sorted(data.columns)]
    data = data.sort_index(level=["country", "year"])

    # Create new table for garden dataset.
    wide_table = catalog.Table(data).copy()
    for column in wide_table.columns:
        variable_units = units[column].dropna().unique()
        assert len(variable_units) == 1, f"Variable {column} has ambiguous units."
        unit = variable_units[0]
        # Remove unit from title (only last occurrence of the unit).
        title = " ".join(column.rsplit(f" ({unit})", 1)).strip()

        # Add title and unit to each column in the table.
        wide_table[column].metadata.title = title
        wide_table[column].metadata.unit = unit

    # Make all column names snake_case.
    wide_table = catalog.utils.underscore_table(wide_table)

    # Use the same table metadata as from original meadow table, but update index.
    wide_table.metadata = deepcopy(table_metadata)
    wide_table.metadata.primary_key = ["country", "year"]

    # TODO: Check why in food_explorer, _fields are also added to the table.
    # data_table_garden._fields = fields

    return wide_table


def remove_duplicates(data):
    """TODO"""
    data = data.copy()

    # Add flag ranking to dataset.
    data = pd.merge(data, FLAGS_RANKING[["flag", "ranking"]].rename(columns={"ranking": "flag_ranking"}),
                    on="flag", how="left")

    # Number of ambiguous indices (those that have multiple data values).
    index_columns = ["country", "year", "item", "element", "unit"]
    n_ambiguous_indices = len(data[data.duplicated(subset=index_columns, keep="first")])
    if n_ambiguous_indices > 0:
        # Number of ambiguous indices that cannot be solved using flags.
        n_ambiguous_indices_unsolvable = len(data[
            data.duplicated(subset=index_columns + ["flag_ranking"], keep="first")])
        # Remove ambiguous indices (those that have multiple data values).
        # When possible, use flags to prioritise among duplicates.
        data = data.sort_values(index_columns + ['flag_ranking']).drop_duplicates(
            subset=index_columns, keep="first")
        frac_ambiguous = n_ambiguous_indices / len(data)
        frac_ambiguous_solved_by_flags = 1 - (n_ambiguous_indices_unsolvable / n_ambiguous_indices)
        print(f"Removing {n_ambiguous_indices} ambiguous indices ({frac_ambiguous: .2%}).")
        print(f"{frac_ambiguous_solved_by_flags: .2%} of ambiguities were solved with flags.")

    data = data.drop(columns=["flag_ranking"])

    return data


def clean_data(data, countries_file):
    data = data.copy()

    # Remove rows with nan value.
    data = remove_rows_with_nan_value(data)

    # Ensure column of values is numeric (transform any possible value like "<1" into a nan, and remove those rows).
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = remove_rows_with_nan_value(data)

    # Sanity checks.
    check_that_there_are_as_many_entity_codes_as_entities(data)
    # Ensure that each element has only one unit.
    error = "Some elements in the combined dataset have more than one unit."
    assert data.groupby("element")["unit"].nunique().max() == 1, error
    error = "Some elements in the combined dataset have more than one description."
    assert data.groupby("element")["description"].nunique().max() == 1, error

    # Harmonize country names.
    assert countries_file.is_file(), "countries file not found."
    data = geo.harmonize_countries(
        df=data,
        countries_file=countries_file,
        country_col="area",
        warn_on_unused_countries=False,
    ).rename(columns={"area": "country"})
    # If countries are missing in countries file, execute etl.harmonize again and update countries file.
    ####################################################################################################################
    # TODO: Remove this temporary solution once grapher accepts mapping of all countries.
    data = data[~data["country"].str.endswith("(FAO)")].reset_index(drop=True)
    ####################################################################################################################

    # After harmonizing, there are some country-year with more than one item-element.
    # This happens for example because there is different data for "Micronesia" and "Micronesia (Federated States of)",
    # which are both mapped to the same country, "Micronesia (country)".
    # The same happens with "China", and "China, mainland".
    # TODO: Solve possible issue of duplicated regions in China
    # (https://github.com/owid/owid-issues/issues/130#issuecomment-1114859105).
    # In cases where a country-year has more than one item-element, try to remove duplicates by looking at the flags.
    # If flags do not remove the duplicates, raise an error.

    # Ensure year column is integer (in previous versions it seems sometimes there were ranges, like 2013-2015).
    try:
        data["year"] = data["year"].astype(int)
    except ValueError:
        print(f"WARNING: Dataset may have years defined by intervals. Map them to a year.")

    # Remove duplicated data points keeping the one with lowest ranking (i.e. highest priority).
    data = remove_duplicates(data)

    # We can now remove entity codes and flags.
    data = data.drop(
        columns=["area_code", "element_code", "item_code", "flag"]
    )

    return data


def run(dest_dir: str) -> None:
    ####################################################################################################################
    # Common definitions.
    ####################################################################################################################

    # Assume dest_dir is a path to the step that needs to be run, e.g. "faostat_qcl", and fetch namespace and dataset
    # short name from that path.
    dataset_short_name = Path(dest_dir).name
    namespace = dataset_short_name.split("_")[0]
    dataset_code = dataset_short_name.split("_")[1]
    # Path to latest dataset in meadow.
    meadow_version_dir = sorted(
        (DATA_DIR / "meadow" / namespace).glob(f"*/{dataset_short_name}")
    )[-1].parent
    # Version of meadow dataset, which will also be the version of the analogous garden dataset.
    version = meadow_version_dir.name
    # Get dataset version from folder name with latest date.
    meadow_data_dir = meadow_version_dir / dataset_short_name
    garden_code_dir = STEP_DIR / "data" / "garden" / namespace / version
    countries_file = garden_code_dir / f"{namespace}.countries.json"
    additional_metadata_dir = meadow_version_dir / f"{namespace}_metadata"

    ####################################################################################################################
    # Load data.
    ####################################################################################################################

    # Additional metadata of all FAO datasets (used for sanity checks).
    additional_metadata = catalog.Dataset(additional_metadata_dir)

    # Sanity checks.
    check_that_flag_definitions_in_dataset_agree_with_those_in_flags_ranking(additional_metadata)

    # Load meadow dataset and keep its metadata.
    dataset_meadow = catalog.Dataset(meadow_data_dir)

    # Load main table from dataset.
    data_table_meadow = dataset_meadow[dataset_short_name]
    data = pd.DataFrame(data_table_meadow).reset_index()

    # Sanity checks.
    check_that_all_flags_in_dataset_are_in_ranking(data, additional_metadata[f"meta_{dataset_code}_flag"])

    ####################################################################################################################
    # Process data.
    ####################################################################################################################

    data = clean_data(data=data, countries_file=countries_file)

    # Create new table for garden dataset (use metadata from original meadow table).
    data_table_garden = create_wide_table_with_metadata_from_long_dataframe(
        data_long=data, table_metadata=data_table_meadow.metadata)

    # TODO: Run more sanity checks on the new wide data.

    ####################################################################################################################
    # Prepare outputs.
    ####################################################################################################################

    # Initialize new garden dataset.
    dataset_garden = catalog.Dataset.create_empty(dest_dir)
    # Keep original dataset's metadata from meadow.
    dataset_garden.metadata = deepcopy(dataset_meadow.metadata)
    # Create new dataset in garden.
    dataset_garden.save()
    # Add table to dataset.
    dataset_garden.add(data_table_garden)
