"""Tool for fetching and processing GitHub pull request details and diffs."""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from github import Auth, Github
from langchain_core.tools import tool

# Load environment variables
load_dotenv()

# Add parent directory to path to import logger
current_file = Path(__file__).resolve()
workflow_dir = current_file.parent.parent
sys.path.insert(0, str(workflow_dir))
from utils.logger import get_logger

# Get project root directory (parent of WorkFlow)
PROJECT_ROOT = current_file.parent.parent.parent


def should_ignore_file(file_path: str, logger=None) -> bool:
    """Check if a file should be ignored based on common patterns."""
    if logger is None:
        logger = get_logger()

    ignore_patterns = [
        "node_modules",
        "__pycache__",
        ".pyc",
        ".pyo",
        ".pyd",
        ".env",
        ".env.local",
        ".env.production",
        "pyproject.toml",
        "package-lock.json",
        "yarn.lock",
        ".gitignore",
        ".DS_Store",
        "dist/",
        "build/",
        ".venv",
        "venv/",
        ".idea",
        ".vscode",
        "*.log",
        ".pytest_cache",
        ".mypy_cache",
        ".coverage",
        "htmlcov/",
    ]

    file_path_lower = file_path.lower()

    for pattern in ignore_patterns:
        if pattern in file_path_lower:
            logger.debug(f"File {file_path} ignored due to pattern: {pattern}")
            return True

    binary_extensions = [".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin"]
    if any(file_path_lower.endswith(ext) for ext in binary_extensions):
        logger.debug(f"File {file_path} ignored as binary file")
        return True

    return False


