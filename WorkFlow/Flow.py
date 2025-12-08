"""LangGraph workflow for code review process."""

import sys
import hashlib
from pathlib import Path
from typing import TypedDict
from datetime import datetime
from langgraph.graph import StateGraph, END

# Add project root to path for direct folder imports
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))

from WorkFlow.State import intial_state, Global_State, CommentMetadata
from WorkFlow.nodes.Fetch_PR_node.FetchPrState import FetchState
from WorkFlow.nodes.Fetch_PR_node.FetchPrNode import FetchNode
from WorkFlow.nodes.Parse_files_node.ParseFileState import ParseState
from WorkFlow.nodes.Parse_files_node.ParseFileNode import ParseFileNode
from WorkFlow.nodes.Review_file_node.ReviewFileNode import ReviewFileNode
from WorkFlow.nodes.Reflexion_node.ReflexionNode import ReflexionNode
from WorkFlow.utils.logger import get_logger
from WorkFlow.utils.memory_manager import get_memory_manager


class WorkflowState(TypedDict):
    """Combined state for the workflow."""
    initial_state: intial_state
    global_state: Global_State
    fetch_state: FetchState
    parse_state: ParseState


def fetch_pr_node(state: WorkflowState) -> WorkflowState:
    """
    Node that fetches pull request details and initializes session.
    
    Args:
        state: Current workflow state
    
    Returns:
        Updated workflow state with PR details and session
    """
    logger = get_logger()
    logger.info("Fetching PR details...")
    
    initial = state["initial_state"]
    global_state = state["global_state"]
    
    # Call FetchNode
    initial_result, updated_global, fetch_state = FetchNode(initial, global_state)
    
    # Initialize or load session from memory
    memory_manager = get_memory_manager()
    session = memory_manager.load_session(
        repo_link=initial.PullRequestLink,
        pr_number=initial.PullRequestNum
    )
    
    if session:
        logger.info(f"Resumed session: {session.session_id} ({session.total_comments_posted} comments posted)")
        # Update initial and global state with session ID
        initial_result.SessionId = session.session_id
        updated_global.SessionId = session.session_id
    else:
        logger.info("New review session will be created")
        # Session will be created in parse_files_node once we have PR details
    
    # Update state
    return {
        "initial_state": initial_result,
        "global_state": updated_global,
        "fetch_state": fetch_state,
        "parse_state": state.get("parse_state")  # Keep existing parse_state if any
    }


def parse_files_node(state: WorkflowState) -> WorkflowState:
    """
    Node that parses files and decides which to review and which to skip.
    Creates session if not exists.
    
    Args:
        state: Current workflow state
    
    Returns:
        Updated workflow state with parsed file information
    """
    logger = get_logger()
    logger.info("Executing parse_files_node...")
    
    initial_state = state["initial_state"]
    fetch_state = state["fetch_state"]
    global_state = state["global_state"]
    
    # Call ParseFileNode
    updated_global, parse_state = ParseFileNode(fetch_state, global_state)
    
    # Create or update session
    memory_manager = get_memory_manager()
    if not global_state.SessionId:
        session = memory_manager.create_session(
            repo_link=initial_state.PullRequestLink,
            pr_number=initial_state.PullRequestNum,
            pr_title=fetch_state.PrRequest.Title,
            pr_description=fetch_state.PrRequest.Description
        )
        updated_global.SessionId = session.session_id
        logger.info(f"Created new session: {session.session_id}")
    
    # Update state
    return {
        "initial_state": initial_state,
        "global_state": updated_global,
        "fetch_state": fetch_state,
        "parse_state": parse_state
    }


