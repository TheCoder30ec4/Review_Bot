"""
Custom exceptions for the code review bot.
"""

from typing import Optional


class CodeReviewBotError(Exception):
    """Base exception for code review bot errors."""
    pass


class GitHubAPIError(CodeReviewBotError):
    """Exception raised for GitHub API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class FileReadError(CodeReviewBotError):
    """Exception raised when file reading fails."""
    def __init__(self, file_path: str, message: Optional[str] = None):
        self.file_path = file_path
        super().__init__(message or f"Failed to read file: {file_path}")


class LLMError(CodeReviewBotError):
    """Exception raised for LLM-related errors."""
    def __init__(self, message: str, provider: Optional[str] = None):
        self.provider = provider
        super().__init__(message)


class ValidationError(CodeReviewBotError):
    """Exception raised for validation failures."""
    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        super().__init__(message)


class MemoryError(CodeReviewBotError):
    """Exception raised for memory/persistence errors."""
    def __init__(self, message: str, operation: Optional[str] = None):
        self.operation = operation
        super().__init__(message)


class ConfigurationError(CodeReviewBotError):
    """Exception raised for configuration issues."""
    def __init__(self, message: str, config_key: Optional[str] = None):
        self.config_key = config_key
        super().__init__(message)


class ReflexionError(CodeReviewBotError):
    """Exception raised for reflexion validation failures."""
    def __init__(self, message: str, confidence: Optional[float] = None):
        self.confidence = confidence
        super().__init__(message)


class SessionError(CodeReviewBotError):
    """Exception raised for session management errors."""
    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)
