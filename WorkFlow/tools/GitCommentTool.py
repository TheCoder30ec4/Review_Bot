"""Tool for posting code review comments to GitHub pull requests."""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Literal, Optional

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

# Impact levels
ImpactLevel = Literal["OK", "Medium", "Critical"]


def format_comment(
    code_snippet: str,
    comment: str,
    impact: ImpactLevel,
    current_code: str = None,
    suggested_code: str = None,
    file_path: str = None,
) -> str:
    """
    Format a code review comment with impact level indicator and before/after code.

    Args:
        code_snippet: The code that needs to be changed (for backward compatibility)
        comment: Comment explaining what needs to be changed
        impact: Impact level (OK | Medium | Critical)
        current_code: The current/existing code that has the issue (optional)
        suggested_code: The suggested improved code (optional)
        file_path: Path to the file being reviewed (optional, for AI prompt)

    Returns:
        Formatted comment string with impact indicator and before/after code
    """
    # Impact level emojis and formatting
    impact_config = {
        "OK": {"emoji": "ℹ️", "label": "**Impact: OK**", "color": "blue"},
        "Medium": {"emoji": "⚠️", "label": "**Impact: Medium**", "color": "yellow"},
        "Critical": {"emoji": "🚨", "label": "**Impact: Critical**", "color": "red"},
    }

    config = impact_config.get(impact, impact_config["OK"])

    # Format the comment with before/after if available
    if current_code and suggested_code:
        formatted_comment = f"""{config["emoji"]} {config["label"]}

**Issue:**
{comment}

### 📝 Current Code (needs improvement):
```python
{current_code}
```

### ✅ Suggested Code (improved version):
```python
{suggested_code}
```

---

---

### 🤖 AI Implementation Prompt

**Copy and paste this prompt to your AI assistant (Claude, Cursor, ChatGPT, etc.) to implement automatically:**

```
Please implement the following code change in my codebase:

File: `{file_path if file_path else '[file path]'}`

Find and replace this code:
```
{current_code}
```

With this improved code:
```
{suggested_code}
```

Instructions:
1. Open the file `{file_path if file_path else '[file path]'}`
2. Locate the exact code block shown above
3. Replace it with the improved version
4. Preserve all indentation and formatting
5. Verify the change is correct in context
6. Save the file
```
"""
    else:
        # Fallback to old format if current/suggested code not provided
        formatted_comment = f"""{config["emoji"]} {config["label"]}

**Code Snippet:**
```
{code_snippet}
```

**Comment:**
{comment}
"""

    return formatted_comment


