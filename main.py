#!/usr/bin/env python3
"""
Code Review Bot - Main Entry Point

Enterprise-grade AI-powered code review automation using LangGraph.

Usage:
    python main.py --pr-url "https://github.com/owner/repo/pull/123"
    python main.py --help
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from WorkFlow.Flow import create_workflow


def validate_environment():
    """Validate required environment variables."""
    required_vars = ['GIT_TOKEN']
    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\nSet them using:")
        print("   export GIT_TOKEN='your_github_token'")
        print("   export GIT_WRITE_TOKEN='your_write_token'  # Optional")
        sys.exit(1)

    print("✅ Environment validation passed")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="AI-Powered Code Review Bot using LangGraph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --pr-url "https://github.com/microsoft/vscode/pull/150000"
  python main.py --repo "owner/repo" --pr-number 123
  python main.py --help
        """
    )

    parser.add_argument(
        '--pr-url',
        type=str,
        help='Full GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)'
    )

    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in owner/repo format'
    )

    parser.add_argument(
        '--pr-number',
        type=int,
        help='Pull request number'
    )

    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Validate environment and exit'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='Code Review Bot v0.1.0'
    )

    return parser.parse_args()


def extract_pr_details(pr_url: str = None, repo: str = None, pr_number: int = None):
    """Extract PR details from arguments."""

    if pr_url:
        # Parse URL: https://github.com/owner/repo/pull/123
        try:
            parts = pr_url.rstrip('/').split('/')
            if len(parts) >= 5 and parts[3] == 'pull':
                repo = f"{parts[4]}/{parts[5]}"
                pr_number = int(parts[7])
            else:
                raise ValueError("Invalid PR URL format")
        except (IndexError, ValueError) as e:
            print(f"❌ Invalid PR URL format: {e}")
            print("Expected: https://github.com/owner/repo/pull/123")
            sys.exit(1)
    elif not (repo and pr_number):
        print("❌ Must provide either --pr-url OR both --repo and --pr-number")
        sys.exit(1)

    # Validate repo format
    if '/' not in repo or len(repo.split('/')) != 2:
        print("❌ Invalid repo format. Expected: owner/repo")
        sys.exit(1)

    return repo, pr_number


def main():
    """Main entry point for the code review bot."""
    print("🤖 Code Review Bot v0.1.0")
    print("Enterprise-grade AI-powered code review automation\n")

    args = parse_arguments()

    # Validate environment
    validate_environment()

    if args.validate_only:
        print("✅ Environment validation complete")
        return

    # Extract PR details
    try:
        repo, pr_number = extract_pr_details(args.pr_url, args.repo, args.pr_number)
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
    except Exception as e:
        print(f"❌ Failed to extract PR details: {e}")
        sys.exit(1)

    print("📋 PR Details:")
    print(f"   Repository: {repo}")
    print(f"   PR Number: {pr_number}")
    print(f"   PR URL: {pr_url}")
    print()

    # Create and execute workflow
    try:
        print("🏗️ Creating LangGraph workflow...")
        workflow = create_workflow()
        app = workflow.compile()

        print("🚀 Executing code review...")
        print("   This may take several minutes depending on PR size...\n")

        initial_state = {
            "PullRequestLink": pr_url,
            "PullRequestNum": pr_number
        }

        result = app.invoke({
            "initial_state": initial_state,
            "global_state": {}
        })

        print("\n✅ Code review completed successfully!")
        print("📝 Check GitHub PR for review comments")
        print("📊 Review logs available in ./logs/ directory")

    except KeyboardInterrupt:
        print("\n⚠️ Review interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Review failed: {e}")
        print("📋 Check logs in ./logs/ directory for details")
        sys.exit(1)


if __name__ == "__main__":
    main()
