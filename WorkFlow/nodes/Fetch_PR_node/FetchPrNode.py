"""Node for fetching pull request details and populating states."""

import sys
from pathlib import Path

# Add project root to path for direct folder imports
# This allows imports like: from WorkFlow.State import ...
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent  # Go up to project root
sys.path.insert(0, str(project_root))

from WorkFlow.nodes.Fetch_PR_node.FetchPrState import FetchState, PrRequestState
from WorkFlow.State import Global_State, intial_state
from WorkFlow.tools.GetPullRequestTool import get_pull_request_tool
from WorkFlow.utils.logger import get_logger


def FetchNode(
    initial_state: intial_state, global_state: Global_State
) -> tuple[intial_state, Global_State, FetchState]:
    """
    Fetch pull request details using the GetPullRequestTool and populate states.

    Args:
        initial_state: Initial state containing PR link and number
        global_state: Global state to be updated with PR information

    Returns:
        Tuple of (initial_state, updated_global_state, fetch_state)
    """
    logger = get_logger()
    logger.info(
        f"FetchNode: Starting PR fetch for PR #{initial_state.PullRequestNum} from {initial_state.PullRequestLink}"
    )

    try:
        # Invoke the get_pull_request tool
        logger.info("Invoking get_pull_request_tool...")
        pr_result = get_pull_request_tool.invoke(
            {
                "repo_link": initial_state.PullRequestLink,
                "pull_request_number": initial_state.PullRequestNum,
            }
        )

        logger.info("PR details fetched successfully")

        # Extract PR details
        pr_details = pr_result["pr_details"]
        saved_files = pr_result["saved_files"]
        ignored_files = pr_result["ignored_files"]
        workspace_path = pr_result["SavedWorkspaceFiles"]
        total_files = pr_result["total_files"]

        # Update Global_State
        updated_global_state = Global_State(
            TotalFiles=total_files,
            ReviewedFiles=global_state.ReviewedFiles.copy(),  # Keep existing reviewed files
            CurrentFile=global_state.CurrentFile,  # Keep current file if any
            RelaventContext=global_state.RelaventContext.copy(),  # Keep existing context
            SkippedFiles=global_state.SkippedFiles.copy(),  # Keep existing skipped files
            IgnoreFiles=ignored_files,  # Set ignored files from PR fetch
        )

        # Create PrRequestState from pr_details
        # Map GitHub state ("open", "closed") to FetchPrState Literal ("open", "close")
        github_state = pr_details["State"].lower()
        mapped_state = "close" if github_state == "closed" else "open"

        pr_state = PrRequestState(
            Title=pr_details["Title"],
            State=mapped_state,
            Description=pr_details["Description"],
            FileStructure=pr_details["FileStructure"],
            Branch=pr_details["Branch"],
        )

        # Create FetchState
        fetch_state = FetchState(WorkSpacePath=workspace_path, PrRequest=pr_state)

        logger.info(
            f"FetchNode completed successfully. Total files: {total_files}, Saved: {len(saved_files)}, Ignored: {len(ignored_files)}"
        )

        return initial_state, updated_global_state, fetch_state

    except Exception as e:
        logger.error(f"Error in FetchNode: {e}")
        import traceback

        traceback.print_exc()
        raise
