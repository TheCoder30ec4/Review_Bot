"""Node for reviewing individual files and generating review comments."""

import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.nodes.Review_file_node.ReviewFileState import ReviewState
from WorkFlow.PromptLibrary.Prompts import (
    REVIEW_FILE_SYSTEM_PROMPT,
    get_review_file_invocation_prompt,
)
from WorkFlow.State import Global_State
from WorkFlow.tools.ReadFileTool import read_file_tool
from WorkFlow.utils.logger import get_logger


def find_relevant_files(
    file_path: str, all_files: List[str], workspace_path: str, logger
) -> List[Dict[str, str]]:
    """
    Find files relevant to the file being reviewed.

    Args:
        file_path: Path of the file being reviewed
        all_files: List of all available files in the PR
        workspace_path: Workspace path where files are stored
        logger: Logger instance

    Returns:
        List of dicts with 'file_path', 'content', and 'relevance' keys
    """
    relevant_files = []
    file_path_obj = Path(file_path)
    file_dir = file_path_obj.parent
    file_name = file_path_obj.stem

    # Strategy 1: Files in the same directory
    same_dir_files = [
        f for f in all_files if Path(f).parent == file_dir and f != file_path
    ]

    # Strategy 2: Files with similar names (e.g., same base name with different extensions)
    similar_name_files = [
        f for f in all_files if Path(f).stem == file_name and f != file_path
    ]

    # Strategy 3: Related files (e.g., if reviewing a controller, look for related service/model files)
    related_files = []
    if "controller" in file_path.lower():
        # Look for related service/model files
        related_files = [
            f
            for f in all_files
            if ("service" in f.lower() or "model" in f.lower())
            and file_dir in Path(f).parents
        ]
    elif "service" in file_path.lower():
        # Look for related model/entity files
        related_files = [
            f
            for f in all_files
            if ("model" in f.lower() or "entity" in f.lower())
            and file_dir in Path(f).parents
        ]

    # Combine and deduplicate
    candidate_files = list(set(same_dir_files + similar_name_files + related_files))

    # Read and add relevance explanation for each file
    for rel_file in candidate_files[:5]:  # Limit to 5 most relevant files
        try:
            result = read_file_tool.invoke(
                {"file_path": rel_file, "workspace_path": workspace_path}
            )

            if result["success"]:
                # Determine relevance reason
                relevance_reason = ""
                if rel_file in same_dir_files:
                    relevance_reason = f"Located in the same directory as {file_path}, likely related functionality"
                elif rel_file in similar_name_files:
                    relevance_reason = "Similar filename suggests related functionality or complementary code"
                elif rel_file in related_files:
                    if (
                        "controller" in file_path.lower()
                        and "service" in rel_file.lower()
                    ):
                        relevance_reason = (
                            "Service file used by the controller being reviewed"
                        )
                    elif "service" in file_path.lower() and "model" in rel_file.lower():
                        relevance_reason = (
                            "Model/entity file used by the service being reviewed"
                        )
                    else:
                        relevance_reason = "Related file in the same module/package"

                relevant_files.append(
                    {
                        "file_path": rel_file,
                        "content": result["content"],
                        "relevance": relevance_reason,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to read relevant file {rel_file}: {e}")
            continue

    return relevant_files


def ReviewFileNode(
    file_path: str,
    global_state: Global_State,
    workspace_path: str,
    pr_title: str,
    pr_description: str,
    repo_link: str,
    pr_number: int,
    all_files: List[str],
    retry_context: Optional[Dict[str, Any]] = None,
) -> Global_State:
    """
    Review a single file and generate review comments.

    Args:
        file_path: Path of the file to review
        global_state: Global_State to be updated
        workspace_path: Workspace path where diff files are stored
        pr_title: Pull request title
        pr_description: Pull request description
        repo_link: Repository link
        pr_number: Pull request number
        all_files: List of all available files in the PR
        retry_context: Optional context for retry attempts with validation feedback

    Returns:
        Updated global_state
    """
    logger = get_logger()
    logger.info(f"ReviewFileNode: Reviewing file: {file_path}")

    try:
        # Update current file in global state
        updated_global_state = Global_State(
            TotalFiles=global_state.TotalFiles,
            ReviewedFiles=global_state.ReviewedFiles.copy(),
            CurrentFile=file_path,
            RelaventContext=global_state.RelaventContext.copy(),
            SkippedFiles=global_state.SkippedFiles.copy(),
            IgnoreFiles=global_state.IgnoreFiles.copy(),
        )

        # Read the file being reviewed
        file_result = read_file_tool.invoke(
            {"file_path": file_path, "workspace_path": workspace_path}
        )

        if not file_result["success"]:
            logger.error(f"Failed to read file {file_path}: {file_result.get('error')}")
            # Still update global state to mark as attempted (but don't add to ReviewedFiles since no review was done)
            updated_global_state.CurrentFile = ""
            # Return empty review state on error
            empty_review_state = ReviewState(
                File=file_path,
                CriticalityStatus="OK",
                WhatNeedsToBeImproved="Failed to read file",
                DiffCode="",
                PromptForAI="",
            )
            return updated_global_state, empty_review_state

        file_content = file_result["content"]

        # Find relevant files
        relevant_files = find_relevant_files(
            file_path=file_path,
            all_files=all_files,
            workspace_path=workspace_path,
            logger=logger,
        )

        # Update relevant context in global state
        relevance_context = [
            f"{rel_file['file_path']}: {rel_file['relevance']}"
            for rel_file in relevant_files
        ]
        updated_global_state.RelaventContext.extend(relevance_context)

        # Create invocation prompt
        invocation_prompt = get_review_file_invocation_prompt(
            file_path=file_path,
            file_content=file_content,
            pr_title=pr_title,
            pr_description=pr_description,
            relevant_files_context=relevant_files,
            workspace_path=workspace_path,
            repo_link=repo_link,
            pr_number=pr_number,
            retry_context=retry_context,
        )

        # Create LLM with structured output for ReviewState
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_groq import ChatGroq

        llm = ChatGroq(model="openai/gpt-oss-120b")
        # Let LangChain auto-select the best method (tool calling for Groq)
        structured_llm = llm.with_structured_output(ReviewState, include_raw=False)

        # Create messages in proper format
        messages = [
            SystemMessage(content=REVIEW_FILE_SYSTEM_PROMPT),
            HumanMessage(content=invocation_prompt),
        ]

        # Get review state from LLM with structured output

        # Retry logic for rate limiting
        max_retries = 3
        retry_count = 0
        review_state = None

        while retry_count < max_retries:
            try:
                review_state = structured_llm.invoke(messages)
                break  # Success, exit retry loop
            except Exception as e:
                error_str = str(e)
                # Check if it's a rate limit error
                if (
                    "429" in error_str
                    or "rate_limit" in error_str.lower()
                    or "RateLimitError" in str(type(e).__name__)
                ):
                    retry_count += 1
                    if retry_count < max_retries:
                        # Wait 3-4 minutes (180-240 seconds) before retrying
                        wait_time = random.uniform(180, 240)  # 3-4 minutes
                        logger.warning(
                            f"Rate limit error encountered. Waiting {wait_time:.1f} seconds ({wait_time/60:.1f} minutes) before retry {retry_count}/{max_retries}..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(
                            f"Rate limit error after {max_retries} retries. Giving up."
                        )
                        raise
                else:
                    # Not a rate limit error, re-raise immediately
                    raise

        if review_state is None:
            raise Exception("Failed to generate review state after retries")

        # Ensure file path is set correctly
        review_state.File = file_path

        # NOTE: Comment posting is now handled by Flow.py after reflexion validation
        # This ensures ALL comments go through reflexion before being posted
        logger.info(
            f"ReviewFileNode completed for {file_path}. Comment posting will be handled by Flow.py after reflexion."
        )

        # Return both global_state and review_state
        # Flow.py will handle reflexion validation and posting
        return updated_global_state, review_state

    except Exception as e:
        logger.error(f"Error in ReviewFileNode for {file_path}: {e}", exc_info=True)
        # Don't add to ReviewedFiles on error since review wasn't completed
        updated_global_state.CurrentFile = ""
        # Return empty review state on error
        empty_review_state = ReviewState(
            File=file_path,
            CriticalityStatus="OK",
            WhatNeedsToBeImproved="Error during review",
            DiffCode="",
            PromptForAI="",
        )
        return updated_global_state, empty_review_state