@tool
def post_code_review_comment(
    repo_link: str,
    pull_request_number: int,
    file_path: str,
    code_snippet: str,
    comment: str,
    impact: ImpactLevel,
    line_number: Optional[int] = None,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    side: Literal["LEFT", "RIGHT"] = "RIGHT",
    current_code: Optional[str] = None,
    suggested_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Post a code review comment on a GitHub pull request with before/after code.

    This tool posts comments on specific lines or code sections in a GitHub PR,
    with impact level indicators (OK | Medium | Critical) and shows current vs suggested code.

    Args:
        repo_link: GitHub repository URL or identifier (e.g., 'owner/repo' or 'https://github.com/owner/repo')
        pull_request_number: Pull request number
        file_path: Path to the file being commented on (relative to repo root)
        code_snippet: The code that needs to be changed (will be included in comment)
        comment: Comment explaining what needs to be changed and why
        impact: Impact level - "OK" (minor), "Medium" (moderate), or "Critical" (severe)
        line_number: Single line number for single-line comment (mutually exclusive with start_line/end_line)
        current_code: The existing code that has the issue (optional, for before/after comparison)
        suggested_code: The improved code to replace current_code (optional, for before/after comparison)
        start_line: Start line number for multi-line comment (requires end_line)
        end_line: End line number for multi-line comment (requires start_line)
        side: Which side of the diff to comment on - "LEFT" (old) or "RIGHT" (new). Default: "RIGHT"

    Returns:
        Dictionary containing:
        - success: bool indicating if comment was posted successfully
        - comment_id: GitHub comment ID (if successful)
        - comment_url: URL to the comment (if successful)
        - error: Error message (if unsuccessful)
        - impact: The impact level that was used

    Raises:
        ValueError: If parameters are invalid or missing
        Exception: If GitHub API call fails

    Example:
        >>> result = post_code_review_comment.invoke({
        ...     "repo_link": "owner/repo",
        ...     "pull_request_number": 123,
        ...     "file_path": "src/main.py",
        ...     "code_snippet": "def func(): pass",
        ...     "comment": "This function needs error handling",
        ...     "impact": "Critical",
        ...     "line_number": 42
        ... })
    """
    logger = get_logger()
    logger.info(
        f"post_code_review_comment tool invoked - PR #{pull_request_number}, file: {file_path}, impact: {impact}"
    )

    # Validate inputs
    if not repo_link or not repo_link.strip():
        error_msg = "Repository link cannot be empty"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if not file_path or not file_path.strip():
        error_msg = "File path cannot be empty"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if not code_snippet or not code_snippet.strip():
        error_msg = "Code snippet cannot be empty"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if not comment or not comment.strip():
        error_msg = "Comment cannot be empty"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if impact not in ["OK", "Medium", "Critical"]:
        error_msg = (
            f"Invalid impact level: {impact}. Must be one of: OK, Medium, Critical"
        )
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    # Validate line number parameters
    if line_number is not None and (start_line is not None or end_line is not None):
        error_msg = "Cannot specify both line_number and start_line/end_line"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if (start_line is not None) != (end_line is not None):
        error_msg = "Both start_line and end_line must be provided together"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    if line_number is None and start_line is None:
        error_msg = "Must specify either line_number or both start_line and end_line"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(
        f"Input validation passed - repo: {repo_link}, PR: {pull_request_number}, file: {file_path}"
    )

    # Get GitHub token
    token = os.getenv("GIT_WRITE_TOKEN")
    if not token:
        # Fallback to GIT_TOKEN if GIT_WRITE_TOKEN is not set
        token = os.getenv("GIT_TOKEN")
        if token:
            logger.warning(
                "Using GIT_TOKEN instead of GIT_WRITE_TOKEN. Consider using GIT_WRITE_TOKEN for write operations."
            )

    if not token:
        error_msg = "GIT_WRITE_TOKEN or GIT_TOKEN not found in environment variables"
        logger.error(error_msg)
        raise ValueError(
            "GIT_WRITE_TOKEN or GIT_TOKEN environment variable is required"
        )

    logger.debug("GitHub token retrieved successfully")

    # Initialize GitHub client
    try:
        g = Github(auth=Auth.Token(token))
        logger.debug("GitHub client initialized")
    except Exception as e:
        error_msg = f"Failed to initialize GitHub client: {e}"
        logger.error(error_msg)
        raise

    # Parse repository identifier
    logger.debug(f"Parsing repository identifier from: {repo_link}")
    if repo_link.startswith("http"):
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_link)
        if match:
            repo_identifier = f"{match.group(1)}/{match.group(2).rstrip('/')}"
        else:
            error_msg = f"Invalid GitHub URL format: {repo_link}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    else:
        repo_identifier = repo_link.rstrip("/")

    logger.debug(f"Repository identifier: {repo_identifier}")

    # Get repository and pull request
    try:
        logger.info(f"Fetching repository: {repo_identifier}")
        repo = g.get_repo(repo_identifier)
        logger.debug(f"Repository fetched: {repo.full_name}")

        logger.info(f"Fetching pull request #{pull_request_number}")
        pr = repo.get_pull(pull_request_number)
        logger.debug(f"Pull request fetched: {pr.title}")
    except Exception as e:
        error_msg = f"Error fetching repository or PR: {e}"
        logger.error(error_msg, exc_info=True)
        raise

    # Format the comment with before/after code if available
    logger.debug(f"Formatting comment with impact level: {impact}")
    formatted_comment = format_comment(
        code_snippet, comment, impact, current_code, suggested_code, file_path
    )
    logger.debug(
        f"Comment formatted successfully ({len(formatted_comment)} characters)"
    )

    # Determine line numbers for the comment
    if line_number is not None:
        comment_line = line_number
        comment_start_line = None
        comment_end_line = None
        logger.debug(f"Single-line comment on line {line_number}")
    else:
        comment_line = None
        comment_start_line = start_line
        comment_end_line = end_line
        logger.debug(f"Multi-line comment from line {start_line} to {end_line}")

    # Post the comment using GitHub REST API directly
    try:
        logger.info(f"Posting comment on file: {file_path}")
        logger.debug(
            f"Comment details - Line: {comment_line or f'{comment_start_line}-{comment_end_line}'}, Side: {side}"
        )

        # Get the commit SHA for the PR head
        commit_sha = pr.head.sha
        logger.debug(f"Using commit SHA: {commit_sha}")

        # Calculate position from diff for line-specific comments
        # GitHub API requires 'position' (line number in unified diff) not 'line' (file line number)
        position = None
        use_review_comment = False
        actual_file_path = file_path  # Track the actual file path that exists in PR
        target_file = None  # Initialize outside try block

        try:
            # Get the file from PR to access its patch/diff
            # Also verify the file exists and get the correct path
            pr_files = pr.get_files()

            # Try exact match first
            for file in pr_files:
                if file.filename == file_path:
                    target_file = file
                    actual_file_path = file.filename
                    break

            # If exact match fails, try case-insensitive or partial match
            if not target_file:
                logger.debug(
                    f"Exact match failed for '{file_path}', trying case-insensitive match..."
                )
                for file in pr_files:
                    if file.filename.lower() == file_path.lower():
                        target_file = file
                        actual_file_path = file.filename
                        logger.info(
                            f"Found file with case-insensitive match: {file.filename}"
                        )
                        break

            # If still not found, try matching just the filename
            if not target_file:
                logger.debug(
                    "Case-insensitive match failed, trying filename-only match..."
                )
                file_path_basename = Path(file_path).name
                for file in pr_files:
                    if Path(file.filename).name == file_path_basename:
                        target_file = file
                        actual_file_path = file.filename
                        logger.info(
                            f"Found file with filename match: {file.filename} (requested: {file_path})"
                        )
                        break

            # Log available files if still not found
            if not target_file:
                available_files = [f.filename for f in pr_files]
                logger.warning(
                    f"File '{file_path}' not found in PR. Available files: {available_files[:10]}..."
                )

            if target_file and target_file.patch:
                target_line_num = (
                    comment_line if comment_line is not None else comment_end_line
                )

                if target_line_num:
                    # Parse diff to find position
                    # Position is the line number in the unified diff where the comment should be placed
                    patch_lines = target_file.patch.split("\n")
                    current_position = 0
                    new_line_counter = 0

                    for i, patch_line in enumerate(patch_lines):
                        current_position += 1

                        # Check for hunk header
                        hunk_match = re.search(
                            r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", patch_line
                        )
                        if hunk_match:
                            new_start = int(hunk_match.group(2))
                            new_line_counter = (
                                new_start - 1
                            )  # Reset counter for new hunk

                        # Count new lines (for RIGHT side) or old lines (for LEFT side)
                        if patch_line.startswith("+") and side.upper() == "RIGHT":
                            new_line_counter += 1
                            if new_line_counter == target_line_num:
                                position = current_position
                                use_review_comment = True
                                break
                        elif patch_line.startswith("-") and side.upper() == "LEFT":
                            # For LEFT side, we'd need to track old line numbers
                            # Simplified: use position approximation
                            if i > 0:  # Skip first line (usually diff header)
                                position = current_position
                                use_review_comment = True
                                break
                        elif patch_line.startswith(" ") and not patch_line.startswith(
                            "@@"
                        ):
                            # Context lines - increment both counters
                            new_line_counter += 1
                            if (
                                side.upper() == "RIGHT"
                                and new_line_counter == target_line_num
                            ):
                                position = current_position
                                use_review_comment = True
                                break

                    # Fallback: if exact position not found, use approximation
                    if not use_review_comment and target_line_num:
                        # Use a simple approximation - this may not be perfect
                        position = target_line_num + 10  # Add offset for diff headers
                        use_review_comment = True
                        logger.warning(
                            f"Using approximate position {position} for line {target_line_num}"
                        )

                logger.debug(f"Calculated position from diff: {position}")
            else:
                logger.warning(
                    f"Could not find file {file_path} in PR files or file has no patch"
                )
        except Exception as e:
            logger.warning(f"Could not calculate position from diff: {e}")

        # Use GitHub REST API directly via requests for more reliable comment posting
        # Check if we have a valid file path that exists in the PR
        if not target_file:
            # File not found in PR - fall back to issue comment (general PR comment)
            logger.warning(
                f"File '{file_path}' not found in PR files. Posting as general PR comment instead."
            )
            api_url = f"https://api.github.com/repos/{repo_identifier}/issues/{pull_request_number}/comments"
            # Add file path and line info to comment body for context
            line_info = f"**File:** `{file_path}`"
            if comment_line is not None:
                line_info += f"\n**Line:** {comment_line}"
            elif comment_start_line is not None:
                line_info += f"\n**Lines:** {comment_start_line}-{comment_end_line}"
            formatted_comment_with_context = f"{line_info}\n\n{formatted_comment}"

            payload = {"body": formatted_comment_with_context}
            logger.info("Posting as general PR comment (file not in PR diff)")
        else:
            # File exists in PR - try to post as review comment
            api_url = f"https://api.github.com/repos/{repo_identifier}/pulls/{pull_request_number}/comments"

            if position is None:
                # If we couldn't calculate position, use a default based on line number
                # This is an approximation but should work for most cases
                if comment_line is not None:
                    position = comment_line + 5  # Add small offset for diff headers
                elif comment_end_line is not None:
                    position = comment_end_line + 5
                else:
                    position = 10  # Default position

                logger.warning(
                    f"Position calculation unavailable, using approximate position: {position}"
                )

            # Use the actual file path from PR (may differ from requested path)
            payload = {
                "body": formatted_comment,
                "commit_id": commit_sha,
                "path": actual_file_path,  # Use the actual file path from PR
                "position": position,
                "side": side.upper(),  # Must be "LEFT" or "RIGHT" (uppercase)
            }
            logger.info(
                f"Posting as review comment with position: {position}, side: {side.upper()}, path: {actual_file_path}"
            )

        # Prepare headers
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

        logger.debug(f"Posting to API: {api_url}")
        logger.debug(f"Payload: {payload}")

        # Make the API request
        response = requests.post(api_url, json=payload, headers=headers)

        if response.status_code == 201:
            comment_data = response.json()
            comment_id = comment_data.get("id")
            comment_url = comment_data.get("html_url")

            logger.info(f"Comment posted successfully - Comment ID: {comment_id}")
            logger.debug(f"Comment URL: {comment_url}")

            return {
                "success": True,
                "comment_id": comment_id,
                "comment_url": comment_url,
                "error": None,
                "impact": impact,
                "file_path": file_path,
                "line_number": comment_line
                or f"{comment_start_line}-{comment_end_line}",
            }
        elif response.status_code == 403:
            # Handle permission errors gracefully
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("message", "Permission denied")

            # Provide helpful error message about token permissions
            detailed_error = (
                f"GitHub API returned 403 Forbidden: {error_msg}. "
                f"This usually means your GitHub token (GIT_WRITE_TOKEN) doesn't have the required permissions. "
                f"Please ensure your token has 'Pull requests' write permission. "
                f"Visit: https://github.com/settings/tokens to update your token permissions."
            )
            logger.error(detailed_error)
            logger.debug(f"Full API response: {response.text}")

            return {
                "success": False,
                "comment_id": None,
                "comment_url": None,
                "error": detailed_error,
                "impact": impact,
                "file_path": file_path,
                "line_number": comment_line
                or (f"{comment_start_line}-{comment_end_line}" if start_line else None),
            }
        else:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get(
                "message", f"GitHub API returned status {response.status_code}"
            )
            detailed_error = (
                f"GitHub API returned status {response.status_code}: {error_msg}"
            )
            logger.error(detailed_error)
            logger.debug(f"Full API response: {response.text}")

            return {
                "success": False,
                "comment_id": None,
                "comment_url": None,
                "error": detailed_error,
                "impact": impact,
                "file_path": file_path,
                "line_number": comment_line
                or (f"{comment_start_line}-{comment_end_line}" if start_line else None),
            }

    except Exception as e:
        error_msg = f"Error posting comment: {e}"
        logger.error(error_msg, exc_info=True)
        logger.debug(
            f"Failed comment details - File: {file_path}, Line: {comment_line or f'{comment_start_line}-{comment_end_line}'}"
        )

        # Don't raise exception, return error result instead
        return {
            "success": False,
            "comment_id": None,
            "comment_url": None,
            "error": error_msg,
            "impact": impact,
            "file_path": file_path,
            "line_number": comment_line
            or (f"{comment_start_line}-{comment_end_line}" if start_line else None),
        }


# Export the tool (already decorated with @tool)
post_code_review_comment_tool = post_code_review_comment


if __name__ == "__main__":
    """Example usage of the post_code_review_comment tool."""

    print("=" * 80)
    print("Example: Using post_code_review_comment_tool")
    print("=" * 80)

    # Example 1: Post a critical comment on a single line
    print("\n1. Posting critical comment on single line...")

    try:
        result = post_code_review_comment_tool.invoke(
            {
                "repo_link": "https://github.com/TheCoder30ec4/OneForAll-MCP/",
                "pull_request_number": 3,
                "file_path": "Backend/OneForAllMCP/app/main.py",
                "code_snippet": "def insecure_function(password):\n    return password",
                "comment": "This function stores passwords in plain text. Please use proper encryption/hashing.",
                "impact": "Critical",
                "line_number": 42,
                "side": "RIGHT",
            }
        )

        if result["success"]:
            print("✅ Comment posted successfully!")
            print(f"   Comment ID: {result['comment_id']}")
            print(f"   Comment URL: {result['comment_url']}")
            print(f"   Impact: {result['impact']}")
        else:
            print(f"❌ Failed: {result['error']}")

        # Example 2: Post a medium impact comment on multiple lines
        print("\n2. Posting medium impact comment on multiple lines...")
        result2 = post_code_review_comment_tool.invoke(
            {
                "repo_link": "https://github.com/TheCoder30ec4/OneForAll-MCP/",
                "pull_request_number": 3,
                "file_path": "Backend/OneForAllMCP/app/api.py",
                "code_snippet": "def process_data(data):\n    # Missing error handling\n    result = data.process()\n    return result",
                "comment": "Consider adding error handling for edge cases and invalid input.",
                "impact": "Medium",
                "start_line": 10,
                "end_line": 13,
                "side": "RIGHT",
            }
        )

        if result2["success"]:
            print("✅ Comment posted successfully!")
            print(f"   Comment ID: {result2['comment_id']}")
            print(f"   Impact: {result2['impact']}")
        else:
            print(f"❌ Failed: {result2['error']}")

        # Example 3: Post an OK impact comment
        print("\n3. Posting OK impact comment...")
        result3 = post_code_review_comment_tool.invoke(
            {
                "repo_link": "https://github.com/TheCoder30ec4/OneForAll-MCP/",
                "pull_request_number": 3,
                "file_path": "Backend/OneForAllMCP/app/utils.py",
                "code_snippet": "def helper(): pass",
                "comment": "Consider adding a docstring to document this function's purpose.",
                "impact": "OK",
                "line_number": 5,
                "side": "RIGHT",
            }
        )

        if result3["success"]:
            print("✅ Comment posted successfully!")
            print(f"   Comment ID: {result3['comment_id']}")
            print(f"   Impact: {result3['impact']}")
        else:
            print(f"❌ Failed: {result3['error']}")

    except ValueError as e:
        print(f"\n❌ Validation Error: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("Tool metadata:")
    print("=" * 80)
    print(f"Tool Name: {post_code_review_comment_tool.name}")
    print(f"Tool Description: {post_code_review_comment_tool.description}")
    print("=" * 80)
