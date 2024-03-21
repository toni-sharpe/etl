"""General utils.

TODO: Should probably re-order this file and split it into multiple files.
    - Ideally we want to leave front-end stuff here.
    - More backendy stuff should be moved to apps/utils.

    IF a tool here is used by something outside of Wizard domains, then we should place it elsewhere.
    At the moment, I'm moving things to apps/utils/. But I could see this going elsewhere under etl/.

    Also, can imagine apps/wizard/ being renamed to just wizard/, and stuff other than wizard should be either (i) deleted or (ii) migrated elsewhere in etl/.
"""
import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

import bugsnag
import streamlit as st
from MySQLdb import OperationalError
from owid.catalog import Dataset
from structlog import get_logger
from typing_extensions import Self

from apps.wizard.config import PAGES_BY_ALIAS
from apps.wizard.utils.defaults import load_wizard_defaults, update_wizard_defaults_from_form
from apps.wizard.utils.step_form import StepForm
from etl import config
from etl.db import get_connection
from etl.files import ruamel_dump, ruamel_load
from etl.metadata_export import main as metadata_export
from etl.paths import (
    APPS_DIR,
    DAG_DIR,
    LATEST_POPULATION_VERSION,
    LATEST_REGIONS_VERSION,
    STEPS_GARDEN_DIR,
    STEPS_GRAPHER_DIR,
    STEPS_MEADOW_DIR,
)
from etl.steps import load_dag

__all__ = [
    "load_wizard_defaults",
    "update_wizard_defaults_from_form",
    "StepForm",
]

# Logger
log = get_logger()

# Path to variable configs
DAG_WIZARD_PATH = DAG_DIR / "wizard.yml"

# Load latest dataset versions
DATASET_POPULATION_URI = f"data://garden/demography/{LATEST_POPULATION_VERSION}/population"
DATASET_REGIONS_URI = f"data://garden/regions/{LATEST_REGIONS_VERSION}/regions"

# DAG dropdown options
dag_files = sorted(os.listdir(DAG_DIR))
dag_not_add_option = "(do not add to DAG)"
ADD_DAG_OPTIONS = [dag_not_add_option] + dag_files

# Date today
DATE_TODAY = dt.date.today().strftime("%Y-%m-%d")

# Get current directory
CURRENT_DIR = Path(__file__).parent.parent

# Wizard path
WIZARD_DIR = APPS_DIR / "wizard"

# Paths to cookiecutter files
COOKIE_SNAPSHOT = WIZARD_DIR / "etl_steps" / "cookiecutter" / "snapshot"
COOKIE_MEADOW = WIZARD_DIR / "etl_steps" / "cookiecutter" / "meadow"
COOKIE_GARDEN = WIZARD_DIR / "etl_steps" / "cookiecutter" / "garden"
COOKIE_GRAPHER = WIZARD_DIR / "etl_steps" / "cookiecutter" / "grapher"
# Paths to markdown templates
MD_SNAPSHOT = WIZARD_DIR / "etl_steps" / "markdown" / "snapshot.md"
MD_MEADOW = WIZARD_DIR / "etl_steps" / "markdown" / "meadow.md"
MD_GARDEN = WIZARD_DIR / "etl_steps" / "markdown" / "garden.md"
MD_GRAPHER = WIZARD_DIR / "etl_steps" / "markdown" / "grapher.md"

# Dummy data
DUMMY_DATA = {
    "namespace": "dummy",
    "short_name": "dummy",
    "version": "2020-01-01",
    "snapshot_version": "2020-01-01",
    "title": "Data product title",
    "description": "This\nis\na\ndummy\ndataset",
    "file_extension": "csv",
    "date_published": "2020-01-01",
    "producer": "Dummy producer",
    "citation_full": "Dummy producer citation",
    "url_download": "https://raw.githubusercontent.com/owid/etl/master/apps/wizard/dummy_data.csv",
    "url_main": "https://www.url-dummy.com/",
    "license_name": "MIT dummy license",
}


