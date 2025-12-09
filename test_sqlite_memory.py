#!/usr/bin/env python3
"""
Test script for SQLite Memory Manager

Run this script to verify that the SQLite memory manager works correctly.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_sqlite_memory_manager():
    """Test the SQLite memory manager functionality."""
    from WorkFlow.utils.memory_manager import MemoryManager

    print("🧪 Testing SQLite Memory Manager...")

    # Initialize memory manager
    manager = MemoryManager()
    print("✅ MemoryManager initialized")

    # Test database stats
    stats = manager.get_database_stats()
    print(f"📊 Database stats: {stats}")

    # Test session creation
    session = manager.create_session(
        repo_link="https://github.com/test/repo",
        pr_number=123,
        pr_title="Test PR",
        pr_description="Test description"
    )
    print(f"✅ Created session: {session.session_id}")

    # Test session loading
    loaded_session = manager.load_session("https://github.com/test/repo", 123)
    assert loaded_session is not None
    assert loaded_session.session_id == session.session_id
    print("✅ Session loading works")

    # Test adding review memory
    manager.add_review_memory(
        session=loaded_session,
        file_path="src/main.py",
        criticality="Medium",
        issue="Missing error handling",
        diff_code="def process():\n    pass",
        comment_id="12345",
        comment_url="https://github.com/test/repo/pull/123#discussion_r12345"
    )
    print("✅ Review memory added")

    # Test duplicate checking
    is_duplicate = manager.check_duplicate_comment(
        session=loaded_session,
        file_path="src/main.py",
        issue="Missing error handling"
    )
    assert is_duplicate == True
    print("✅ Duplicate detection works")

    # Test session summary
    summary = manager.get_session_summary(loaded_session)
    print(f"📈 Session summary: {summary}")

    # Test session completion
    manager.complete_session(loaded_session, "Review completed successfully")
    print("✅ Session completion works")

    # Verify final stats
    final_stats = manager.get_database_stats()
    print(f"📊 Final database stats: {final_stats}")

    print("\n🎉 All SQLite memory manager tests passed!")
    return True

def test_migration():
    """Test JSON to SQLite migration."""
    from WorkFlow.utils.memory_manager import MemoryManager

    print("\n🔄 Testing JSON migration...")

    manager = MemoryManager()

    # Test migration (will be no-op if no JSON files exist)
    migrated_count = manager.migrate_from_json()
    print(f"📁 Migration result: {migrated_count} sessions migrated")

    return True

if __name__ == "__main__":
    try:
        test_sqlite_memory_manager()
        test_migration()
        print("\n✅ All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

