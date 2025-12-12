from typing import List, Literal

from pydantic import BaseModel, Field


class PrRequestState(BaseModel):
    """Pull request request state containing PR metadata."""

    Title: str = Field(
        description="The title of the pull request. This is the PR title as shown on GitHub.",
        examples=[
            "Add authentication feature",
            "Fix bug in API endpoint",
            "Update dependencies",
        ],
    )
    State: Literal["close", "open"] = Field(
        description="The current state of the pull request. Must be either 'open' or 'close'.",
        examples=["open", "close"],
    )
    Description: str = Field(
        description="The description or body of the pull request. This contains the PR description provided by the author when creating the PR. Can be empty if no description was provided.",
        examples=[
            "This PR adds user authentication functionality",
            "Fixes the bug where API returns 500 error",
            "",
        ],
    )
    FileStructure: List[str] = Field(
        description="List of strings representing the file structure of changed files in the PR. Each string typically represents a file path or a formatted line showing file information (e.g., '> * `path/to/file.py` (5 hunks)'). This should match the format from the PR file structure.",
        examples=[
            [
                "FILE STRUCTURE",
                "=" * 80,
                "",
                "📒 Files selected for processing (10)",
                "",
                "> * `Backend/app/main.py` (3 hunks)",
                "> * `Frontend/src/App.tsx` (2 hunks)",
            ],
            ["> * `src/utils/helper.py` (1 hunks)"],
        ],
        default_factory=list,
    )
    Branch: str = Field(
        description="The branch name and commit SHA of the pull request. Format: 'branch_name (sha7chars)' or just the branch name.",
        examples=["main (a1b2c3d)", "feature/auth (e4f5g6h)", "develop"],
    )


class FetchState(BaseModel):
    """State for fetching pull request information."""

    WorkSpacePath: str = Field(
        description="The workspace path where the diff files are stored. This should be the directory path where the PR diff files have been saved (e.g., 'Output/diff_files' or full absolute path).",
        examples=[
            "Output/diff_files",
            "/home/user/project/Output/diff_files",
            "Output/diff_files/",
        ],
    )
    PrRequest: PrRequestState = Field(
        description="The pull request request state containing PR metadata including title, state, description, file structure, and branch information."
    )