def review_files_node(state: WorkflowState) -> WorkflowState:
    """
    Node that reviews each selected file in a loop with reflexion, memory, and hallucination guards.
    
    Args:
        state: Current workflow state
    
    Returns:
        Updated workflow state with reviewed files
    """
    logger = get_logger()
    logger.info("Executing review_files_node with reflexion and memory...")
    
    parse_state = state["parse_state"]
    global_state = state["global_state"]
    fetch_state = state["fetch_state"]
    initial_state = state["initial_state"]
    
    selected_files = parse_state.SelectedFilePath
    workspace_path = parse_state.RootWorkSpace
    
    if not selected_files:
        logger.warning("No files selected for review")
        return state
    
    logger.info(f"Reviewing {len(selected_files)} files with enhanced validation")
    
    # Initialize memory manager
    memory_manager = get_memory_manager()
    session = memory_manager.load_session(
        repo_link=initial_state.PullRequestLink,
        pr_number=initial_state.PullRequestNum
    )
    
    if not session:
        # Create session if not exists
        session = memory_manager.create_session(
            repo_link=initial_state.PullRequestLink,
            pr_number=initial_state.PullRequestNum,
            pr_title=fetch_state.PrRequest.Title,
            pr_description=fetch_state.PrRequest.Description
        )
        global_state.SessionId = session.session_id
    
    # Get all available files for finding relevant files
    from pathlib import Path
    all_files = []
    workspace_dir = Path(workspace_path)
    if not workspace_dir.is_absolute():
        workspace_dir = project_root / workspace_path
    
    if workspace_dir.exists():
        for txt_file in workspace_dir.rglob("*.txt"):
            rel_path = txt_file.relative_to(workspace_dir)
            file_path_str = str(rel_path).replace(".txt", "")
            all_files.append(file_path_str)
    
    
    # Loop through each selected file and review it
    current_global_state = global_state
    from WorkFlow.nodes.Conditional_continue_node.ConditionalNode import ConditionalNode
    from WorkFlow.tools.ReadFileTool import read_file_tool
    from WorkFlow.tools.GitCommentTool import post_code_review_comment_tool
    
    # Hallucination guard: Max comments per file
    MAX_COMMENTS_PER_FILE = 3
    # Hallucination guard: Min confidence threshold
    MIN_CONFIDENCE_THRESHOLD = 0.6
    
    for file_path in selected_files:
        
        # Check if file has been reviewed too many times (loop prevention)
        file_review_count = memory_manager.get_file_review_count(session, file_path)
        if file_review_count >= MAX_COMMENTS_PER_FILE:
            logger.warning(f"File {file_path} has been reviewed {file_review_count} times. Skipping to prevent looping.")
            continue
        
        # Read file content
        file_result = read_file_tool.invoke({
            "file_path": file_path,
            "workspace_path": workspace_path
        })
        file_content = file_result.get("content", "") if file_result.get("success") else ""
        
        if not file_result.get("success"):
            logger.error(f"Failed to read file {file_path}: {file_result.get('error')}")
            continue
        
        # Initial review
        current_global_state, review_state = ReviewFileNode(
            file_path=file_path,
            global_state=current_global_state,
            workspace_path=workspace_path,
            pr_title=fetch_state.PrRequest.Title,
            pr_description=fetch_state.PrRequest.Description,
            repo_link=initial_state.PullRequestLink,
            pr_number=initial_state.PullRequestNum,
            all_files=all_files
        )
        
        # REFLEXION: Validate review before posting with retry mechanism
        reflexion_approved = False  # Track if reflexion approved this review

        if review_state.CriticalityStatus in ["Medium", "Critical"]:
            max_reflexion_retries = 2
            reflexion_retry_count = 0

            while reflexion_retry_count <= max_reflexion_retries:
                pr_context = {
                    "pr_title": fetch_state.PrRequest.Title,
                    "pr_description": fetch_state.PrRequest.Description
                }

                is_valid, validated_review_state, confidence, validation_issues = ReflexionNode(
                    review_state=review_state,
                    file_content=file_content,
                    pr_context=pr_context
                )

                if is_valid and confidence >= MIN_CONFIDENCE_THRESHOLD:
                    # ✅ REFLEXION APPROVED: Validation passed, use the validated review state
                    review_state = validated_review_state
                    reflexion_approved = True  # Mark as approved by reflexion
                    logger.info(f"✅ Reflexion approved review for {file_path} (confidence: {confidence:.2f})")
                    break

                # ❌ REFLEXION REJECTED: Validation failed
                reflexion_retry_count += 1
                logger.warning(f"❌ Reflexion rejected review (attempt {reflexion_retry_count}/{max_reflexion_retries + 1}) - confidence: {confidence:.2f}")
                logger.warning(f"Validation issues: {', '.join(validation_issues)}")

                if reflexion_retry_count > max_reflexion_retries:
                    logger.warning(f"❌ All reflexion retries exhausted. Review NOT approved for {file_path}.")
                    reflexion_approved = False  # Explicitly mark as not approved
                    break

                # Retry: Call ReviewFileNode again with validation issues as additional context
                logger.info(f"🔄 Retrying review generation for {file_path} with validation feedback...")

                retry_context = {
                    "validation_failed": True,
                    "validation_issues": validation_issues,
                    "previous_confidence": confidence,
                    "retry_attempt": reflexion_retry_count
                }

                # Re-call ReviewFileNode with retry context
                current_global_state, review_state = ReviewFileNode(
                    file_path=file_path,
                    global_state=current_global_state,
                    workspace_path=workspace_path,
                    pr_title=fetch_state.PrRequest.Title,
                    pr_description=fetch_state.PrRequest.Description,
                    repo_link=initial_state.PullRequestLink,
                    pr_number=initial_state.PullRequestNum,
                    all_files=all_files,
                    retry_context=retry_context  # Pass retry context
                )

            # If we still don't have a valid review after retries, skip
            if not reflexion_approved:
                logger.info(f"⏭️ Skipping comment for {file_path} - reflexion did not approve")
                continue
            
            # Check for duplicate comments using memory
            diff_code_hash = hashlib.md5(review_state.DiffCode.encode()).hexdigest()
            issue_summary = review_state.WhatNeedsToBeImproved[:100]
            
            if memory_manager.check_duplicate_comment(session, file_path, issue_summary):
                logger.warning(f"Duplicate comment detected for {file_path}. Skipping.")
                continue
            
            # Check against current session's posted comments
            is_duplicate = False
            for posted_comment in current_global_state.PostedComments:
                if posted_comment.file_path == file_path and posted_comment.diff_code_hash == diff_code_hash:
                    logger.warning(f"Duplicate comment detected in current session for {file_path}. Skipping.")
                    is_duplicate = True
                    break
            
            if is_duplicate:
                continue

            # 🔐 FINAL APPROVAL CHECK: Only post if reflexion approved
            if not reflexion_approved:
                logger.warning(f"🚫 SECURITY: Attempted to post unapproved comment for {file_path}. Blocking post.")
                continue

            # ✅ REFLEXION APPROVED: Post the comment
            logger.info(f"📝 Posting reflexion-approved comment for {file_path} (Criticality: {review_state.CriticalityStatus})")
            
            combined_comment = f"{review_state.WhatNeedsToBeImproved}\n\n**AI Guidance:** {review_state.PromptForAI}"
            
            try:
                comment_result = post_code_review_comment_tool.invoke({
                    "repo_link": initial_state.PullRequestLink,
                    "pull_request_number": initial_state.PullRequestNum,
                    "file_path": file_path,
                    "code_snippet": review_state.DiffCode,
                    "comment": combined_comment,
                    "impact": review_state.CriticalityStatus,
                    "line_number": 1,
                    "side": "RIGHT",
                    "current_code": review_state.CurrentCode,
                    "suggested_code": review_state.SuggestedCode
                })
                
                if comment_result["success"]:
                    logger.info(f"✅ Comment posted for {file_path}")
                    
                    # Track in memory
                    memory_manager.add_review_memory(
                        session=session,
                        file_path=file_path,
                        criticality=review_state.CriticalityStatus,
                        issue=issue_summary,
                        diff_code=review_state.DiffCode,
                        comment_id=str(comment_result.get('comment_id')),
                        comment_url=comment_result.get('comment_url')
                    )
                    
                    # Track in current session
                    comment_metadata = CommentMetadata(
                        file_path=file_path,
                        criticality=review_state.CriticalityStatus,
                        issue_summary=issue_summary,
                        comment_id=str(comment_result.get('comment_id')),
                        timestamp=datetime.now().isoformat(),
                        diff_code_hash=diff_code_hash
                    )
                    current_global_state.PostedComments.append(comment_metadata)
                    
                    # Update file review count
                    current_global_state.FileReviewCounts[file_path] = current_global_state.FileReviewCounts.get(file_path, 0) + 1
                    
                    # Ensure file is tracked in ReviewedFiles
                    if file_path not in current_global_state.ReviewedFiles:
                        current_global_state.ReviewedFiles.append(file_path)
                else:
                    logger.error(f"❌ Failed to post comment: {comment_result.get('error')}")
            except Exception as e:
                logger.error(f"❌ Error posting comment: {e}", exc_info=True)
        
        # Conditional check for additional comments (with guards)
        max_iterations = 2
        iteration = 0
        
        # Check current file review count
        current_file_comments = current_global_state.FileReviewCounts.get(file_path, 0)
        
        while iteration < max_iterations and current_file_comments < MAX_COMMENTS_PER_FILE:
            iteration += 1
            
            should_continue, next_review_state = ConditionalNode(
                file_path=file_path,
                previous_review_state=review_state,
                file_content=file_content,
                workspace_path=workspace_path
            )
            
            if not should_continue or next_review_state is None:
                logger.info(f"No more comments needed for {file_path}")
                break
            
            # Post the next comment with reflexion validation
            if next_review_state.CriticalityStatus in ["Medium", "Critical"]:
                # Reflexion validation for additional comments
                pr_context = {
                    "pr_title": fetch_state.PrRequest.Title,
                    "pr_description": fetch_state.PrRequest.Description
                }

                is_valid, validated_next_state, confidence, validation_issues = ReflexionNode(
                    review_state=next_review_state,
                    file_content=file_content,
                    pr_context=pr_context
                )

                # Track reflexion approval for additional comments
                additional_reflexion_approved = is_valid and confidence >= MIN_CONFIDENCE_THRESHOLD

                if not additional_reflexion_approved:
                    logger.warning(f"❌ Additional review failed reflexion validation (confidence: {confidence:.2f}). Skipping.")
                    break

                # ✅ Additional comment approved by reflexion
                next_review_state = validated_next_state
                logger.info(f"✅ Additional comment approved by reflexion for {file_path} (confidence: {confidence:.2f})")

                # Check for duplicates
                diff_code_hash = hashlib.md5(next_review_state.DiffCode.encode()).hexdigest()
                issue_summary = next_review_state.WhatNeedsToBeImproved[:100]

                if memory_manager.check_duplicate_comment(session, file_path, issue_summary):
                    logger.warning(f"Duplicate additional comment detected. Stopping iterations.")
                    break

                # 🔐 FINAL APPROVAL CHECK: Only post if reflexion approved
                if not additional_reflexion_approved:
                    logger.warning(f"🚫 SECURITY: Attempted to post unapproved additional comment for {file_path}. Blocking post.")
                    break

                logger.info(f"📝 Posting reflexion-approved additional comment {iteration} for {file_path}")
                
                combined_comment = f"{next_review_state.WhatNeedsToBeImproved}\n\n**AI Guidance:** {next_review_state.PromptForAI}"
                
                try:
                    comment_result = post_code_review_comment_tool.invoke({
                        "repo_link": initial_state.PullRequestLink,
                        "pull_request_number": initial_state.PullRequestNum,
                        "file_path": file_path,
                        "code_snippet": next_review_state.DiffCode,
                        "comment": combined_comment,
                        "impact": next_review_state.CriticalityStatus,
                        "line_number": 1,
                        "side": "RIGHT",
                        "current_code": next_review_state.CurrentCode,
                        "suggested_code": next_review_state.SuggestedCode
                    })
                    
                    if comment_result["success"]:
                        logger.info(f"✅ Additional comment posted for {file_path}")
                        
                        # Track in memory
                        memory_manager.add_review_memory(
                            session=session,
                            file_path=file_path,
                            criticality=next_review_state.CriticalityStatus,
                            issue=issue_summary,
                            diff_code=next_review_state.DiffCode,
                            comment_id=str(comment_result.get('comment_id')),
                            comment_url=comment_result.get('comment_url')
                        )
                        
                        # Update counts
                        current_global_state.FileReviewCounts[file_path] = current_global_state.FileReviewCounts.get(file_path, 0) + 1
                        current_file_comments += 1
                    else:
                        logger.error(f"❌ Failed to post additional comment: {comment_result.get('error')}")
                        break
                except Exception as e:
                    logger.error(f"❌ Error posting additional comment: {e}", exc_info=True)
                    break
            
            review_state = next_review_state
        
        if iteration >= max_iterations:
            logger.warning(f"Reached max iterations ({max_iterations}) for {file_path}.")
    
    logger.info(f"Review completed: {len(selected_files)} files processed")
    
    # Generate and post final summary comment
    logger.info("Generating final summary comment...")
    try:
        from WorkFlow.nodes.Final_draft_node.FinalDraftNode import FinalDraftNode
        
        summary_comment = FinalDraftNode(
            global_state=current_global_state,
            repo_link=initial_state.PullRequestLink,
            pr_number=initial_state.PullRequestNum,
            pr_title=fetch_state.PrRequest.Title,
            pr_description=fetch_state.PrRequest.Description
        )
        logger.info("✅ Final summary comment posted successfully")
        
        # Mark session as completed
        memory_manager.complete_session(session, summary_comment)
        
    except Exception as e:
        logger.error(f"❌ Error posting final summary comment: {e}", exc_info=True)
    
    # Update state
    return {
        "initial_state": initial_state,
        "global_state": current_global_state,
        "fetch_state": fetch_state,
        "parse_state": parse_state
    }


