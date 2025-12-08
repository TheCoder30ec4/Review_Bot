"""Memory manager for tracking PR review sessions and history."""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from .logger import get_logger

# Get project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ReviewMemory(BaseModel):
    """Memory of a single review comment."""
    file_path: str
    criticality: str
    issue: str
    diff_code: str
    timestamp: str
    comment_id: Optional[str] = None
    comment_url: Optional[str] = None


class PRSession(BaseModel):
    """Session data for a pull request review."""
    session_id: str = Field(description="Unique session ID for this PR review")
    pr_number: int
    repo_link: str
    pr_title: str
    pr_description: str
    created_at: str
    last_updated: str
    total_files_reviewed: int = 0
    total_comments_posted: int = 0
    review_memories: List[ReviewMemory] = Field(default_factory=list)
    files_reviewed: List[str] = Field(default_factory=list)
    files_skipped: List[tuple[str, str]] = Field(default_factory=list)
    final_summary: Optional[str] = None
    status: str = "in_progress"  # in_progress, completed, failed


class MemoryManager:
    """Manager for PR review sessions and memory."""
    
    def __init__(self, storage_dir: Optional[Path] = None):
        """
        Initialize memory manager.
        
        Args:
            storage_dir: Directory to store memory files. Defaults to Output/memory/
        """
        self.logger = get_logger()
        self.storage_dir = storage_dir or (PROJECT_ROOT / "Output" / "memory")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"MemoryManager initialized with storage: {self.storage_dir}")
    
    def generate_session_id(self, repo_link: str, pr_number: int) -> str:
        """
        Generate unique session ID for a PR.
        
        Args:
            repo_link: Repository link
            pr_number: Pull request number
        
        Returns:
            Unique session ID (hash)
        """
        # Create a unique identifier from repo + PR number
        identifier = f"{repo_link}#{pr_number}"
        session_id = hashlib.md5(identifier.encode()).hexdigest()[:16]
        self.logger.debug(f"Generated session ID: {session_id} for {identifier}")
        return session_id
    
    def get_session_file(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self.storage_dir / f"session_{session_id}.json"
    
    def load_session(self, repo_link: str, pr_number: int) -> Optional[PRSession]:
        """
        Load existing session for a PR.
        
        Args:
            repo_link: Repository link
            pr_number: Pull request number
        
        Returns:
            PRSession if exists, None otherwise
        """
        session_id = self.generate_session_id(repo_link, pr_number)
        session_file = self.get_session_file(session_id)
        
        if not session_file.exists():
            self.logger.info(f"No existing session found for PR #{pr_number}")
            return None
        
        try:
            self.logger.info(f"Loading session from: {session_file}")
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            session = PRSession(**data)
            self.logger.info(f"Loaded session {session_id}: {session.total_comments_posted} comments, {session.total_files_reviewed} files reviewed")
            return session
        except Exception as e:
            self.logger.error(f"Error loading session {session_id}: {e}", exc_info=True)
            return None
    
    def create_session(
        self,
        repo_link: str,
        pr_number: int,
        pr_title: str,
        pr_description: str
    ) -> PRSession:
        """
        Create new session for a PR.
        
        Args:
            repo_link: Repository link
            pr_number: Pull request number
            pr_title: Pull request title
            pr_description: Pull request description
        
        Returns:
            New PRSession
        """
        session_id = self.generate_session_id(repo_link, pr_number)
        now = datetime.now().isoformat()
        
        session = PRSession(
            session_id=session_id,
            pr_number=pr_number,
            repo_link=repo_link,
            pr_title=pr_title,
            pr_description=pr_description,
            created_at=now,
            last_updated=now,
            status="in_progress"
        )
        
        self.logger.info(f"Created new session {session_id} for PR #{pr_number}")
        self.save_session(session)
        return session
    
    def save_session(self, session: PRSession) -> None:
        """
        Save session to disk.
        
        Args:
            session: PRSession to save
        """
        session_file = self.get_session_file(session.session_id)
        
        try:
            # Update last_updated timestamp
            session.last_updated = datetime.now().isoformat()
            
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session.model_dump(), f, indent=2)
            
            self.logger.debug(f"Saved session {session.session_id} to {session_file}")
        except Exception as e:
            self.logger.error(f"Error saving session {session.session_id}: {e}", exc_info=True)
            raise
    
    def add_review_memory(
        self,
        session: PRSession,
        file_path: str,
        criticality: str,
        issue: str,
        diff_code: str,
        comment_id: Optional[str] = None,
        comment_url: Optional[str] = None
    ) -> None:
        """
        Add a review memory to the session.
        
        Args:
            session: PRSession to update
            file_path: File that was reviewed
            criticality: Criticality level
            issue: Issue description
            diff_code: Code snippet
            comment_id: GitHub comment ID
            comment_url: GitHub comment URL
        """
        memory = ReviewMemory(
            file_path=file_path,
            criticality=criticality,
            issue=issue,
            diff_code=diff_code[:500],  # Limit size
            timestamp=datetime.now().isoformat(),
            comment_id=comment_id,
            comment_url=comment_url
        )
        
        session.review_memories.append(memory)
        session.total_comments_posted += 1
        
        if file_path not in session.files_reviewed:
            session.files_reviewed.append(file_path)
            session.total_files_reviewed += 1
        
        self.logger.info(f"Added review memory for {file_path} ({criticality})")
        self.save_session(session)
    
    def check_duplicate_comment(
        self,
        session: PRSession,
        file_path: str,
        issue: str,
        similarity_threshold: float = 0.8
    ) -> bool:
        """
        Check if a similar comment was already posted.
        
        Args:
            session: PRSession to check
            file_path: File being reviewed
            issue: Issue description
            similarity_threshold: Similarity threshold (0-1)
        
        Returns:
            True if duplicate found, False otherwise
        """
        for memory in session.review_memories:
            if memory.file_path == file_path:
                # Simple similarity check based on common words
                issue_words = set(issue.lower().split())
                memory_words = set(memory.issue.lower().split())
                
                if len(issue_words) == 0 or len(memory_words) == 0:
                    continue
                
                common_words = issue_words.intersection(memory_words)
                similarity = len(common_words) / max(len(issue_words), len(memory_words))
                
                if similarity >= similarity_threshold:
                    self.logger.warning(f"Duplicate comment detected for {file_path}: {similarity:.2f} similarity")
                    return True
        
        return False
    
    def get_file_review_count(self, session: PRSession, file_path: str) -> int:
        """
        Get the number of times a file has been reviewed.
        
        Args:
            session: PRSession to check
            file_path: File path to check
        
        Returns:
            Number of reviews for this file
        """
        count = sum(1 for m in session.review_memories if m.file_path == file_path)
        return count
    
    def complete_session(self, session: PRSession, final_summary: str) -> None:
        """
        Mark session as completed.
        
        Args:
            session: PRSession to complete
            final_summary: Final summary text
        """
        session.status = "completed"
        session.final_summary = final_summary
        self.save_session(session)
        self.logger.info(f"Session {session.session_id} marked as completed")
    
    def get_session_summary(self, session: PRSession) -> Dict[str, Any]:
        """
        Get a summary of the session.
        
        Args:
            session: PRSession to summarize
        
        Returns:
            Dictionary with session summary
        """
        critical_count = sum(1 for m in session.review_memories if m.criticality == "Critical")
        medium_count = sum(1 for m in session.review_memories if m.criticality == "Medium")
        ok_count = sum(1 for m in session.review_memories if m.criticality == "OK")
        
        return {
            "session_id": session.session_id,
            "pr_number": session.pr_number,
            "status": session.status,
            "created_at": session.created_at,
            "last_updated": session.last_updated,
            "total_files_reviewed": session.total_files_reviewed,
            "total_comments_posted": session.total_comments_posted,
            "critical_issues": critical_count,
            "medium_issues": medium_count,
            "ok_issues": ok_count,
            "files_reviewed": session.files_reviewed[:10],  # First 10 files
            "has_more_files": len(session.files_reviewed) > 10
        }


# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Get or create the global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

