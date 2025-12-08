"""Utility for parsing and cleaning diff code snippets."""

import re
from typing import Tuple, Optional


def clean_diff_code(diff_code: str) -> str:
    """
    Clean diff code by removing diff markers and formatting properly.
    
    Args:
        diff_code: Raw diff code with potential markers
    
    Returns:
        Cleaned code without diff markers
    """
    if not diff_code or not diff_code.strip():
        return ""
    
    lines = diff_code.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Skip diff header lines
        if line.startswith('@@') or line.startswith('diff ') or line.startswith('index '):
            continue
        
        # Remove diff markers but preserve the rest
        if line.startswith('+'):
            # Addition - remove the + but keep the code
            cleaned_lines.append(line[1:])
        elif line.startswith('-'):
            # Deletion - skip these for now (could include in context if needed)
            continue
        elif line.startswith(' '):
            # Context line - remove the leading space
            cleaned_lines.append(line[1:])
        else:
            # No marker - keep as is
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


def extract_code_from_diff(diff_content: str, max_lines: int = 50) -> str:
    """
    Extract clean code from a diff, focusing on additions.
    
    Args:
        diff_content: Full diff content
        max_lines: Maximum number of lines to extract
    
    Returns:
        Cleaned code snippet
    """
    if not diff_content:
        return ""
    
    lines = diff_content.split('\n')
    code_lines = []
    in_hunk = False
    
    for line in lines:
        # Detect hunk header
        if line.startswith('@@'):
            in_hunk = True
            continue
        
        if not in_hunk:
            continue
        
        # Stop at next file or end
        if line.startswith('diff ') or line.startswith('index '):
            break
        
        # Extract additions and context
        if line.startswith('+'):
            code_lines.append(line[1:])  # Remove +
        elif line.startswith(' '):
            code_lines.append(line[1:])  # Remove leading space (context)
        # Skip deletions (-)
    
    # Limit lines
    if len(code_lines) > max_lines:
        code_lines = code_lines[:max_lines]
    
    return '\n'.join(code_lines)


def validate_code_snippet(code_snippet: str, file_extension: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validate that a code snippet looks reasonable.
    
    Args:
        code_snippet: Code to validate
        file_extension: File extension (e.g., 'py', 'js') for language-specific checks
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not code_snippet or not code_snippet.strip():
        return False, "Code snippet is empty"
    
    # Check for diff markers that shouldn't be there
    diff_markers = ['+', '-', '@@']
    first_chars = [line[0] if line else '' for line in code_snippet.split('\n') if line]
    
    # If more than 50% of lines start with diff markers, it's not cleaned properly
    marker_count = sum(1 for char in first_chars if char in diff_markers)
    if len(first_chars) > 0 and marker_count / len(first_chars) > 0.5:
        return False, "Code snippet contains too many diff markers (not properly cleaned)"
    
    # Check for hunk headers
    if '@@' in code_snippet:
        return False, "Code snippet contains hunk headers (@@)"
    
    # Basic syntax checks based on file type
    if file_extension:
        ext = file_extension.lower().lstrip('.')
        
        if ext in ['py', 'python']:
            # Python-specific checks
            # Check for basic syntax elements
            if 'def ' in code_snippet or 'class ' in code_snippet or 'import ' in code_snippet:
                # Looks like Python code
                pass
        
        elif ext in ['js', 'javascript', 'ts', 'typescript']:
            # JavaScript/TypeScript checks
            if 'function ' in code_snippet or 'const ' in code_snippet or '=>' in code_snippet:
                # Looks like JS/TS code
                pass
    
    # Check minimum length (at least 10 characters for meaningful code)
    if len(code_snippet.strip()) < 10:
        return False, "Code snippet is too short to be meaningful"
    
    # Check maximum length (prevent extremely large snippets)
    if len(code_snippet) > 5000:
        return False, "Code snippet is too long (over 5000 characters)"
    
    return True, ""


def extract_function_or_class_context(diff_content: str) -> Optional[str]:
    """
    Try to extract the function or class definition from diff for better context.
    
    Args:
        diff_content: Diff content
    
    Returns:
        Function/class definition line or None
    """
    lines = diff_content.split('\n')
    
    for line in lines:
        clean_line = line.lstrip('+ -')
        
        # Look for function/method definitions
        if re.match(r'\s*(def|function|class|interface|type)\s+\w+', clean_line):
            return clean_line.strip()
    
    return None


def get_code_language_from_path(file_path: str) -> Optional[str]:
    """
    Determine programming language from file path.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Language name or None
    """
    extension_map = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'jsx': 'javascript',
        'tsx': 'typescript',
        'java': 'java',
        'cpp': 'cpp',
        'c': 'c',
        'go': 'go',
        'rs': 'rust',
        'rb': 'ruby',
        'php': 'php',
        'cs': 'csharp',
        'swift': 'swift',
        'kt': 'kotlin',
        'scala': 'scala',
        'r': 'r',
        'sql': 'sql',
        'sh': 'bash',
        'bash': 'bash',
        'yml': 'yaml',
        'yaml': 'yaml',
        'json': 'json',
        'xml': 'xml',
        'html': 'html',
        'css': 'css',
        'scss': 'scss',
        'vue': 'vue',
        'dart': 'dart'
    }
    
    if '.' not in file_path:
        return None
    
    ext = file_path.split('.')[-1].lower()
    return extension_map.get(ext)

