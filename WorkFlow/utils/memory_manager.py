"""Memory manager for tracking PR review sessions and history using SQLite3."""

import sqlite3
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
    """Manager for PR review sessions and memory using SQLite3."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize memory manager with SQLite database.

        Args:
            db_path: Path to SQLite database file. Defaults to Output/memory.db
        """
        self.logger = get_logger()
        self.db_path = db_path or (PROJECT_ROOT / "Output" / "memory.db")

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()
        self.logger.info(f"MemoryManager initialized with SQLite database: {self.db_path}")

    def _init_database(self):
        """Initialize SQLite database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    pr_number INTEGER NOT NULL,
                    repo_link TEXT NOT NULL,
                    pr_title TEXT NOT NULL,
                    pr_description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    total_files_reviewed INTEGER DEFAULT 0,
                    total_comments_posted INTEGER DEFAULT 0,
                    final_summary TEXT,
                    status TEXT DEFAULT 'in_progress',
                    UNIQUE(repo_link, pr_number)
                )
            ''')

            # Create review_memories table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS review_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    criticality TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    diff_code TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    comment_id TEXT,
                    comment_url TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            ''')

            # Create files_reviewed table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files_reviewed (
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    PRIMARY KEY (session_id, file_path),
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            ''')

            # Create files_skipped table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files_skipped (
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (session_id, file_path),
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            ''')

            conn.commit()
            self.logger.debug("Database tables initialized")

    def migrate_from_json(self) -> int:
        """
        Migrate existing JSON session files to SQLite database.

        Returns:
            Number of sessions migrated
        """
        import json

        json_dir = PROJECT_ROOT / "Output" / "memory"
        migrated_count = 0

        if not json_dir.exists():
            self.logger.info("No JSON files found to migrate")
            return 0

        json_files = list(json_dir.glob("session_*.json"))

        for json_file in json_files:
            try:
                self.logger.info(f"Migrating {json_file.name}...")

                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Create session in database
                session = PRSession(**data)
                self._save_session_to_db(session)
                migrated_count += 1

                # Backup original file
                backup_file = json_file.with_suffix('.json.backup')
                json_file.rename(backup_file)
                self.logger.info(f"Backed up {json_file.name} to {backup_file.name}")

            except Exception as e:
                self.logger.error(f"Error migrating {json_file.name}: {e}", exc_info=True)

        self.logger.info(f"Migration complete: {migrated_count} sessions migrated")
        return migrated_count

    def _save_session_to_db(self, session: PRSession) -> None:
        """Internal method to save session directly to database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Insert session
            cursor.execute('''
                INSERT OR REPLACE INTO sessions
                (session_id, pr_number, repo_link, pr_title, pr_description,
                 created_at, last_updated, total_files_reviewed, total_comments_posted,
                 final_summary, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.session_id, session.pr_number, session.repo_link,
                session.pr_title, session.pr_description, session.created_at,
                session.last_updated, session.total_files_reviewed,
                session.total_comments_posted, session.final_summary, session.status
            ))

            # Insert review memories
            for memory in session.review_memories:
                cursor.execute('''
                    INSERT INTO review_memories
                    (session_id, file_path, criticality, issue, diff_code,
                     timestamp, comment_id, comment_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session.session_id, memory.file_path, memory.criticality,
                    memory.issue, memory.diff_code, memory.timestamp,
                    memory.comment_id, memory.comment_url
                ))

            # Insert files reviewed
            for file_path in session.files_reviewed:
                cursor.execute(
                    "INSERT OR IGNORE INTO files_reviewed (session_id, file_path) VALUES (?, ?)",
                    (session.session_id, file_path)
                )

            # Insert files skipped
            for file_path, reason in session.files_skipped:
                cursor.execute(
                    "INSERT OR IGNORE INTO files_skipped (session_id, file_path, reason) VALUES (?, ?, ?)",
                    (session.session_id, file_path, reason)
                )

            conn.commit()

    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with database statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                stats = {}

                # Count sessions
                cursor.execute("SELECT COUNT(*) FROM sessions")
                stats['total_sessions'] = cursor.fetchone()[0]

                # Count review memories
                cursor.execute("SELECT COUNT(*) FROM review_memories")
                stats['total_review_memories'] = cursor.fetchone()[0]

                # Count unique files reviewed
                cursor.execute("SELECT COUNT(DISTINCT file_path) FROM files_reviewed")
                stats['unique_files_reviewed'] = cursor.fetchone()[0]

                # Sessions by status
                cursor.execute("SELECT status, COUNT(*) FROM sessions GROUP BY status")
                stats['sessions_by_status'] = {row[0]: row[1] for row in cursor.fetchall()}

                # Database file size
                import os
                stats['database_size_mb'] = os.path.getsize(self.db_path) / (1024 * 1024)

                return stats

        except Exception as e:
            self.logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {}

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
    
    def load_session(self, repo_link: str, pr_number: int) -> Optional[PRSession]:
        """
        Load existing session for a PR from SQLite database.

        Args:
            repo_link: Repository link
            pr_number: Pull request number

        Returns:
            PRSession if exists, None otherwise
        """
        session_id = self.generate_session_id(repo_link, pr_number)

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Load session data
                cursor.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,)
                )
                session_row = cursor.fetchone()

                if not session_row:
                    self.logger.info(f"No existing session found for PR #{pr_number}")
                    return None

                # Load review memories
                cursor.execute(
                    "SELECT file_path, criticality, issue, diff_code, timestamp, comment_id, comment_url FROM review_memories WHERE session_id = ? ORDER BY timestamp",
                    (session_id,)
                )
                memory_rows = cursor.fetchall()

                # Load files reviewed
                cursor.execute(
                    "SELECT file_path FROM files_reviewed WHERE session_id = ?",
                    (session_id,)
                )
                files_reviewed = [row[0] for row in cursor.fetchall()]

                # Load files skipped
                cursor.execute(
                    "SELECT file_path, reason FROM files_skipped WHERE session_id = ?",
                    (session_id,)
                )
                files_skipped = [(row[0], row[1]) for row in cursor.fetchall()]

                # Convert to PRSession object
                review_memories = [
                    ReviewMemory(
                        file_path=row[0],
                        criticality=row[1],
                        issue=row[2],
                        diff_code=row[3],
                        timestamp=row[4],
                        comment_id=row[5],
                        comment_url=row[6]
                    )
                    for row in memory_rows
                ]

                session = PRSession(
                    session_id=session_row[0],
                    pr_number=session_row[1],
                    repo_link=session_row[2],
                    pr_title=session_row[3],
                    pr_description=session_row[4],
                    created_at=session_row[5],
                    last_updated=session_row[6],
                    total_files_reviewed=session_row[7],
                    total_comments_posted=session_row[8],
                    review_memories=review_memories,
                    files_reviewed=files_reviewed,
                    files_skipped=files_skipped,
                    final_summary=session_row[9],
                    status=session_row[10]
                )

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
        Create new session for a PR in SQLite database.

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

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Insert session
                cursor.execute('''
                    INSERT INTO sessions
                    (session_id, pr_number, repo_link, pr_title, pr_description, created_at, last_updated, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session_id, pr_number, repo_link, pr_title, pr_description, now, now, "in_progress"))

                conn.commit()

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
                return session

        except sqlite3.IntegrityError:
            # Session already exists
            self.logger.warning(f"Session {session_id} already exists, loading instead")
            return self.load_session(repo_link, pr_number)
        except Exception as e:
            self.logger.error(f"Error creating session {session_id}: {e}", exc_info=True)
            raise
    
    def save_session(self, session: PRSession) -> None:
        """
        Save session to SQLite database.

        Args:
            session: PRSession to save
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Update last_updated timestamp
                session.last_updated = datetime.now().isoformat()

                # Update session data
                cursor.execute('''
                    UPDATE sessions SET
                        last_updated = ?,
                        total_files_reviewed = ?,
                        total_comments_posted = ?,
                        final_summary = ?,
                        status = ?
                    WHERE session_id = ?
                ''', (
                    session.last_updated,
                    session.total_files_reviewed,
                    session.total_comments_posted,
                    session.final_summary,
                    session.status,
                    session.session_id
                ))

                # Clear and re-insert files_reviewed
                cursor.execute("DELETE FROM files_reviewed WHERE session_id = ?", (session.session_id,))
                for file_path in session.files_reviewed:
                    cursor.execute(
                        "INSERT INTO files_reviewed (session_id, file_path) VALUES (?, ?)",
                        (session.session_id, file_path)
                    )

                # Clear and re-insert files_skipped
                cursor.execute("DELETE FROM files_skipped WHERE session_id = ?", (session.session_id,))
                for file_path, reason in session.files_skipped:
                    cursor.execute(
                        "INSERT INTO files_skipped (session_id, file_path, reason) VALUES (?, ?, ?)",
                        (session.session_id, file_path, reason)
                    )

                conn.commit()
                self.logger.debug(f"Saved session {session.session_id} to database")

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
        Add a review memory to the session in SQLite database.

        Args:
            session: PRSession to update
            file_path: File that was reviewed
            criticality: Criticality level
            issue: Issue description
            diff_code: Code snippet
            comment_id: GitHub comment ID
            comment_url: GitHub comment URL
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                timestamp = datetime.now().isoformat()

                # Insert review memory
                cursor.execute('''
                    INSERT INTO review_memories
                    (session_id, file_path, criticality, issue, diff_code, timestamp, comment_id, comment_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session.session_id,
                    file_path,
                    criticality,
                    issue,
                    diff_code[:500],  # Limit size
                    timestamp,
                    comment_id,
                    comment_url
                ))

                # Update session counters
                session.total_comments_posted += 1

                # Check if file is already reviewed
                cursor.execute(
                    "SELECT COUNT(*) FROM files_reviewed WHERE session_id = ? AND file_path = ?",
                    (session.session_id, file_path)
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "INSERT INTO files_reviewed (session_id, file_path) VALUES (?, ?)",
                        (session.session_id, file_path)
                    )
                    session.total_files_reviewed += 1

                # Update session counters in database
                cursor.execute('''
                    UPDATE sessions SET
                        total_files_reviewed = ?,
                        total_comments_posted = ?,
                        last_updated = ?
                    WHERE session_id = ?
                ''', (
                    session.total_files_reviewed,
                    session.total_comments_posted,
                    timestamp,
                    session.session_id
                ))

                conn.commit()

                # Update in-memory session object
                memory = ReviewMemory(
                    file_path=file_path,
                    criticality=criticality,
                    issue=issue,
                    diff_code=diff_code[:500],
                    timestamp=timestamp,
                    comment_id=comment_id,
                    comment_url=comment_url
                )
                session.review_memories.append(memory)

                if file_path not in session.files_reviewed:
                    session.files_reviewed.append(file_path)

                self.logger.info(f"Added review memory for {file_path} ({criticality})")

        except Exception as e:
            self.logger.error(f"Error adding review memory: {e}", exc_info=True)
            raise
    
    def check_duplicate_comment(
        self,
        session: PRSession,
        file_path: str,
        issue: str,
        similarity_threshold: float = 0.8
    ) -> bool:
        """
        Check if a similar comment was already posted for this file.

        Args:
            session: PRSession to check
            file_path: File being reviewed
            issue: Issue description
            similarity_threshold: Similarity threshold (0-1)

        Returns:
            True if duplicate found, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get existing issues for this file in the session
                cursor.execute(
                    "SELECT issue FROM review_memories WHERE session_id = ? AND file_path = ?",
                    (session.session_id, file_path)
                )

                existing_issues = [row[0] for row in cursor.fetchall()]

                # Check similarity with each existing issue
                issue_words = set(issue.lower().split())
                for existing_issue in existing_issues:
                    memory_words = set(existing_issue.lower().split())

                    if len(issue_words) == 0 or len(memory_words) == 0:
                        continue

                    common_words = issue_words.intersection(memory_words)
                    similarity = len(common_words) / max(len(issue_words), len(memory_words))

                    if similarity >= similarity_threshold:
                        self.logger.warning(f"Duplicate comment detected for {file_path}: {similarity:.2f} similarity")
                        return True

                return False

        except Exception as e:
            self.logger.error(f"Error checking duplicate comment: {e}", exc_info=True)
            return False
    
    def get_file_review_count(self, session: PRSession, file_path: str) -> int:
        """
        Get the number of times a file has been reviewed from SQLite database.

        Args:
            session: PRSession to check
            file_path: File path to check

        Returns:
            Number of reviews for this file
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM review_memories WHERE session_id = ? AND file_path = ?",
                    (session.session_id, file_path)
                )
                return cursor.fetchone()[0]
        except Exception as e:
            self.logger.error(f"Error getting file review count: {e}", exc_info=True)
            return 0
    
    def complete_session(self, session: PRSession, final_summary: str) -> None:
        """
        Mark session as completed in SQLite database.

        Args:
            session: PRSession to complete
            final_summary: Final summary text
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE sessions SET
                        status = 'completed',
                        final_summary = ?,
                        last_updated = ?
                    WHERE session_id = ?
                ''', (
                    final_summary,
                    datetime.now().isoformat(),
                    session.session_id
                ))

                conn.commit()

                # Update in-memory session object
                session.status = "completed"
                session.final_summary = final_summary

                self.logger.info(f"Session {session.session_id} marked as completed")

        except Exception as e:
            self.logger.error(f"Error completing session {session.session_id}: {e}", exc_info=True)
            raise
    
    def get_session_summary(self, session: PRSession) -> Dict[str, Any]:
        """
        Get a summary of the session from SQLite database.

        Args:
            session: PRSession to summarize

        Returns:
            Dictionary with session summary
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get criticality counts from database
                cursor.execute('''
                    SELECT criticality, COUNT(*) as count
                    FROM review_memories
                    WHERE session_id = ?
                    GROUP BY criticality
                ''', (session.session_id,))

                criticality_counts = {row[0]: row[1] for row in cursor.fetchall()}

                # Get files reviewed count from database
                cursor.execute(
                    "SELECT COUNT(*) FROM files_reviewed WHERE session_id = ?",
                    (session.session_id,)
                )
                total_files_reviewed = cursor.fetchone()[0]

                # Get first 10 files reviewed
                cursor.execute(
                    "SELECT file_path FROM files_reviewed WHERE session_id = ? LIMIT 10",
                    (session.session_id,)
                )
                files_reviewed = [row[0] for row in cursor.fetchall()]

                cursor.execute(
                    "SELECT COUNT(*) FROM files_reviewed WHERE session_id = ?",
                    (session.session_id,)
                )
                total_files_count = cursor.fetchone()[0]

                return {
                    "session_id": session.session_id,
                    "pr_number": session.pr_number,
                    "status": session.status,
                    "created_at": session.created_at,
                    "last_updated": session.last_updated,
                    "total_files_reviewed": total_files_reviewed,
                    "total_comments_posted": session.total_comments_posted,
                    "critical_issues": criticality_counts.get("Critical", 0),
                    "medium_issues": criticality_counts.get("Medium", 0),
                    "ok_issues": criticality_counts.get("OK", 0),
                    "files_reviewed": files_reviewed,
                    "has_more_files": total_files_count > 10
                }

        except Exception as e:
            self.logger.error(f"Error getting session summary: {e}", exc_info=True)
            # Fallback to in-memory calculation
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
                "files_reviewed": session.files_reviewed[:10],
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

