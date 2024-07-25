"""Load a snapshot and create a meadow dataset."""

import re

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from owid.catalog import Table

from etl.helpers import PathFinder, create_dataset

# Get paths and naming conventions for current step.
paths = PathFinder(__file__)


def run(dest_dir: str) -> None:
    #
    # Load inputs.
    #
    # Retrieve snapshot.
    snap = paths.load_snapshot("papers_with_code_imagenet.html")

    # Load data from snapshot.
    with open(snap.path, "r") as file:
        html_content = file.read()

    df = extract_html(html_content)

    # Find the index of the max 'performance' in each group
    idx = df.groupby(["date", "name"])["top_1_accuracy"].idxmax()

    # Select the rows with these indices
    df = df.loc[idx]

    #
    # Process data.
    #
    tb = Table(df, short_name=paths.short_name, metadata=snap.to_table_metadata())

    # Ensure metadata is correctly associated.
    for column in tb.columns:
        tb[column].metadata.origins = [snap.metadata.origin]

    # Ensure all columns are snake-case, set an appropriate index, and sort conveniently.
    tb = tb.format(["name", "date"])

    #
    # Save outputs.
    #
    # Create a new meadow dataset with the same metadata as the snapshot.
    ds_meadow = create_dataset(dest_dir, tables=[tb], check_variables_metadata=True, default_metadata=snap.metadata)

    # Save changes in the new meadow dataset.
    ds_meadow.save()


def extract_html(html_content):
    """
    Extracts table data from the HTML content of the image classification page on Papers with Code.

    Args:
        html_content (str): The HTML content of the image classification page.

    Returns:
        pandas.DataFrame: A DataFrame containing the extracted table data.

    Raises:
        AssertionError: If the evaluation script or script content is not found, or if any required fields are missing in an entry.

    """
    # Parse the HTML using BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")

    # Find the script with id="evaluation-table-data"
    evaluation_script = soup.find("script", id="evaluation-table-data")

    assert evaluation_script is not None, "Evaluation script not found in HTML content."

    # Extract the contents of the script tag
    script_content = str(evaluation_script)

    assert script_content is not None, "Script content is empty."
    script_bytes = script_content.encode("utf-8")

    # Extract the entries using regex pattern
    pattern = rb'{"table_id": 116.*?(?=\{"table_id": 116|$)'

    entries = re.findall(pattern, script_bytes)

    assert entries, "No entries found in script content."

    # Create a list to store the extracted data
    table_data = []

    # Iterate through each entry
    for entry in entries:
        entry_str = entry.decode("utf-8")

        # Extract the desired fields using regex
        method_short_match = re.search(r'"method":\s*"([^"]*)"', entry_str)
        top_1_accuracy = re.search(r'"Top 1 Accuracy":\s*"([^"]*)"', entry_str)
        evaluation_date_match = re.search(r'"evaluation_date":\s*"([^"]*)"', entry_str)

        # Extract the values from the match objects if available
        method_short = (
            method_short_match.group(1) if method_short_match and method_short_match.group(1) != "null" else np.nan
        )
        top_1_accuracy = top_1_accuracy.group(1) if top_1_accuracy and top_1_accuracy.group(1) != "null" else np.nan
        evaluation_date = (
            evaluation_date_match.group(1)
            if evaluation_date_match and evaluation_date_match.group(1) != "null"
            else np.nan
        )

        # Add the extracted data to the list
        table_data.append((method_short, top_1_accuracy, evaluation_date))

    # Convert the table data to a DataFrame
    df = pd.DataFrame(
        table_data,
        columns=[
            "name",
            "top_1_accuracy",
            "date",
        ],
    )

    df = df.replace('"', "", regex=True)
    df = df.replace("%", "", regex=True)

    return df
