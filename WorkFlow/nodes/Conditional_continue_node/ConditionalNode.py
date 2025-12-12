"""Conditional node to check if more comments are needed for a file."""

import random
import sys
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.nodes.Review_file_node.ReviewFileState import ReviewState
from WorkFlow.PromptLibrary.Prompts import CONDITIONAL_SYSTEM_PROMPT
from WorkFlow.utils.logger import get_logger


class ConditionalState(BaseModel):
    """State for conditional decision on whether to continue reviewing."""

    ContinueReview: bool = Field(
        description="Whether to continue reviewing this file for more comments. True if there are more issues to comment on, False if review is complete.",
        examples=[True, False],
    )
    Reason: str = Field(
        description="Reason for the decision. If ContinueReview is True, explain what other issues need to be reviewed. If False, explain why the review is complete.",
        examples=[
            "There are additional security concerns in the authentication logic that need review",
            "Review complete - all critical and medium issues have been addressed",
            "Found more code quality issues in error handling sections",
        ],
    )


def ConditionalNode(
    file_path: str,
    previous_review_state: ReviewState,
    file_content: str,
    workspace_path: str,
) -> tuple[bool, ReviewState | None]:
    """
    Conditional node that decides if more comments are needed for a file.

    Args:
        file_path: Path of the file being reviewed
        previous_review_state: The review state from the previous review iteration
        file_content: Content of the file being reviewed (diff)
        workspace_path: Workspace path where files are stored

    Returns:
        Tuple of (should_continue: bool, next_review_state: ReviewState | None)
        If should_continue is True, next_review_state will contain the next review to post
        If should_continue is False, next_review_state will be None
    """
    logger = get_logger()

    try:
        # Create LLM with structured output
        llm = ChatGroq(model="openai/gpt-oss-120b")
        structured_llm = llm.with_structured_output(ConditionalState, include_raw=False)

        # Create invocation prompt
        invocation_prompt = f"""You have just reviewed the file '{file_path}' and posted the following comment:

**Previous Comment Posted:**
- Criticality: {previous_review_state.CriticalityStatus}
- Issue: {previous_review_state.WhatNeedsToBeImproved}
- Code Snippet Reviewed:
```
{previous_review_state.DiffCode}
```

**File Content (Diff):**
```
{file_content[:2000]}...
```

**Question:** Are there any other issues in this file that need to be reviewed and commented on?

Consider:
- Are there other code sections with problems?
- Are there additional security, performance, or code quality issues?
- Have all critical and medium priority issues been identified?

If yes, you should continue reviewing. If the file has been thoroughly reviewed and all significant issues have been addressed, you can stop.

Return your decision in the ConditionalState format."""

        # Invoke LLM with retry logic for rate limiting
        messages = [
            SystemMessage(content=CONDITIONAL_SYSTEM_PROMPT),
            HumanMessage(content=invocation_prompt),
        ]

        max_retries = 3
        retry_count = 0
        conditional_state = None

        while retry_count < max_retries:
            try:
                conditional_state = structured_llm.invoke(messages)
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

        if conditional_state is None:
            raise Exception("Failed to generate conditional state after retries")

        if conditional_state.ContinueReview:
            # Generate next review state using the same LLM
            logger.info(
                f"More comments needed for {file_path}. Generating next review..."
            )

            # Use ReviewState structured output to generate next comment
            review_llm = llm.with_structured_output(ReviewState, include_raw=False)

            next_review_prompt = f"""Continue reviewing the file '{file_path}'. 

You have already posted a comment about:
- {previous_review_state.WhatNeedsToBeImproved}

Now identify a DIFFERENT issue in this file that also needs to be reviewed. Look for other problems, bugs, security issues, or code quality concerns.

**File Content (Diff):**
```
{file_content}
```

**Important:**
- Find a DIFFERENT issue than the one already commented on
- Extract the EXACT code snippet from the diff (remove + markers)
- Determine criticality (OK, Medium, or Critical)
- Provide actionable feedback
- Generate a prompt for AI to create the GitHub comment

Return your review in the ReviewState format."""

            review_messages = [
                SystemMessage(
                    content="You are an expert code reviewer. Identify issues in code and provide actionable feedback."
                ),
                HumanMessage(content=next_review_prompt),
            ]

            # Retry logic for rate limiting
            max_retries = 3
            retry_count = 0
            next_review_state = None

            while retry_count < max_retries:
                try:
                    next_review_state = review_llm.invoke(review_messages)
                    next_review_state.File = file_path  # Ensure file path is set
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

            if next_review_state is None:
                raise Exception("Failed to generate next review state after retries")

            return True, next_review_state
        else:
            logger.info(f"Review complete for {file_path}. No more comments needed.")
            return False, None

    except Exception as e:
        logger.error(f"Error in ConditionalNode for {file_path}: {e}", exc_info=True)
        # On error, assume review is complete to avoid infinite loops
        return False, None