def get_namespaces(step_type: str) -> List[str]:
    """Get list with namespaces.

    Looks for namespaces in `etl/steps/data/<step_type>/`.
    """
    match step_type:
        case "meadow":
            folders = sorted(item for item in STEPS_MEADOW_DIR.iterdir() if item.is_dir())
        case "garden":
            folders = sorted(item for item in STEPS_GARDEN_DIR.iterdir() if item.is_dir())
        case "grapher":
            folders = sorted(item for item in STEPS_GRAPHER_DIR.iterdir() if item.is_dir())
        case _:
            raise ValueError(f"Step {step_type} not in ['meadow', 'garden', 'grapher'].")
    namespaces = [folder.name for folder in folders]
    return namespaces


def remove_from_dag(step: str, dag_path: Path = DAG_WIZARD_PATH) -> None:
    with open(dag_path, "r") as f:
        doc = ruamel_load(f)

    doc["steps"].pop(step, None)

    with open(dag_path, "w") as f:
        # Add new step to DAG
        f.write(ruamel_dump(doc))


class classproperty(property):
    """Decorator."""

    def __get__(self, owner_self: Self, owner_cls: Self):
        return self.fget(owner_cls)  # type: ignore


class AppState:
    """Management of state variables shared across different apps."""

    steps: List[str] = ["snapshot", "meadow", "garden", "grapher", "explorers"]
    dataset_edit: Dict[str, Dataset | None] = {
        "snapshot": None,
        "meadow": None,
        "garden": None,
        "grapher": None,
    }

    def __init__(self: "AppState") -> None:
        """Construct variable."""
        self.step = st.session_state["step_name"]
        self._init_steps()

    def _init_steps(self: "AppState") -> None:
        # Initiate dictionary
        if "steps" not in st.session_state:
            st.session_state["steps"] = {}
        for step in self.steps:
            if step not in st.session_state["steps"]:
                st.session_state["steps"][step] = {}
        # Initiate default
        self.default_steps = {step: {} for step in self.steps}

        # Load config from .wizard
        defaults = load_wizard_defaults()
        # Add defaults (these are used when not value is found in current or previous step)
        self.default_steps["snapshot"]["snapshot_version"] = DATE_TODAY
        self.default_steps["snapshot"]["origin.date_accessed"] = DATE_TODAY

        self.default_steps["meadow"]["version"] = DATE_TODAY
        self.default_steps["meadow"]["snapshot_version"] = DATE_TODAY
        self.default_steps["meadow"]["generate_notebook"] = defaults["template"]["meadow"]["generate_notebook"]

        self.default_steps["garden"]["version"] = DATE_TODAY
        self.default_steps["garden"]["meadow_version"] = DATE_TODAY
        self.default_steps["garden"]["generate_notebook"] = defaults["template"]["garden"]["generate_notebook"]

        self.default_steps["grapher"]["version"] = DATE_TODAY
        self.default_steps["grapher"]["garden_version"] = DATE_TODAY

    def _check_step(self: "AppState") -> None:
        """Check that the value for step is valid."""
        if self.step is None or self.step not in self.steps:
            raise ValueError(f"Step {self.step} not in {self.steps}.")

    def reset_dataset_to_edit(self: "AppState") -> None:
        """Set dataset to edit."""
        self.dataset_edit[self.step] = None

    def set_dataset_to_edit(self: "AppState", ds: Dataset) -> None:
        """Set dataset to edit."""
        self.dataset_edit[self.step] = ds

    def get_variables_of_step(self: "AppState") -> Dict[str, Any]:
        """Get variables of a specific step.

        Variables are assumed to have keys `step.NAME`, based on the keys given in the widgets within a form.
        """
        return {
            cast(str, k): v for k, v in st.session_state.items() if isinstance(k, str) and k.startswith(f"{self.step}.")
        }

    def update(self: "AppState") -> None:
        """Update global variables of step.

        This is expected to be called when submitting the step's form.
        """
        self._check_step()
        print(f"Updating {self.step}...")
        st.session_state["steps"][self.step] = self.get_variables_of_step()

    def update_from_form(self, form: "StepForm") -> None:
        self._check_step()
        st.session_state["steps"][self.step] = form.dict()

    @property
    def state_step(self: "AppState") -> Dict[str, Any]:
        """Get state variables of step."""
        self._check_step()
        return st.session_state["steps"][self.step]

    def default_value(
        self: "AppState", key: str, previous_step: Optional[str] = None, default_last: Optional[str | bool | int] = ""
    ) -> str | bool | int:
        """Get the default value of a variable.

        This is useful when setting good defaults in widgets (e.g. text_input).

        Priority of default value is:
            - Check if there is a value stored for this field in the current step.
            - If not, check if there is a value stored for this field in the previous step.
            - If not, use value given by `default_last`.
        """
        self._check_step()
        # Get name of previous step
        if previous_step is None:
            previous_step = self.previous_step
        # (1) Get value stored for this field (in current step)
        # st.write(f"KEY: {key}")
        value_step = self.state_step.get(key)
        # st.write(f"value_step: {value_step}")
        if value_step is not None:
            return value_step
        # (2) If none, check if previous step has a value and use that one, otherwise (3) use empty string.
        key = key.replace(f"{self.step}.", f"{self.previous_step}.")
        value_previous_step = st.session_state["steps"][self.previous_step].get(key)
        # st.write(f"value_previous_step: {value_previous_step}")
        if value_previous_step is not None:
            return value_previous_step
        # (3) If none, use self.default_steps
        value_defaults = self.default_steps[self.step].get(key)
        # st.write(f"value_defaults: {value_defaults}")
        if value_defaults is not None:
            return value_defaults
        # (4) Use default_last as last resource
        if default_last is None:
            raise ValueError(
                f"No value found for {key} in current, previous or defaults. Must provide a valid `default_value`!"
            )
        return cast(str | bool | int, default_last)

    def display_error(self: "AppState", key: str) -> None:
        """Get error message for a given key."""
        if "errors" in self.state_step:
            # print("KEY:", key)
            if msg := self.state_step.get("errors", {}).get(key, ""):
                # print(msg)
                st.error(msg)

    @property
    def previous_step(self: "AppState") -> str:
        """Get the name of the previous step.

        E.g. 'snapshot' is the step prior to 'meadow', etc.
        """
        self._check_step()
        idx = max(self.steps.index(self.step) - 1, 0)
        return self.steps[idx]

    def st_widget(
        self: "AppState",
        st_widget: Callable,
        default_last: Optional[str | bool | int] = "",
        dataset_field_name: Optional[str] = None,
        **kwargs: Optional[str | int | List[str]],
    ) -> None:
        """Wrap a streamlit widget with a default value."""
        key = cast(str, kwargs["key"])
        # Get default value (either from previous edits, or from previous steps)
        if self.dataset_edit[self.step] is not None:
            if dataset_field_name:
                default_value = getattr(self.dataset_edit[self.step], dataset_field_name, "")
            else:
                default_value = getattr(self.dataset_edit[self.step].metadata, key, "")  # type: ignore
        else:
            default_value = self.default_value(key, default_last=default_last)
        # Change key name, to be stored it in general st.session_state
        kwargs["key"] = f"{self.step}.{key}"
        # Special behaviour for multiselect
        if "multiselect" not in str(st_widget):
            # Default value for selectbox (and other widgets with selectbox-like behavior)
            if "options" in kwargs:
                options = cast(List[str], kwargs["options"])
                index = options.index(default_value) if default_value in options else 0  # type: ignore
                kwargs["index"] = index
            # Default value for other widgets (if none is given)
            elif (
                ("value" not in kwargs)
                or ("value" in kwargs and kwargs.get("value") is None)
                or self.dataset_edit[self.step]
            ):
                kwargs["value"] = default_value
        elif "default" not in kwargs:
            kwargs["default"] = default_value
        # Create widget
        widget = st_widget(**kwargs)
        # Show error message
        self.display_error(key)
        return widget

    @classproperty
    def args(cls: "AppState") -> argparse.Namespace:
        """Get arguments passed from command line."""
        if "args" in st.session_state:
            return st.session_state["args"]
        else:
            parser = argparse.ArgumentParser()
            parser.add_argument("--phase")
            parser.add_argument("--run-checks", action="store_true")
            parser.add_argument("--dummy-data", action="store_true")
            args = parser.parse_args()
            st.session_state["args"] = args
        return st.session_state["args"]


