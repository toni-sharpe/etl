"""This script creates a new draft pull request in GitHub, which starts a new staging server.

Usage:
- If you have already created a new local branch, run this script without specifying any argument.
  The 'master' branch will be assumed as the base branch of the new draft pull request.
- If you are in the master branch on your local ETL repo, specify a --new-branch argument.
  This will create a new local branch, which will be pushed to remote to create a new draft pull request.
- If you want the base branch to be different from 'master', specify it with the --base-branch argument.

The resulting draft pull request will be new_branch -> base_branch.

"""

from typing import Optional

import click
import requests
from git import GitCommandError, Repo
from rich_click.rich_command import RichCommand
from structlog import get_logger

from etl.config import GITHUB_TOKEN
from etl.paths import BASE_DIR

# Initialize logger.
log = get_logger()

# URL of the Github API, to be used to create a draft pull request in the ETL repos.
GITHUB_API_URL = "https://api.github.com/repos/owid/etl/pulls"


@click.command(name="draft-pr", cls=RichCommand, help=__doc__)
@click.option(
    "--new-branch",
    type=str,
    default=None,
    help="Name of new branch to create (if not given, current branch will be used).",
)
@click.option(
    "--base-branch", type=str, default=None, help="Name of base branch (if not given, 'master' will be used)."
)
def cli(new_branch: Optional[str] = None, base_branch: Optional[str] = None) -> None:
    if not GITHUB_TOKEN:
        log.error(
            """A github token is needed. To create one:
- Go to: https://github.com/settings/tokens
- Click on the dropdown "Generate new token" and select "Generate new token (classic)".
- Give the token a name (e.g., "etl-work"), set an expiration time, and select the scope "repo".
- Click on "Generate token".
- Copy the token and save it in your .env file as GITHUB_TOKEN.
- Run this tool again.
"""
        )
        return

    # Initialize a repos object at the root folder of the etl repos.
    repo = Repo(BASE_DIR)

    # List all local branches.
    local_branches = [branch.name for branch in repo.branches]

    # Update the list of remote branches in the local repository.
    origin = repo.remote(name="origin")
    origin.fetch()
    # List all remote branches.
    remote_branches = [ref.name.split("origin/")[-1] for ref in origin.refs if ref.remote_head != "HEAD"]

    if base_branch is None:
        # If a base branch is not specified, assume that it will be 'master'.
        base_branch = "master"

    # Ensure the base branch exists in remote (this should always be true for 'master').
    if base_branch not in remote_branches:
        log.error(
            f"Base branch '{base_branch}' does not exist in remote. "
            "Either push that branch (git push origin base-branch-name) or use 'master' as a base branch. "
            "Then run this tool again."
        )
        return

    if new_branch is None:
        # If not explicitly given, the new branch will be the current branch.
        new_branch = repo.active_branch.name
        if new_branch == "master":
            log.error("You're currently on 'master' branch. Use '--new-branch ...' to create a new branch.")
            return
    else:
        # Ensure the new branch does not already exist locally.
        if new_branch in local_branches:
            log.error(
                f"Branch '{new_branch}' already exists locally."
                "Either choose a different name for the new branch to be created, "
                "or switch to the new branch and run this tool without specifying a new branch."
            )
            return
        try:
            log.info(f"Switch to base branch '{base_branch}', create a new branch from there, and switch to it.")
            repo.git.checkout(base_branch)
            repo.git.checkout("-b", new_branch)
        except GitCommandError as e:
            log.error(f"Failed to create a new branch from '{base_branch}':\n{e}")
            return

    # Ensure the new branch does not already exist in remote.
    if new_branch in remote_branches:
        log.error(
            f"New branch '{new_branch}' already exists in remote. "
            "Either manually create a pull request from github, or use a different name for the new branch."
        )
        return

    log.info("Creating an empty commit.")
    repo.git.commit("--allow-empty", "-m", "Start a new staging server")

    log.info("Pushing the new branch to remote.")
    repo.git.push("origin", new_branch)

    log.info("Creating a draft pull request.")
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    data = {
        "title": f":construction: Draft PR for branch {new_branch}",
        "head": new_branch,
        "base": base_branch,
        "body": "",
        "draft": True,
    }
    response = requests.post(GITHUB_API_URL, json=data, headers=headers)
    if response.status_code == 201:
        log.info("Draft pull request created successfully.")
    else:
        log.error(f"Failed to create draft pull request:\n{response.json()}")