def parse_and_save_diff_files(
    diff_content: str, output_dir: str = "Output/diff_files", logger=None
) -> tuple[List[str], List[str], List[str]]:
    """Parse diff content and save each file's diff separately, maintaining folder structure.

    Returns:
        Tuple of (saved_file_paths, ignored_file_paths, saved_workspace_file_paths)
    """
    if logger is None:
        logger = get_logger()

    # Ensure output directory is in project root
    if not Path(output_dir).is_absolute():
        output_dir = str(PROJECT_ROOT / output_dir)

    logger.info(f"Starting to parse diff files. Output directory: {output_dir}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    file_diffs = re.split(r"(?=^diff --git)", diff_content, flags=re.MULTILINE)
    saved_files = []
    ignored_files = []
    saved_workspace_files = []

    for file_diff in file_diffs:
        if not file_diff.strip():
            continue

        match = re.search(r"^diff --git a/(.+?) b/(.+?)$", file_diff, re.MULTILINE)
        if not match:
            continue

        file_path = match.group(2)

        if should_ignore_file(file_path, logger):
            ignored_files.append(file_path)
            continue

        file_path_obj = Path(file_path)
        directory = file_path_obj.parent
        filename = file_path_obj.name

        full_dir_path = Path(output_dir) / directory
        full_dir_path.mkdir(parents=True, exist_ok=True)

        safe_filename = re.sub(r'[<>:"|?*]', "_", filename)
        output_file = full_dir_path / f"{safe_filename}.txt"

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(file_diff)
            saved_files.append(file_path)
            # Store the workspace file path relative to project root
            workspace_path = str(output_file.relative_to(PROJECT_ROOT))
            saved_workspace_files.append(workspace_path)
            logger.debug(f"Saved diff for file: {file_path} -> {output_file}")
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")

    logger.info(
        f"Saved {len(saved_files)} file diffs, ignored {len(ignored_files)} files"
    )
    return saved_files, ignored_files, saved_workspace_files


def get_file_structure(pr, logger=None) -> List[Dict[str, Any]]:
    """Get the file structure of changed files in the PR."""
    if logger is None:
        logger = get_logger()

    logger.info("Fetching file structure from PR")
    files = pr.get_files()
    file_list = []

    for file in files:
        hunks = 0
        if file.patch:
            hunks = len(re.findall(r"^@@", file.patch, re.MULTILINE))

        file_info = {
            "filename": file.filename,
            "status": file.status,
            "additions": file.additions,
            "deletions": file.deletions,
            "changes": file.changes,
            "hunks": hunks,
        }
        file_list.append(file_info)

    logger.info(f"Retrieved {len(file_list)} files from PR")
    return file_list


def format_file_structure(file_list: List[Dict[str, Any]]) -> List[str]:
    """Format file list into a structure similar to GitHub PR file listing."""
    if not file_list:
        return ["No files changed."]

    formatted = [
        "FILE STRUCTURE",
        "=" * 80,
        "",
        f"📒 Files selected for processing ({len(file_list)})",
        "",
    ]

    sorted_files = sorted(file_list, key=lambda x: x["filename"])
    for file_info in sorted_files:
        formatted.append(f"> * `{file_info['filename']}` ({file_info['hunks']} hunks)")

    formatted.extend(["", f"Total Files Changed: {len(file_list)}"])
    return formatted


def get_pr_details(pr, ignored_files: List[str] = None, logger=None) -> Dict[str, Any]:
    """Extract pull request details."""
    if logger is None:
        logger = get_logger()

    logger.info(f"Extracting PR details for PR #{pr.number}")
    file_list = get_file_structure(pr, logger)
    file_structure = format_file_structure(file_list)

    pr_details = {
        "Title": pr.title,
        "State": pr.state,
        "Description": pr.body if pr.body else "No description provided.",
        "FileStructure": file_structure,
        "Branch": f"{pr.head.ref} ({pr.head.sha[:7]})",
        "Number": pr.number,
        "URL": pr.html_url,
        "Additions": pr.additions,
        "Deletions": pr.deletions,
        "ChangedFiles": pr.changed_files,
        "Commits": pr.commits,
        "IgnoredFiles": ignored_files if ignored_files is not None else [],
    }

    logger.info(f"PR details extracted successfully for PR #{pr.number}")
    return pr_details


@tool
def get_pull_request(repo_link: str, pull_request_number: int) -> Dict[str, Any]:
    """
    Fetch GitHub pull request details, extract file diffs, and save them in organized folder structure.

    Args:
        repo_link: GitHub repository URL or identifier (e.g., 'owner/repo' or 'https://github.com/owner/repo')
        pull_request_number: Pull request number

    Returns:
        Dictionary containing PR details, saved files, ignored files, and statistics.
        The result includes:
        - pr_details: PR metadata (title, description, file structure, etc.)
        - saved_files: List of file paths that were saved
        - ignored_files: List of file paths that were ignored
        - total_files: Total number of files processed
        - saved_count: Number of files saved
        - ignored_count: Number of files ignored
    """
    logger = get_logger()
    logger.info(
        f"Starting PR fetch process for PR #{pull_request_number} from {repo_link}"
    )

    token = os.getenv("GIT_TOKEN")
    if not token:
        logger.error("GIT_TOKEN not found in environment variables")
        raise ValueError("GIT_TOKEN environment variable is required")

    g = Github(auth=Auth.Token(token))

    # Parse repository identifier
    if repo_link.startswith("http"):
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_link)
        if match:
            repo_identifier = f"{match.group(1)}/{match.group(2).rstrip('/')}"
        else:
            raise ValueError(f"Invalid GitHub URL format: {repo_link}")
    else:
        repo_identifier = repo_link.rstrip("/")

    # Fetch repository and pull request
    try:
        repo = g.get_repo(repo_identifier)
        pr = repo.get_pull(pull_request_number)
        logger.info(f"PR fetched successfully: {pr.title}")
    except Exception as e:
        logger.error(f"Error fetching PR: {e}")
        raise

    # Fetch diff
    diff_url = pr.diff_url
    header = {"Authorization": f"token {token}"}

    try:
        response = requests.get(diff_url, headers=header)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch diff: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching diff: {e}")
        raise

    # Parse and save individual file diffs
    saved_files, ignored_files, saved_workspace_files = parse_and_save_diff_files(
        response.text, logger=logger
    )

    # Get PR details
    pr_details = get_pr_details(pr, ignored_files=ignored_files, logger=logger)

    # Prepare result
    result = {
        "pr_details": pr_details,
        "saved_files": saved_files,
        "ignored_files": ignored_files,
        "SavedWorkspaceFiles": str(PROJECT_ROOT / "Output" / "diff_files"),
        "total_files": len(saved_files) + len(ignored_files),
        "saved_count": len(saved_files),
        "ignored_count": len(ignored_files),
    }

    logger.info(
        f"Process completed successfully. Total files: {result['total_files']}, Saved: {result['saved_count']}, Ignored: {result['ignored_count']}"
    )
    return result


# Export the tool (already decorated with @tool)
get_pull_request_tool = get_pull_request


# if __name__ == "__main__":
#     """Example usage of the get_pull_request tool."""
#     import json

#     # Example 1: Using the tool directly
#     print("=" * 80)
#     print("Example: Using get_pull_request_tool")
#     print("=" * 80)

#     # Replace with your actual repository and PR number
#     repo_url = "https://github.com/TheCoder30ec4/OneForAll-MCP/"
#     pr_number = 2

#     try:
#         # Invoke the tool
#         result = get_pull_request_tool.invoke({
#             "repo_link": repo_url,
#             "pull_request_number": pr_number
#         })

#         print(result)

#     except ValueError as e:
#         print(f"\n❌ Validation Error: {e}")
#     except Exception as e:
#         print(f"\n❌ Error: {e}")
#         import traceback
#         traceback.print_exc()

#     # # Example 2: Using the tool in a LangChain agent context
#     # print("\n" + "=" * 80)
#     # print("Example: Tool metadata and schema")
#     # print("=" * 80)
#     # print(f"Tool Name: {get_pull_request_tool.name}")
#     # print(f"Tool Description: {get_pull_request_tool.description}")
#     # print(f"\nTool Args Schema:")
#     # if hasattr(get_pull_request_tool, 'args_schema'):
#     #     print(json.dumps(get_pull_request_tool.args_schema.schema(), indent=2))
#     # print("=" * 80)