def extract(error_message: str) -> List[Any]:
    """Get field name that caused the error."""
    rex = r"'(.*)' is a required property"
    return re.findall(rex, error_message)[0]


def config_style_html() -> None:
    st.markdown(
        """
    <style>
    .streamlit-expanderHeader {
        font-size: x-large;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )


def preview_file(file_path: str | Path, language: str = "python") -> None:
    """Preview file in streamlit."""
    with open(file_path, "r") as f:
        code = f.read()
    with st.expander(f"File: `{file_path}`", expanded=False):
        st.code(code, language=language)


def preview_dag_additions(dag_content: str, dag_path: str | Path) -> None:
    """Preview DAG additions."""
    if dag_content:
        with st.expander(f"File: `{dag_path}`", expanded=False):
            st.code(dag_content, "yaml")


@st.cache_data
def load_instructions() -> str:
    """Load snapshot step instruction text."""
    with open(CURRENT_DIR / f"{st.session_state['step_name']}.md", "r") as f:
        return f.read()


def _check_env() -> bool:
    """Check if environment variables are set correctly."""
    ok = True
    for env_name in ("GRAPHER_USER_ID", "DB_USER", "DB_NAME", "DB_HOST"):
        if getattr(config, env_name) is None:
            ok = False
            st.warning(f"Environment variable `{env_name}` not found, do you have it in your `.env` file?")

    if ok:
        st.success(("`.env` configured correctly"))
    return ok


def _check_db() -> bool:
    try:
        with st.spinner():
            _ = get_connection()
    except OperationalError as e:
        st.error(
            "We could not connect to the database. If connecting to a remote database, remember to"
            f" ssh-tunel into it using the appropriate ports and then try again.\n\nError:\n{e}"
        )
        return False
    except Exception as e:
        raise e
    st.success("Connection to the Grapher database was successfull!")
    return True


def _show_environment():
    """Show environment variables."""
    st.info(
        f"""
    **Environment variables**:

    ```
    GRAPHER_USER_ID: {config.GRAPHER_USER_ID}
    DB_USER: {config.DB_USER}
    DB_NAME: {config.DB_NAME}
    DB_HOST: {config.DB_HOST}
    ```
    """
    )


def clean_empty_dict(d: Dict[str, Any]) -> Dict[str, Any] | List[Any]:
    """Remove empty values from dict.

    REference: https://stackoverflow.com/a/27974027/5056599
    """
    if isinstance(d, dict):
        return {k: v for k, v in ((k, clean_empty_dict(v)) for k, v in d.items()) if v}
    if isinstance(d, list):
        return [v for v in map(clean_empty_dict, d) if v]
    return d


def warning_metadata_unstable() -> None:
    """Show warning on latest metadata definitions being available in Notion."""
    st.warning(
        "Documentation for new metadata is almost complete, but still being finalised based on feedback. Feel free to open a [new issue](https://github.com/owid/etl/issues/new) for any question of suggestion!"
    )


def render_responsive_field_in_form(
    key: str,
    display_name: str,
    field_1: Any,
    field_2: Any,
    options: List[str],
    custom_label: str,
    help_text: str,
    app_state: Any,
    default_value: str,
) -> None:
    """Render the namespace field within the form.

    We want the namespace field to be a selectbox, but with the option to add a custom namespace.

    This is a workaround to have repsonsive behaviour within a form.

    Source: https://discuss.streamlit.io/t/can-i-add-to-a-selectbox-an-other-option-where-the-user-can-add-his-own-answer/28525/5
    """
    # Main decription
    help_text = "## Description\n\nInstitution or topic name"

    # Render and get element depending on selection in selectbox
    with field_1:
        field = app_state.st_widget(
            st.selectbox,
            label=display_name,
            options=[custom_label] + options,
            help=help_text,
            key=key,
            default_last=default_value,  # dummy_values[prop_uri],
        )
    with field_2:
        if field == custom_label:
            default_value = app_state.default_value(key)
            field = app_state.st_widget(
                st.text_input,
                label="↳ *Use custom value*",
                placeholder="",
                help="Enter custom value.",
                key=f"{key}_custom",
                default_last=default_value,
            )


def get_datasets_in_etl(
    dag: Dict[str, Any] | None = None,
    snapshots: bool = False,
    prefixes: List[str] | None = None,
    prefix_priorities: List[str] | None = None,
) -> Any:
    """Show a selectbox with all datasets available."""
    # Load dag
    if dag is None:
        dag = load_dag()

    # Define list with options
    options = sorted(list(dag.keys()))
    ## Optional: Show some options first based on their prefix. E.g. Show those that are Meadow (i.e. start with 'data://meadow') first.
    if prefix_priorities:
        options, options_left = [], options
        for prefix in prefix_priorities:
            options_ = [o for o in options_left if o.startswith(f"{prefix}/")]
            options.extend(sorted(options_))
            options_left = [o for o in options_left if o not in options_]
        options.extend(options_left)

    # Show only datasets that start with a given prefix
    if prefixes:
        options = [o for o in options if any(o.startswith(prefix) for prefix in prefixes)]
    # Discard snapshots if flag is enabled
    if not snapshots:
        options = [o for o in options if not o.startswith("snapshot://")]

    return options


def set_states(states_values: Dict[str, Any], logging: bool = False) -> None:
    """Set states from any key in dictionary.

    Set logging to true to log the state changes
    """
    for key, value in states_values.items():
        if logging and (st.session_state[key] != value):
            print(f"{key}: {st.session_state[key]} -> {value}")
        st.session_state[key] = value


def st_page_link(alias: str, border: bool = False, **kwargs) -> None:
    """Link to page."""
    if border:
        with st.container(border=True):
            st.page_link(
                page=PAGES_BY_ALIAS[alias]["entrypoint"],
                label=PAGES_BY_ALIAS[alias]["title"],
                icon=PAGES_BY_ALIAS[alias]["emoji"],
                **kwargs,
            )
    else:
        st.page_link(
            page=PAGES_BY_ALIAS[alias]["entrypoint"],
            label=PAGES_BY_ALIAS[alias]["title"],
            icon=PAGES_BY_ALIAS[alias]["emoji"],
            **kwargs,
        )


st.cache_data


def metadata_export_basic(dataset_path: str | None = None, dataset: Dataset | None = None, output: str = "") -> str:
    """Export metadata of a dataset.

    The metadata of the dataset may have changed in run time.
    """
    # Handle inputs
    if dataset:
        dataset_path = str(dataset.path)
    elif dataset_path is None:
        raise ValueError("Either a dataset or a dataset_path must be provided.")

    output_path = metadata_export(
        path=dataset_path,
        output=output,  # Will assign the default value
        show=False,
        decimals="auto",
    )
    return output_path


def enable_bugsnag_for_streamlit():
    """Enable bugsnag for streamlit. Uses this workaround
    https://github.com/streamlit/streamlit/issues/3426#issuecomment-1848429254
    """
    config.enable_bugsnag()
    # error_util = sys.modules["streamlit.error_util"]
    error_util = sys.modules["streamlit.runtime.scriptrunner.script_runner"]
    original_handler = error_util.handle_uncaught_app_exception

    def bugsnag_handler(exception: Exception) -> None:
        """Pass the provided exception through to bugsnag."""
        bugsnag.notify(exception)
        return original_handler(exception)

    error_util.handle_uncaught_app_exception = bugsnag_handler  # type: ignore
