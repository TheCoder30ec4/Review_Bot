"""Tool for reading file contents from the Output/diff_files directory."""

import sys
from pathlib import Path
from typing import Any, Dict

from langchain_core.tools import tool

# Add parent directory to path to import logger
current_file = Path(__file__).resolve()
workflow_dir = current_file.parent.parent
sys.path.insert(0, str(workflow_dir))
from utils.logger import get_logger

# Get project root directory (parent of WorkFlow)
PROJECT_ROOT = current_file.parent.parent.parent

# Default workspace directory for diff files
DEFAULT_WORKSPACE = PROJECT_ROOT / "Output" / "diff_files"


@tool
def read_file(file_path: str, workspace_path: str = None) -> Dict[str, Any]:
    """
    Read the content of a file from the Output/diff_files directory.

    This tool reads diff files that were saved during PR processing. Files are stored
    with .txt extension in the workspace directory, maintaining the original file structure.

    Args:
        file_path: Relative file path from repository root (e.g., 'Backend/app/main.py').
                  The tool will automatically append .txt extension to find the diff file.
        workspace_path: Optional workspace directory path. If not provided, defaults to
                       'Output/diff_files' in the project root.

    Returns:
        Dictionary containing:
        - success: bool indicating if file was read successfully
        - file_path: The requested file path
        - content: File content as string (if successful)
        - error: Error message (if unsuccessful)
        - file_size: Size of file in bytes (if successful)
        - lines: Number of lines in file (if successful)

    Raises:
        ValueError: If file_path is empty or invalid
        FileNotFoundError: If file does not exist in workspace
        PermissionError: If file cannot be read due to permissions
        IOError: If file reading fails for other reasons

    Example:
        >>> result = read_file.invoke({"file_path": "Backend/app/main.py"})
        >>> print(result["content"])
    """
    logger = get_logger()
    logger.info(
        f"read_file tool invoked - file_path: '{file_path}', workspace_path: '{workspace_path}'"
    )

    # Validate input
    if not file_path or not file_path.strip():
        error_msg = "File path cannot be empty"
        logger.error(f"Validation failed: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"Input validation passed for file_path: '{file_path}'")

    # Normalize file path (handle both Windows and Unix paths)
    file_path_normalized = file_path.strip().replace("\\", "/")
    logger.debug(f"Normalized file path: '{file_path}' -> '{file_path_normalized}'")

    # Determine workspace directory
    if workspace_path:
        logger.debug(f"Custom workspace path provided: '{workspace_path}'")
        workspace_dir = Path(workspace_path)
        if not workspace_dir.is_absolute():
            workspace_dir = PROJECT_ROOT / workspace_path
            logger.debug(f"Resolved relative workspace path to: {workspace_dir}")
        else:
            logger.debug(f"Using absolute workspace path: {workspace_dir}")
    else:
        workspace_dir = DEFAULT_WORKSPACE
        logger.debug(f"Using default workspace path: {workspace_dir}")

    # Construct full file path with .txt extension
    # Check if file_path already ends with .txt to avoid double extension
    if file_path_normalized.endswith(".txt"):
        logger.debug("File path already has .txt extension, not appending")
        full_file_path = workspace_dir / file_path_normalized
    else:
        logger.debug("Appending .txt extension to file path")
        full_file_path = workspace_dir / f"{file_path_normalized}.txt"

    logger.info(f"Resolved full file path: {full_file_path}")
    logger.debug(f"Workspace directory: {workspace_dir}")

    # Security check: Ensure file is within workspace directory (prevent path traversal)
    logger.debug("Performing security check: validating file path is within workspace")
    try:
        resolved_file_path = full_file_path.resolve()
        resolved_workspace = workspace_dir.resolve()
        logger.debug(f"Resolved file path: {resolved_file_path}")
        logger.debug(f"Resolved workspace: {resolved_workspace}")

        # Check if file is within workspace
        if not str(resolved_file_path).startswith(str(resolved_workspace)):
            error_msg = "Security violation: File path attempts to access outside workspace directory"
            logger.error(
                f"{error_msg} - File: {resolved_file_path}, Workspace: {resolved_workspace}"
            )
            raise ValueError(error_msg)
        logger.debug("Security check passed: file path is within workspace boundaries")
    except ValueError:
        # Re-raise ValueError as-is (security violation)
        raise
    except Exception as e:
        error_msg = f"Error resolving file path: {e}"
        logger.error(
            f"{error_msg} - Original error: {type(e).__name__}: {e}", exc_info=True
        )
        raise ValueError(error_msg)

    # Check if file exists
    logger.debug(f"Checking if file exists: {full_file_path}")
    if not full_file_path.exists():
        error_msg = f"File not found: {file_path} (looked for: {full_file_path})"
        logger.warning(error_msg)
        logger.debug(
            f"File path components - workspace: {workspace_dir}, normalized_path: {file_path_normalized}"
        )
        return {
            "success": False,
            "file_path": file_path,
            "content": None,
            "error": error_msg,
            "file_size": None,
            "lines": None,
        }
    logger.debug(f"File exists: {full_file_path}")

    # Check if it's a file (not a directory)
    logger.debug(f"Verifying path is a file (not directory): {full_file_path}")
    if not full_file_path.is_file():
        error_msg = f"Path exists but is not a file: {file_path}"
        logger.warning(f"{error_msg} - Path type: {type(full_file_path)}")
        return {
            "success": False,
            "file_path": file_path,
            "content": None,
            "error": error_msg,
            "file_size": None,
            "lines": None,
        }
    logger.debug(f"Path verification passed: {full_file_path} is a valid file")

    # Read file content
    try:
        logger.info(f"Starting file read operation for: {file_path}")
        logger.debug(f"Opening file: {full_file_path}")

        # Read file with UTF-8 encoding, handle encoding errors gracefully
        try:
            logger.debug("Attempting to read file with UTF-8 encoding")
            with open(full_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug("Successfully read file with UTF-8 encoding")
        except UnicodeDecodeError as e:
            # If UTF-8 fails, try reading as binary and decode with error handling
            logger.warning(f"UTF-8 decoding failed for {file_path}: {e}")
            logger.info("Falling back to binary read with error handling")
            with open(full_file_path, "rb") as f:
                content_bytes = f.read()
                logger.debug(f"Read {len(content_bytes)} bytes as binary")
                content = content_bytes.decode("utf-8", errors="replace")
                logger.info("Successfully decoded file content with error replacement")

        # Get file statistics
        logger.debug("Calculating file statistics")
        file_size = full_file_path.stat().st_size
        lines = content.count("\n") + (1 if content else 0)
        content_length = len(content)

        logger.info(f"Successfully read file: {file_path}")
        logger.debug(
            f"File statistics - Size: {file_size} bytes, Content length: {content_length} chars, Lines: {lines}"
        )

        return {
            "success": True,
            "file_path": file_path,
            "content": content,
            "error": None,
            "file_size": file_size,
            "lines": lines,
        }

    except PermissionError as e:
        error_msg = f"Permission denied reading file: {file_path} - {e}"
        logger.error(f"{error_msg} - File: {full_file_path}")
        logger.debug(
            f"Permission error details - File exists: {full_file_path.exists()}, Is file: {full_file_path.is_file() if full_file_path.exists() else 'N/A'}"
        )
        return {
            "success": False,
            "file_path": file_path,
            "content": None,
            "error": error_msg,
            "file_size": None,
            "lines": None,
        }
    except IOError as e:
        error_msg = f"IO error reading file: {file_path} - {e}"
        logger.error(f"{error_msg} - File: {full_file_path}")
        logger.debug(
            f"IO error details - Error type: {type(e).__name__}, Error code: {getattr(e, 'errno', 'N/A')}"
        )
        return {
            "success": False,
            "file_path": file_path,
            "content": None,
            "error": error_msg,
            "file_size": None,
            "lines": None,
        }
    except Exception as e:
        error_msg = f"Unexpected error reading file: {file_path} - {e}"
        logger.error(f"{error_msg} - File: {full_file_path}")
        logger.error(f"Unexpected error type: {type(e).__name__}", exc_info=True)
        return {
            "success": False,
            "file_path": file_path,
            "content": None,
            "error": error_msg,
            "file_size": None,
            "lines": None,
        }


# Export the tool (already decorated with @tool)
read_file_tool = read_file


if __name__ == "__main__":
    """Example usage of the read_file tool."""

    print("=" * 80)
    print("Example: Using read_file_tool")
    print("=" * 80)

    # Example 1: Read a file that exists
    test_file = "/home/thecoder30ec4/Documents/Code_Review_Bot/Output/diff_files/Backend/tests/conftest.py.txt"

    try:
        print(f"\n1. Reading file: {test_file}")
        result = read_file_tool.invoke({"file_path": test_file})

        print(result)

    except ValueError as e:
        print(f"\n❌ Validation Error: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("Tool metadata:")
    print("=" * 80)
    print(f"Tool Name: {read_file_tool.name}")
    print(f"Tool Description: {read_file_tool.description}")
    print("=" * 80)
