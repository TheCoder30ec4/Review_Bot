from typing import List, Tuple

from pydantic import BaseModel, Field


class ParseState(BaseModel):
    """State for parsing and selecting files from the workspace."""

    RootWorkSpace: str = Field(
        description="The root workspace path where diff files are stored. This should be the directory path containing all the diff files (e.g., 'Output/diff_files' or full absolute path).",
        examples=[
            "Output/diff_files",
            "/home/user/project/Output/diff_files",
            "Output/diff_files/",
        ],
    )
    SelectedFilePath: List[str] = Field(
        description="List of file paths that have been selected for review. Each entry should be a relative file path from the repository root. These are the files that will be processed and reviewed.",
        examples=[
            ["Backend/app/main.py", "Backend/app/api.py", "Frontend/src/App.tsx"],
            ["src/utils/helper.py", "src/components/Button.tsx"],
        ],
        default_factory=list,
    )
    SkippedFiles: List[Tuple[str, str]] = Field(
        description="List of tuples containing file paths and reasons for skipping them. Each tuple is (file_path, reason). Files that were decided to skip during parsing should be listed here with their skip reason.",
        examples=[
            [
                ("test.py", "Test file - not part of production code"),
                ("config.py", "Configuration file - no logic changes"),
            ],
            [("README.md", "Documentation file"), ("package.json", "Dependency file")],
        ],
        default_factory=list,
    )