def create_workflow() -> StateGraph:
    """
    Create and configure the workflow graph.
    
    Returns:
        Configured StateGraph
    """
    logger = get_logger()
    logger.info("Creating workflow graph...")
    
    # Create the graph
    workflow = StateGraph(WorkflowState)
    
    # Add nodes
    workflow.add_node("fetch_pr", fetch_pr_node)
    workflow.add_node("parse_files", parse_files_node)
    workflow.add_node("review_files", review_files_node)
    
    # Set entry point
    workflow.set_entry_point("fetch_pr")
    
    # Add edges
    workflow.add_edge("fetch_pr", "parse_files")
    workflow.add_edge("parse_files", "review_files")
    workflow.add_edge("review_files", END)
    
    # Compile the graph
    app = workflow.compile()
    
    logger.info("Workflow graph created successfully")
    return app


if __name__ == "__main__":
    """Test the workflow."""
    import json
    from dotenv import load_dotenv
    
    load_dotenv()
    logger = get_logger()
    
    print("=" * 80)
    print("Testing Code Review Workflow")
    print("=" * 80)
    
    try:
        # Create initial state
        print("\n1. Creating initial state...")
        initial = intial_state(
            PullRequestLink="https://github.com/TheCoder30ec4/anime_recommeder/",
            PullRequestNum=1
        )
        print(f"✅ Initial state created: PR #{initial.PullRequestNum}")
        
        # Create empty global state
        print("\n2. Creating global state...")
        global_state = Global_State(
            TotalFiles=0,
            ReviewedFiles=[],
            CurrentFile="",
            RelaventContext=[],
            SkippedFiles=[],
            IgnoreFiles=[]
        )
        print("✅ Global state created")
        
        # Create initial fetch state (empty, will be populated by node)
        print("\n3. Creating initial fetch state...")
        from WorkFlow.nodes.Fetch_PR_node.FetchPrState import PrRequestState
        fetch_state = FetchState(
            WorkSpacePath="",
            PrRequest=PrRequestState(
                Title="",
                State="open",
                Description="",
                FileStructure=[],
                Branch=""
            )
        )
        print("✅ Fetch state created")
        
        # Create initial parse state (empty, will be populated by node)
        print("\n4. Creating initial parse state...")
        from WorkFlow.nodes.Parse_files_node.ParseFileState import ParseState
        parse_state = ParseState(
            RootWorkSpace="",
            SelectedFilePath=[],
            SkippedFiles=[]
        )
        print("✅ Parse state created")
        
        # Create workflow
        print("\n5. Creating workflow...")
        app = create_workflow()
        print("✅ Workflow created")

        # 🖼 Generate PNG of workflow graph (SAVED TO PROJECT ROOT)
        print("\n5.1 Generating workflow PNG...")
        try:
            # Option A: Mermaid-based PNG (no extra deps, uses Mermaid.ink)
            png_bytes = app.get_graph().draw_mermaid_png()
            png_path = project_root / "code_review_workflow_mermaid.png"
            png_path.write_bytes(png_bytes)
            print(f"✅ Mermaid PNG saved at: {png_path}")

            # Option B (optional): Graphviz-based PNG (requires `pygraphviz` installed)
            # from pathlib import Path
            # png_path_graphviz = project_root / "code_review_workflow_graphviz.png"
            # graphviz_bytes = app.get_graph().draw_png()
            # png_path_graphviz.write_bytes(graphviz_bytes)
            # print(f"✅ Graphviz PNG saved at: {png_path_graphviz}")
        except Exception as viz_err:
            print(f"⚠️ Failed to generate PNG visualization: {viz_err}")

        # Prepare initial state
        initial_state_dict = {
            "initial_state": initial,
            "global_state": global_state,
            "fetch_state": fetch_state,
            "parse_state": parse_state
        }
        
        # Run workflow
        print("\n6. Running workflow...")
        print("   (This will fetch PR details from GitHub and parse files)")
        print("   (Requires GIT_TOKEN in .env file)")
        
        result = app.invoke(initial_state_dict)
        
        print("\n✅ Workflow completed successfully!")
        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)
        
        # Print results
        print("\n📋 Initial State:")
        print(f"   PR Link: {result['initial_state'].PullRequestLink}")
        print(f"   PR Number: {result['initial_state'].PullRequestNum}")
        
        print("\n🌐 Global State:")
        print(f"   Total Files: {result['global_state'].TotalFiles}")
        print(f"   Ignored Files: {len(result['global_state'].IgnoreFiles)}")
        print(f"   Reviewed Files: {len(result['global_state'].ReviewedFiles)}")
        
        print("\n📥 Fetch State:")
        print(f"   Workspace Path: {result['fetch_state'].WorkSpacePath}")
        print(f"   PR Title: {result['fetch_state'].PrRequest.Title}")
        print(f"   PR State: {result['fetch_state'].PrRequest.State}")
        print(f"   Branch: {result['fetch_state'].PrRequest.Branch}")
        print(f"   Files in Structure: {len([f for f in result['fetch_state'].PrRequest.FileStructure if f.startswith('> *')])}")
        
        print("\n📂 Parse State:")
        print(f"   Root Workspace: {result['parse_state'].RootWorkSpace}")
        print(f"   Selected Files: {len(result['parse_state'].SelectedFilePath)}")
        print(f"   Skipped Files: {len(result['parse_state'].SkippedFiles)}")
        if result['parse_state'].SelectedFilePath:
            print(f"   Selected Files (first 5):")
            for file in result['parse_state'].SelectedFilePath[:5]:
                print(f"     - {file}")
            if len(result['parse_state'].SelectedFilePath) > 5:
                print(f"     ... and {len(result['parse_state'].SelectedFilePath) - 5} more")
        if result['parse_state'].SkippedFiles:
            print(f"   Skipped Files (first 3):")
            for file, reason in result['parse_state'].SkippedFiles[:3]:
                print(f"     - {file}: {reason}")
            if len(result['parse_state'].SkippedFiles) > 3:
                print(f"     ... and {len(result['parse_state'].SkippedFiles) - 3} more")
        
        print("\n" + "=" * 80)
        print("Full State (JSON):")
        print("=" * 80)
        print(json.dumps({
            "initial_state": result['initial_state'].model_dump(),
            "global_state": result['global_state'].model_dump(),
            "fetch_state": result['fetch_state'].model_dump(),
            "parse_state": result['parse_state'].model_dump()
        }, indent=2))
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
