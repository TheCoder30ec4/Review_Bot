#!/usr/bin/env python3
"""
Code Review Bot - FastAPI Server

Enterprise-grade AI-powered code review automation using LangGraph.

API Endpoints:
    POST /review - Trigger a code review for a PR
    GET /review/{session_id} - Get review status
    GET /health - Health check
    GET /stats - Get database statistics
"""

import os
import re
import sys
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import uvicorn

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()


# ============================================================================
# Pydantic Models for API
# ============================================================================

class ReviewRequest(BaseModel):
    """Request model for triggering a code review."""
    pr_url: str = Field(
        ...,
        description="Full GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)",
        examples=["https://github.com/microsoft/vscode/pull/150000"]
    )
    
    @field_validator('pr_url')
    @classmethod
    def validate_pr_url(cls, v: str) -> str:
        """Validate GitHub PR URL format."""
        pattern = r'^https://github\.com/[\w\-\.]+/[\w\-\.]+/pull/\d+/?$'
        if not re.match(pattern, v):
            raise ValueError(
                "Invalid PR URL format. Expected: https://github.com/owner/repo/pull/123"
            )
        return v.rstrip('/')


class ReviewResponse(BaseModel):
    """Response model for review request."""
    success: bool
    message: str
    session_id: Optional[str] = None
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    repository: Optional[str] = None


class ReviewStatusResponse(BaseModel):
    """Response model for review status."""
    session_id: str
    status: str  # pending, in_progress, completed, failed
    pr_number: Optional[int] = None
    repository: Optional[str] = None
    total_files_reviewed: int = 0
    total_comments_posted: int = 0
    created_at: Optional[str] = None
    last_updated: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    version: str
    environment_valid: bool
    timestamp: str


class StatsResponse(BaseModel):
    """Response model for database statistics."""
    total_sessions: int
    total_review_memories: int
    unique_files_reviewed: int
    sessions_by_status: Dict[str, int]
    database_size_mb: float


# ============================================================================
# Global State for Background Tasks
# ============================================================================

# Track active reviews
active_reviews: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Helper Functions
# ============================================================================

def validate_environment() -> bool:
    """Validate required environment variables."""
    return bool(os.getenv('GIT_TOKEN'))


def parse_pr_url(pr_url: str) -> tuple[str, int]:
    """
    Parse GitHub PR URL to extract repository and PR number.
    
    Args:
        pr_url: Full GitHub PR URL
        
    Returns:
        Tuple of (repository, pr_number)
    """
    # URL format: https://github.com/owner/repo/pull/123
    parts = pr_url.split('/')
    owner = parts[3]
    repo = parts[4]
    pr_number = int(parts[6])
    repository = f"{owner}/{repo}"
    return repository, pr_number


async def run_code_review(
    pr_url: str,
    pr_number: int,
    session_id: str
) -> None:
    """
    Run the code review workflow in background.
    
    Args:
        pr_url: Full GitHub PR URL
        pr_number: Pull request number
        session_id: Unique session ID for tracking
    """
    from WorkFlow.Flow import create_workflow
    from WorkFlow.State import intial_state, Global_State
    from WorkFlow.nodes.Fetch_PR_node.FetchPrState import FetchState, PrRequestState
    from WorkFlow.nodes.Parse_files_node.ParseFileState import ParseState
    from WorkFlow.utils.logger import get_logger
    
    logger = get_logger()
    
    try:
        # Update status to in_progress
        active_reviews[session_id]["status"] = "in_progress"
        active_reviews[session_id]["started_at"] = datetime.now().isoformat()
        
        logger.info(f"🚀 Starting code review for PR: {pr_url} (session: {session_id})")
        
        # Extract repo link (without /pull/N)
        parts = pr_url.split('/pull/')
        repo_link = parts[0] + '/'
        
        # Create initial states
        initial = intial_state(
            PullRequestLink=repo_link,
            PullRequestNum=pr_number
        )
        
        global_state = Global_State(
            TotalFiles=0,
            ReviewedFiles=[],
            CurrentFile="",
            RelaventContext=[],
            SkippedFiles=[],
            IgnoreFiles=[]
        )
        
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
        
        parse_state = ParseState(
            RootWorkSpace="",
            SelectedFilePath=[],
            SkippedFiles=[]
        )
        
        # Create and run workflow
        app = create_workflow()
        
        initial_state_dict = {
            "initial_state": initial,
            "global_state": global_state,
            "fetch_state": fetch_state,
            "parse_state": parse_state
        }
        
        # Run workflow (this is blocking, so we're in async context)
        result = await asyncio.to_thread(app.invoke, initial_state_dict)
        
        # Update status with results
        active_reviews[session_id]["status"] = "completed"
        active_reviews[session_id]["completed_at"] = datetime.now().isoformat()
        active_reviews[session_id]["total_files_reviewed"] = result['global_state'].TotalFiles
        active_reviews[session_id]["total_comments_posted"] = len(result['global_state'].PostedComments)
        active_reviews[session_id]["reviewed_files"] = result['global_state'].ReviewedFiles
        
        logger.info(f"✅ Code review completed for session: {session_id}")
        
    except Exception as e:
        logger.error(f"❌ Code review failed for session {session_id}: {e}", exc_info=True)
        active_reviews[session_id]["status"] = "failed"
        active_reviews[session_id]["error"] = str(e)
        active_reviews[session_id]["failed_at"] = datetime.now().isoformat()


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print("🤖 Code Review Bot API Starting...")
    print(f"   Environment: {'✅ Valid' if validate_environment() else '❌ Missing GIT_TOKEN'}")
    yield
    # Shutdown
    print("👋 Code Review Bot API Shutting down...")


