"""Reflexion node for verifying and validating review comments before posting."""

import sys
import time
import random
import json
import re
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


def parse_failed_generation(error_message: str, logger) -> Optional['ReflexionState']:
    """
    Parse the failed_generation JSON from Groq tool_use_failed errors.
    
    When Groq LLM generates valid structured output but with wrong tool name,
    we can still extract and use the data from the error message.
    
    Args:
        error_message: The full error message string
        logger: Logger instance
    
    Returns:
        ReflexionState if parsing successful, None otherwise
    """
    try:
        # Look for 'failed_generation' in the error message
        if 'failed_generation' not in error_message:
            return None
        
        # Extract the JSON from the error - it's after 'failed_generation': '
        # The format is: 'failed_generation': '{"name": "...", "arguments": {...}}'
        match = re.search(r"'failed_generation':\s*'(.+?)'\s*\}\s*\}", error_message, re.DOTALL)
        if not match:
            # Try alternative format
            match = re.search(r'"failed_generation":\s*"(.+?)"\s*\}\s*\}', error_message, re.DOTALL)
        
        if not match:
            logger.debug("Could not find failed_generation pattern in error")
            return None
        
        # Get the JSON string and unescape it
        json_str = match.group(1)
        # Unescape the JSON string (it's escaped in the error message)
        json_str = json_str.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
        
        # Parse the outer JSON (which has name and arguments)
        outer_data = json.loads(json_str)
        
        # Get the arguments (which contains our actual data)
        if 'arguments' in outer_data:
            data = outer_data['arguments']
        else:
            data = outer_data
        
        logger.info(f"🔄 Recovered structured output from failed_generation (confidence: {data.get('Confidence', 'N/A')})")
        
        # Build ImprovedReviewState if present
        improved_review = None
        if data.get('ImprovedReviewState'):
            irs = data['ImprovedReviewState']
            improved_review = ReviewState(
                File=irs.get('File', ''),
                CriticalityStatus=irs.get('CriticalityStatus', 'Medium'),
                WhatNeedsToBeImproved=irs.get('WhatNeedsToBeImproved', ''),
                DiffCode=irs.get('DiffCode', ''),
                CurrentCode=irs.get('CurrentCode', ''),
                SuggestedCode=irs.get('SuggestedCode', ''),
                PromptForAI=irs.get('PromptForAI', '')
            )
        
        # Create ReflexionState
        reflexion_state = ReflexionState(
            IsValid=data.get('IsValid', False),
            ValidationIssues=data.get('ValidationIssues', []),
            ImprovedReviewState=improved_review,
            Confidence=float(data.get('Confidence', 0.5))
        )
        
        return reflexion_state
        
    except Exception as parse_error:
        logger.debug(f"Failed to parse failed_generation: {parse_error}")
        return None


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
- Current Code (code to be replaced):
```
{review_state.CurrentCode if review_state.CurrentCode else '(NOT PROVIDED - REQUIRED)'}
```
- Suggested Code (fixed version):
```
{review_state.SuggestedCode if review_state.SuggestedCode else '(NOT PROVIDED - REQUIRED)'}
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

2. **CurrentCode & SuggestedCode Validation** (CRITICAL):
   - Is CurrentCode populated with the existing code that needs changing?
   - Is SuggestedCode populated with the complete fixed version?
   - Are both syntactically valid?
   - Does SuggestedCode actually fix the identified issue?
   - Are they properly formatted and complete (not placeholders)?

3. **Comment Quality**:
   - Is "WhatNeedsToBeImproved" specific and actionable?
   - Does it clearly explain the problem and why it's an issue?
   - Is it professional and constructive?
   - Does it provide enough detail for the developer?

4. **Criticality Accuracy**:
   - Does the criticality level match the severity?
   - Critical: Security vulnerabilities, bugs causing failures, data loss
   - Medium: Error handling, performance, maintainability issues
   - OK: Style, documentation, minor suggestions

5. **Completeness & Relevance**:
   - Are ALL fields properly populated (File, DiffCode, CurrentCode, SuggestedCode)?
   - Does the issue description match the code snippet?
   - Is this review comment relevant to the PR?
   - Is it not duplicate or repetitive?

**Your Task:**
1. Perform all validations above
2. Calculate a confidence score (0-1) for this review:
   - 1.0: All fields valid and complete
   - 0.7-0.9: Minor issues but usable
   - 0.4-0.6: Missing required fields or significant issues
   - 0.0-0.3: Invalid or unusable review
3. If issues found:
   - List all validation issues clearly
   - Attempt to create an improved ReviewState by fixing the issues
   - Extract proper DiffCode, CurrentCode, SuggestedCode if malformed
   - Improve comment clarity if it's vague
   - **IMPORTANT**: If CurrentCode or SuggestedCode is missing, provide them in ImprovedReviewState
4. Return validation results

**CRITICAL**: For a valid review, ALL of these must be populated:
- File (the file path)
- DiffCode (code snippet from diff)
- CurrentCode (existing code to replace)
- SuggestedCode (fixed version of the code)
- WhatNeedsToBeImproved (explanation)

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
                
                # Check if this is the tool_use_failed error with valid data
                if "tool_use_failed" in error_str or "attempted to call tool" in error_str:
                    logger.warning(f"Tool call mismatch error - attempting to recover data from failed_generation...")
                    recovered_state = parse_failed_generation(error_str, logger)
                    if recovered_state:
                        reflexion_state = recovered_state
                        logger.info(f"✅ Successfully recovered ReflexionState from error (confidence: {reflexion_state.Confidence})")
                        break
                    else:
                        logger.warning("Could not recover data from failed_generation, will retry...")
                
                # Check for rate limit errors
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
                    # For other errors, retry once then raise
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"LLM error, retrying ({retry_count}/{max_retries}): {error_str[:200]}...")
                        time.sleep(5)  # Brief pause before retry
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

