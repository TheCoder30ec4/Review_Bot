from typing import List, Tuple, Optional, Dict, Any
from pydantic import BaseModel, Field


class intial_state(BaseModel):
    """Initial state containing pull request information."""
    PullRequestLink: str = Field(
        description="The GitHub repository URL or link to the pull request. Example: 'https://github.com/owner/repo' or 'owner/repo'",
        examples=["https://github.com/TheCoder30ec4/OneForAll-MCP/", "owner/repo"]
    )
    PullRequestNum: int = Field(
        description="The pull request number. Example: 2, 123, 456",
        examples=[2, 123]
    )
    SessionId: Optional[str] = Field(
        description="Unique session ID for this review. Used to track memory across review runs.",
        default=None
    )


class CommentMetadata(BaseModel):
    """Metadata about a posted comment for tracking."""
    file_path: str
    criticality: str
    issue_summary: str
    comment_id: Optional[str] = None
    timestamp: str
    diff_code_hash: str  # Hash of the diff code to detect duplicates


class Global_State(BaseModel):
    """Global state tracking the code review process."""
    TotalFiles: int = Field(
        description="Total number of files in the pull request that need to be reviewed",
        examples=[10, 25, 50]
    )
    ReviewedFiles: List[str] = Field(
        description="List of file paths that have been reviewed. Each entry should be a relative file path from the repository root.",
        examples=[["Backend/app/main.py", "Frontend/src/App.tsx"], ["src/utils/helper.py"]],
        default_factory=list
    )
    CurrentFile: str = Field(
        description="The file path currently being reviewed. Should be a relative path from repository root. Empty string if no file is currently being reviewed.",
        examples=["Backend/app/api.py", "Frontend/src/components/Button.tsx", ""],
        default=""
    )
    RelaventContext: List[str] = Field(
        description="List of relevant context strings, code snippets, or explanations that are important for the current review. Each string can contain code context, explanations, or related information.",
        examples=[["Authentication logic in lines 10-25", "This function handles user login"], ["API endpoint definitions"]],
        default_factory=list
    )
    SkippedFiles: List[Tuple[str, str]] = Field(
        description="List of tuples containing file paths and reasons for skipping them. Each tuple is (file_path, reason). Files that were skipped during review should be listed here with their skip reason.",
        examples=[[("test.py", "Test file - not part of production code"), ("config.py", "Configuration file - no logic changes")], []],
        default_factory=list
    )
    IgnoreFiles: List[str] = Field(
        description="List of file paths that should be ignored and not reviewed. These are typically build artifacts, dependencies, or generated files.",
        examples=[["node_modules", "__pycache__", ".env", "dist/"], ["*.pyc", "venv/"]],
        default_factory=list
    )
    PostedComments: List[CommentMetadata] = Field(
        description="List of all comments posted during this review session for deduplication and tracking.",
        default_factory=list
    )
    FileReviewCounts: Dict[str, int] = Field(
        description="Dictionary tracking how many times each file has been reviewed to prevent excessive looping.",
        default_factory=dict
    )
    SessionId: Optional[str] = Field(
        description="Session ID for memory tracking across review runs.",
        default=None
    )
    