app = FastAPI(
    title="Code Review Bot API",
    description="Enterprise-grade AI-powered code review automation using LangGraph",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - returns health status."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        environment_valid=validate_environment(),
        timestamp=datetime.now().isoformat()
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        environment_valid=validate_environment(),
        timestamp=datetime.now().isoformat()
    )


@app.post("/review", response_model=ReviewResponse)
async def trigger_review(
    request: ReviewRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger a code review for a GitHub pull request.
    
    The review runs in the background. Use GET /review/{session_id} to check status.
    """
    # Validate environment
    if not validate_environment():
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: Missing GIT_TOKEN environment variable"
        )
    
    try:
        # Parse PR URL
        repository, pr_number = parse_pr_url(request.pr_url)
        
        # Generate session ID
        session_id = str(uuid.uuid4())[:8]
        
        # Initialize tracking
        active_reviews[session_id] = {
            "status": "pending",
            "pr_url": request.pr_url,
            "pr_number": pr_number,
            "repository": repository,
            "created_at": datetime.now().isoformat(),
            "total_files_reviewed": 0,
            "total_comments_posted": 0
        }
        
        # Queue background task
        background_tasks.add_task(
            run_code_review,
            request.pr_url,
            pr_number,
            session_id
        )
        
        return ReviewResponse(
            success=True,
            message=f"Code review started. Track progress with GET /review/{session_id}",
            session_id=session_id,
            pr_url=request.pr_url,
            pr_number=pr_number,
            repository=repository
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start review: {str(e)}")


@app.get("/review/{session_id}", response_model=ReviewStatusResponse)
async def get_review_status(session_id: str):
    """
    Get the status of a code review.
    
    Args:
        session_id: The session ID returned from POST /review
    """
    if session_id not in active_reviews:
        raise HTTPException(
            status_code=404,
            detail=f"Review session '{session_id}' not found"
        )
    
    review = active_reviews[session_id]
    
    return ReviewStatusResponse(
        session_id=session_id,
        status=review.get("status", "unknown"),
        pr_number=review.get("pr_number"),
        repository=review.get("repository"),
        total_files_reviewed=review.get("total_files_reviewed", 0),
        total_comments_posted=review.get("total_comments_posted", 0),
        created_at=review.get("created_at"),
        last_updated=review.get("completed_at") or review.get("started_at") or review.get("created_at"),
        error=review.get("error")
    )


@app.get("/reviews", response_model=Dict[str, ReviewStatusResponse])
async def list_reviews():
    """List all active/recent review sessions."""
    return {
        session_id: ReviewStatusResponse(
            session_id=session_id,
            status=review.get("status", "unknown"),
            pr_number=review.get("pr_number"),
            repository=review.get("repository"),
            total_files_reviewed=review.get("total_files_reviewed", 0),
            total_comments_posted=review.get("total_comments_posted", 0),
            created_at=review.get("created_at"),
            last_updated=review.get("completed_at") or review.get("started_at") or review.get("created_at"),
            error=review.get("error")
        )
        for session_id, review in active_reviews.items()
    }


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get database statistics."""
    try:
        from WorkFlow.utils.memory_manager import get_memory_manager
        
        manager = get_memory_manager()
        stats = manager.get_database_stats()
        
        return StatsResponse(
            total_sessions=stats.get("total_sessions", 0),
            total_review_memories=stats.get("total_review_memories", 0),
            unique_files_reviewed=stats.get("unique_files_reviewed", 0),
            sessions_by_status=stats.get("sessions_by_status", {}),
            database_size_mb=stats.get("database_size_mb", 0.0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@app.delete("/review/{session_id}")
async def delete_review(session_id: str):
    """Delete a review session from active tracking."""
    if session_id not in active_reviews:
        raise HTTPException(
            status_code=404,
            detail=f"Review session '{session_id}' not found"
        )
    
    del active_reviews[session_id]
    return {"success": True, "message": f"Session '{session_id}' deleted"}


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run the FastAPI server."""
    print("🤖 Code Review Bot API v0.1.0")
    print("=" * 50)
    print()
    
    # Validate environment
    if not validate_environment():
        print("❌ Missing GIT_TOKEN environment variable!")
        print("   Set it using: export GIT_TOKEN='your_github_token'")
        print()
        print("⚠️  Server will start but reviews will fail without token.")
        print()
    else:
        print("✅ Environment validated")
        print()
    
    print("📡 Starting server...")
    print("   Docs: http://localhost:8000/docs")
    print("   ReDoc: http://localhost:8000/redoc")
    print()
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
