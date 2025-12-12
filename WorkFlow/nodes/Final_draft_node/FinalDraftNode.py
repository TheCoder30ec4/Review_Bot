"""Final draft node that generates and posts a summary comment on the GitHub PR."""

import sys
import time
import random
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
import os
import shutil

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.State import Global_State
from WorkFlow.PromptLibrary.Prompts import FINAL_DRAFT_SYSTEM_PROMPT
from WorkFlow.utils.logger import get_logger




def FinalDraftNode(
    global_state: Global_State,
    repo_link: str,
    pr_number: int,
    pr_title: str,
    pr_description: str
) -> str:
    """
    Generate and post a final summary comment on the GitHub pull request.
    
    Args:
        global_state: Global state containing all review information
        repo_link: GitHub repository URL
        pr_number: Pull request number
        pr_title: Pull request title
        pr_description: Pull request description
    
    Returns:
        The summary comment text that was posted
    """
    logger = get_logger()
    # Use a path relative to the project root so this works both locally and in deployment
    diff_folder = project_root / "Output" / "diff_files"
    
    try:
        # Prepare context for the LLM
        reviewed_files = global_state.ReviewedFiles
        skipped_files = global_state.SkippedFiles
        ignored_files = global_state.IgnoreFiles
        total_files = global_state.TotalFiles
        
        # Count files by status
        reviewed_count = len(reviewed_files)
        skipped_count = len(skipped_files)
        ignored_count = len(ignored_files)
        
        # Create invocation prompt
        invocation_prompt = f"""Create a comprehensive summary comment for this GitHub pull request.

**Pull Request Information:**
- Title: {pr_title}
- Description: {pr_description}
- PR Number: {pr_number}

**Review Statistics:**
- Total Files: {total_files}
- Files Reviewed: {reviewed_count}
- Files Skipped: {skipped_count}
- Files Ignored: {ignored_count}

**Files Reviewed:**
{chr(10).join(f"- {file}" for file in reviewed_files[:20])}
{f"... and {len(reviewed_files) - 20} more files" if len(reviewed_files) > 20 else ""}

**Files Skipped (with reasons):**
{chr(10).join(f"- {item[0]}: {item[1]}" if isinstance(item, tuple) and len(item) == 2 else f"- {item}: No reason provided" for item in skipped_files[:10])}
{f"... and {len(skipped_files) - 10} more skipped files" if len(skipped_files) > 10 else ""}

**Files Ignored (automatically):**
{chr(10).join(f"- {file}" for file in ignored_files[:10])}
{f"... and {len(ignored_files) - 10} more ignored files" if len(ignored_files) > 10 else ""}

**Relevant Context Found:**
{chr(10).join(f"- {context}" for context in global_state.RelaventContext[:10])}
{f"... and {len(global_state.RelaventContext) - 10} more context items" if len(global_state.RelaventContext) > 10 else ""}

Create a comprehensive summary comment that:
1. Provides an overview of the review process
2. Highlights key findings and comments posted
3. Lists files that were skipped and why
4. Provides overall recommendations
5. Suggests next steps or action items

Format the comment using Markdown with clear sections, headers, and bullet points for readability on GitHub."""
        
        # Create LLM
        llm = ChatGroq(model="openai/gpt-oss-120b")
        
        # Generate summary comment
        messages = [
            SystemMessage(content=FINAL_DRAFT_SYSTEM_PROMPT),
            HumanMessage(content=invocation_prompt)
        ]
        
        
        # Retry logic for rate limiting
        max_retries = 3
        retry_count = 0
        response = None
        
        while retry_count < max_retries:
            try:
                response = llm.invoke(messages)
                summary_comment = response.content if hasattr(response, 'content') else str(response)

                # Safely clean up generated diff files folder
                if diff_folder.exists():
                    # Ensure we are deleting a real directory and not a symlink to another location
                    if diff_folder.is_dir() and not diff_folder.is_symlink():
                        try:
                            shutil.rmtree(diff_folder)
                            logger.info(f"Output diff folder cleared at: {diff_folder}")
                        except Exception as cleanup_err:
                            logger.warning(f"Failed to clear diff folder at {diff_folder}: {cleanup_err}")
                    else:
                        logger.warning(f"Skipped diff folder cleanup because {diff_folder} is not a regular directory or is a symlink.")
                else:
                    logger.info(f"No diff folder found to clear at: {diff_folder}")

                break  # Success, exit retry loop
            except Exception as e:
                error_str = str(e)
                # Check if it's a rate limit error
                if "429" in error_str or "rate_limit" in error_str.lower() or "RateLimitError" in str(type(e).__name__):
                    retry_count += 1
                    if retry_count < max_retries:
                        # Wait 3-4 minutes (180-240 seconds) before retrying
                        wait_time = random.uniform(180, 240)  # 3-4 minutes
                        logger.warning(f"Rate limit error encountered. Waiting {wait_time:.1f} seconds ({wait_time/60:.1f} minutes) before retry {retry_count}/{max_retries}...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {max_retries} retries. Giving up.")
                        raise
                else:
                    # Not a rate limit error, re-raise immediately
                    raise
        
        if response is None:
            raise Exception("Failed to generate summary comment after retries")
        
        
        # Post the summary comment to GitHub PR
        
        from github import Github, Auth
        from dotenv import load_dotenv
        import os
        import re
        
        load_dotenv()
        
        # Get GitHub token
        token = os.getenv("GIT_WRITE_TOKEN") or os.getenv("GIT_TOKEN")
        if not token:
            raise ValueError("GIT_WRITE_TOKEN or GIT_TOKEN environment variable is required")
        
        # Initialize GitHub client
        g = Github(auth=Auth.Token(token))
        
        # Parse repository identifier
        if repo_link.startswith("http"):
            match = re.search(r'github\.com/([^/]+)/([^/]+)', repo_link)
            if match:
                repo_identifier = f"{match.group(1)}/{match.group(2).rstrip('/')}"
            else:
                raise ValueError(f"Invalid GitHub URL format: {repo_link}")
        else:
            repo_identifier = repo_link.rstrip('/')
        
        # Get repository and pull request
        repo = g.get_repo(repo_identifier)
        pr = repo.get_pull(pr_number)
        
        # Post comment using issue comments endpoint (general PR comment)
        # Format the comment with a header
        formatted_summary = f"""## 📋 Code Review Summary

{summary_comment}

---
*This summary was automatically generated by the Code Review Bot.*"""
        
        # Post the comment
        comment = pr.create_issue_comment(formatted_summary)
        
        logger.info("✅ Summary comment posted successfully")
        
        return formatted_summary
        
    except Exception as e:
        logger.error(f"Error in FinalDraftNode: {e}", exc_info=True)
        raise

