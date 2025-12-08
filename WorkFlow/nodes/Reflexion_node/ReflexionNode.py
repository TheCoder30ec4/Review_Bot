"""Reflexion node for verifying and validating review comments before posting."""

import sys
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.nodes.Review_file_node.ReviewFileState import ReviewState
from WorkFlow.PromptLibrary.Prompts import REFLEXION_SYSTEM_PROMPT
from WorkFlow.utils.logger import get_logger


class ReflexionState(BaseModel):
    """State for reflexion validation of review comments."""
    IsValid: bool = Field(
        description="Whether the review comment is valid and should be posted. True if all validations pass, False if issues found.",
        examples=[True, False]
    )
    ValidationIssues: list[str] = Field(
        description="List of validation issues found. Empty if IsValid is True.",
        examples=[
            ["DiffCode is empty or invalid", "Comment is too vague"],
            [],
            ["File path doesn't match diff code context"]
        ],
        default_factory=list
    )
    ImprovedReviewState: Optional[ReviewState] = Field(
        description="Improved review state if issues were found and fixed. None if no improvements needed.",
        default=None
    )
    Confidence: float = Field(
        description="Confidence score (0-1) that the review comment is accurate and helpful.",
        ge=0.0,
        le=1.0,
        examples=[0.95, 0.75, 0.50]
    )




def ReflexionNode(
    review_state: ReviewState,
    file_content: str,
    pr_context: Dict[str, Any]
) -> tuple[bool, ReviewState, float, list[str]]:
    """
    Validate and verify a review comment before posting using reflexion.
    
    Args:
        review_state: The review state to validate
        file_content: Full content of the file being reviewed
        pr_context: Dictionary with PR context (title, description, etc.)
    
    Returns:
        Tuple of (is_valid, improved_review_state, confidence, validation_issues)
        - is_valid: Whether the review passed validation
        - improved_review_state: The original or improved review state
        - confidence: Confidence score (0-1)
        - validation_issues: List of validation issue descriptions
    """
    logger = get_logger()
    
    try:
        # Create LLM with structured output
        llm = ChatGroq(model="openai/gpt-oss-120b")
        # Let LangChain auto-select the best method (tool calling for Groq)
        structured_llm = llm.with_structured_output(ReflexionState, include_raw=False)
        
        # Create validation prompt
        validation_prompt = f"""Validate the following code review comment before it is posted to GitHub.

**File Being Reviewed:** {review_state.File}

**Review State to Validate:**
- Criticality: {review_state.CriticalityStatus}
- What Needs To Be Improved: {review_state.WhatNeedsToBeImproved}
- Diff Code:
```
{review_state.DiffCode}
```
- Prompt For AI: {review_state.PromptForAI}

**PR Context:**
- Title: {pr_context.get('pr_title', 'N/A')}
- Description: {pr_context.get('pr_description', 'N/A')}

**File Content (for context):**
```
{file_content[:2000]}...
```

**Validation Checklist:**

1. **DiffCode Validation** (CRITICAL):
   - Is DiffCode populated with actual code?
   - Does DiffCode contain properly formatted source code (no +/- markers)?
   - Is DiffCode syntactically valid?
   - Does DiffCode match the file and context being reviewed?
   - Is there enough code context to understand the issue?

2. **Comment Quality**:
   - Is "WhatNeedsToBeImproved" specific and actionable?
   - Does it clearly explain the problem and why it's an issue?
   - Is it professional and constructive?
   - Does it provide enough detail for the developer?

3. **Criticality Accuracy**:
   - Does the criticality level match the severity?
   - Critical: Security vulnerabilities, bugs causing failures, data loss
   - Medium: Error handling, performance, maintainability issues
   - OK: Style, documentation, minor suggestions

4. **Completeness & Relevance**:
   - Are all fields properly populated?
   - Does the issue description match the code snippet?
   - Is this review comment relevant to the PR?
   - Is it not duplicate or repetitive?

**Your Task:**
1. Perform all validations above
2. Calculate a confidence score (0-1) for this review
3. If issues found:
   - List all validation issues clearly
   - Attempt to create an improved ReviewState by fixing the issues
   - Extract proper DiffCode if it's malformed
   - Improve comment clarity if it's vague
4. Return validation results

Return your validation in the ReflexionState format."""
        
        # Invoke LLM with retry logic
        messages = [
            SystemMessage(content=REFLEXION_SYSTEM_PROMPT),
            HumanMessage(content=validation_prompt)
        ]
        
        max_retries = 3
        retry_count = 0
        reflexion_state = None
        
        while retry_count < max_retries:
            try:
                reflexion_state = structured_llm.invoke(messages)
                break
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = random.uniform(180, 240)
                        logger.warning(f"Rate limit error. Waiting {wait_time:.1f}s before retry {retry_count}/{max_retries}...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {max_retries} retries.")
                        raise
                else:
                    raise
        
        if reflexion_state is None:
            raise Exception("Failed to generate reflexion state")
        
        # Determine which review state to use
        final_review_state = review_state
        if not reflexion_state.IsValid and reflexion_state.ImprovedReviewState:
            logger.info(f"Reflexion found issues, using improved review state")
            final_review_state = reflexion_state.ImprovedReviewState
            # Ensure file path is preserved
            final_review_state.File = review_state.File
        
        # Log validation results
        if reflexion_state.ValidationIssues:
            logger.warning(f"Validation issues found: {', '.join(reflexion_state.ValidationIssues)}")
        
        return (
            reflexion_state.IsValid or (reflexion_state.ImprovedReviewState is not None),
            final_review_state,
            reflexion_state.Confidence,
            reflexion_state.ValidationIssues
        )
        
    except Exception as e:
        logger.error(f"Error in ReflexionNode: {e}", exc_info=True)
        # On error, allow the original review to proceed but with low confidence
        return True, review_state, 0.5, [f"Reflexion validation failed: {str(e)}"]

