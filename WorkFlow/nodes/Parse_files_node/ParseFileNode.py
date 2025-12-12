"""Node for parsing files and deciding which to review and which to skip."""

import re
import sys
from pathlib import Path

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.nodes.Fetch_PR_node.FetchPrState import FetchState
from WorkFlow.nodes.Parse_files_node.ParseFileState import ParseState
from WorkFlow.PromptLibrary.Prompts import (
    PARSE_FILES_SYSTEM_PROMPT,
    get_parse_files_invocation_prompt,
)
from WorkFlow.State import Global_State
from WorkFlow.utils.logger import get_logger


def ParseFileNode(
    fetch_state: FetchState, global_state: Global_State
) -> tuple[Global_State, ParseState]:
    """
    Parse files from the PR and decide which to review and which to skip.

    Args:
        fetch_state: FetchState containing PR details and workspace path
        global_state: Global_State to be updated with skipped files

    Returns:
        Tuple of (updated_global_state, parse_state)
    """
    logger = get_logger()

    try:
        # Extract file structure from fetch_state
        file_structure = fetch_state.PrRequest.FileStructure
        workspace_path = fetch_state.WorkSpacePath

        # Extract file paths from FileStructure
        file_paths = []
        for line in file_structure:
            # Extract file paths from lines like "> * `path/to/file.py` (X hunks)"
            match = re.search(r"`([^`]+)`", line)
            if match:
                file_paths.append(match.group(1))

        # Get prompts from PromptLibrary
        system_prompt = PARSE_FILES_SYSTEM_PROMPT
        invocation_prompt = get_parse_files_invocation_prompt(
            pr_title=fetch_state.PrRequest.Title,
            pr_description=fetch_state.PrRequest.Description,
            file_structure=file_structure,
            ignored_files=global_state.IgnoreFiles,
            workspace_path=workspace_path,
        )

        # Use LLM with structured output directly
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_groq import ChatGroq

        # Create LLM with structured output
        llm = ChatGroq(model="openai/gpt-oss-120b")
        structured_llm = llm.with_structured_output(ParseState, include_raw=False)

        # Create messages in proper format
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=invocation_prompt),
        ]

        # Invoke with structured output using proper message format
        parse_state = structured_llm.invoke(messages)

        # Validate SelectedFilePath - check if files actually exist in workspace

        # Get workspace directory path
        workspace_dir = Path(workspace_path)
        if not workspace_dir.is_absolute():
            workspace_dir = project_root / workspace_path

        validated_selected = []
        invalid_selected = []

        for file_path in parse_state.SelectedFilePath:
            # Normalize file path (handle both Windows and Unix paths)
            file_path_normalized = file_path.replace("\\", "/")
            # Check if file exists in workspace (with .txt extension)
            workspace_file = workspace_dir / f"{file_path_normalized}.txt"

            if workspace_file.exists():
                validated_selected.append(file_path)
            else:
                invalid_selected.append(file_path)
                logger.warning(
                    f"✗ Selected file does not exist in workspace: {file_path}"
                )
                logger.debug(f"   Looked for: {workspace_file}")

        # Add invalid selected files to skipped files with reason
        for invalid_file in invalid_selected:
            parse_state.SkippedFiles.append(
                (invalid_file, "File not found in workspace directory")
            )

        # Update parse_state with validated files only
        parse_state.SelectedFilePath = validated_selected

        if invalid_selected:
            logger.warning(
                f"Filtered out {len(invalid_selected)} invalid selected files that don't exist in workspace"
            )

        # Update Global_State with skipped files
        # Merge new skipped files with existing ones
        existing_skipped = {file: reason for file, reason in global_state.SkippedFiles}
        new_skipped = {file: reason for file, reason in parse_state.SkippedFiles}
        existing_skipped.update(new_skipped)

        updated_global_state = Global_State(
            TotalFiles=global_state.TotalFiles,
            ReviewedFiles=global_state.ReviewedFiles.copy(),
            CurrentFile=global_state.CurrentFile,
            RelaventContext=global_state.RelaventContext.copy(),
            SkippedFiles=list(existing_skipped.items()),
            IgnoreFiles=global_state.IgnoreFiles.copy(),
        )

        return updated_global_state, parse_state

    except Exception as e:
        logger.error(f"Error in ParseFileNode: {e}")
        import traceback

        traceback.print_exc()
        raise
