"""
API routes for gnosis-crawl service
"""
import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header
from datetime import datetime

from app.models import (
    CrawlRequest, CrawlResult, 
    MarkdownRequest, MarkdownResult,
    BatchRequest, BatchResult,
    JobStatus, JobListResponse
)
from app.auth import get_current_user, get_user_email, get_customer_identifier
from app.config import settings
from app.crawler import get_crawler_engine
from fastapi.responses import Response
from typing import Optional
from app.storage import CrawlStorageService

logger = logging.getLogger(__name__)

# Create API router
router = APIRouter()


async def get_optional_user_email(authorization: str = Header(None)) -> Optional[str]:
    """
    Get user email if auth is enabled and token is provided, otherwise return None.
    Used for routes that support both authenticated and unauthenticated access.
    """
    if settings.disable_auth:
        return None
    
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    try:
        user = await get_current_user(authorization)
        if "email" in user:
            return user["email"]
        elif user.get("subject", "").startswith("user:"):
            return user["subject"][5:]
        else:
            return None
    except:
        return None


@router.post("/crawl", response_model=CrawlResult)
async def crawl_single_url(
    request: CrawlRequest,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """
    Crawl a single URL and return HTML + markdown
    Synchronous operation that returns results immediately
    Supports both authenticated (via token) and unauthenticated (via customer_id) access
    """
    try:
        # Resolve customer identifier (prioritizes customer_id from request, falls back to user_email)
        customer_identifier = get_customer_identifier(request.customer_id, user_email)
        
        # Get crawler engine for this customer
        crawler = await get_crawler_engine(customer_identifier)
        
        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())
        
        # Perform crawl with request options
        result = await crawler.crawl_url(
            url=str(request.url),
            javascript=request.options.javascript,
            screenshot=request.options.screenshot,
            screenshot_mode=request.options.screenshot_mode,
            timeout=request.options.timeout,
            session_id=session_id
        )
        
        if result.success:
            saved_filename = None
            try:
                if session_id:
                    saved_filename = await crawler._save_crawl_result(result, session_id)
            except Exception:
                saved_filename = None
            return CrawlResult(
                success=True,
                url=result.url,
                html=result.html,
                markdown=result.markdown,
                screenshot_url=result.screenshot_path,
                metadata={
                    "title": result.title,
                    "customer_identifier": customer_identifier,
                    "processing_time": result.processing_time,
                    "browser_time": result.browser_time,
                    "markdown_time": result.markdown_time,
                    "page_info": result.page_info,
                    "options": request.options.dict(),
                    "session_id": session_id,
                    "storage": {
                        "result_file": saved_filename,
                        "screenshots": result.screenshot_path if isinstance(result.screenshot_path, list) else ([result.screenshot_path] if result.screenshot_path else [])
                    }
                },
                crawled_at=datetime.utcnow()
            )
        else:
            return CrawlResult(
                success=False,
                url=result.url,
                crawled_at=datetime.utcnow(),
                error=result.error_message,
                metadata={
                    "customer_identifier": customer_identifier,
                    "processing_time": result.processing_time,
                    "options": request.options.dict(),
                    "session_id": session_id
                }
            )
        
    except Exception as e:
        logger.error(f"Failed to crawl {request.url}: {e}", exc_info=True)
        return CrawlResult(
            success=False,
            url=str(request.url),
            crawled_at=datetime.utcnow(),
            error=str(e),
            metadata={"customer_identifier": customer_identifier}
        )


@router.post("/markdown", response_model=MarkdownResult) 
async def crawl_markdown_only(
    request: MarkdownRequest,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """
    Crawl a URL and return only markdown content
    Optimized for markdown extraction
    Supports both authenticated (via token) and unauthenticated (via customer_id) access
    """
    try:
        # Resolve customer identifier
        customer_identifier = get_customer_identifier(request.customer_id, user_email)
        
        # Get crawler engine for this customer
        crawler = await get_crawler_engine(customer_identifier)
        
        # Perform markdown-only crawl
        markdown_content = await crawler.crawl_for_markdown_only(
            url=str(request.url),
            javascript=request.options.javascript,
            timeout=request.options.timeout
        )
        
        # Check if crawl was successful by looking for error indicators
        if "Error" in markdown_content[:50]:  # Simple error check
            return MarkdownResult(
                success=False,
                url=str(request.url),
                crawled_at=datetime.utcnow(),
                error=markdown_content,
                metadata={"customer_identifier": customer_identifier}
            )
        else:
            return MarkdownResult(
                success=True,
                url=str(request.url),
                markdown=markdown_content,
                metadata={
                    "customer_identifier": customer_identifier,
                    "options": request.options.dict(),
                    "session_id": request.session_id
                },
                crawled_at=datetime.utcnow()
            )
        
    except Exception as e:
        logger.error(f"Failed to crawl markdown for {request.url}: {e}", exc_info=True)
        return MarkdownResult(
            success=False,
            url=str(request.url),
            crawled_at=datetime.utcnow(),
            error=str(e),
            metadata={"customer_identifier": customer_identifier}
        )


@router.post("/batch", response_model=BatchResult)
async def crawl_batch_urls(
    request: BatchRequest,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """
    Start a batch crawl job for multiple URLs
    Returns results immediately (synchronous batch processing)
    Supports both authenticated (via token) and unauthenticated (via customer_id) access
    """
    try:
        # Resolve customer identifier
        customer_identifier = get_customer_identifier(request.customer_id, user_email)
        
        # Get crawler engine for this customer
        crawler = await get_crawler_engine(customer_identifier)
        
        # Generate session ID for this batch
        session_id = str(uuid.uuid4())
        
        # Convert URLs to strings
        url_list = [str(url) for url in request.urls]
        
        logger.info(f"Starting batch crawl for {len(url_list)} URLs (customer: {customer_identifier})")
        
        # Perform batch crawl (synchronous)
        batch_result = await crawler.batch_crawl(
            urls=url_list,
            javascript=request.options.javascript,
            screenshot=request.options.screenshot,
            max_concurrent=request.concurrent,  # Fixed: it's on BatchRequest, not options
            session_id=session_id
        )

        
        return BatchResult(
            success=True,
            job_id=session_id,
            total_urls=len(url_list),
            message=f"Batch crawl completed: {batch_result['summary']['success']}/{batch_result['summary']['total']} successful",
            results=batch_result["results"],
            failed_results=batch_result["failed"],
            summary=batch_result["summary"]
        )
        
    except Exception as e:
        logger.error(f"Failed to execute batch crawl: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    user_email: str = Depends(get_user_email)
):
    """
    Get status and results for a specific job
    """
    try:
        # TODO: Implement actual job status retrieval
        # For now, return a mock response for Phase 1
        
        return JobStatus(
            job_id=job_id,
            status="completed",
            progress=1.0,
            total_urls=3,
            completed_urls=3,
            results=[
                CrawlResult(
                    success=True,
                    url="https://example.com",
                    html="<html><body>Mock content</body></html>",
                    markdown="# Mock Content",
                    metadata={"title": "Example"},
                    crawled_at=datetime.utcnow()
                )
            ],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Failed to get job status for {job_id}: {e}")
        raise HTTPException(status_code=404, detail="Job not found")


@router.get("/jobs", response_model=JobListResponse)
async def list_user_jobs(
    user_email: str = Depends(get_user_email)
):
    """
    List all jobs for the authenticated user
    """
    try:
        # TODO: Implement actual job listing
        # For now, return a mock response for Phase 1
        
        mock_jobs = [
            {
                "job_id": "mock-job-1",
                "status": "completed",
                "total_urls": 5,
                "completed_urls": 5,
                "created_at": datetime.utcnow().isoformat()
            },
            {
                "job_id": "mock-job-2", 
                "status": "running",
                "total_urls": 10,
                "completed_urls": 7,
                "created_at": datetime.utcnow().isoformat()
            }
        ]
        
        return JobListResponse(
            jobs=mock_jobs,
            total=len(mock_jobs)
        )
        
    except Exception as e:
        logger.error(f"Failed to list jobs for user {user_email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/sessions/{session_id}/files")
async def list_session_files(
    session_id: str, 
    prefix: Optional[str] = None, 
    customer_id: Optional[str] = None,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """List files stored for a session. Optional prefix (e.g., 'results', 'screenshots')."""
    customer_identifier = get_customer_identifier(customer_id, user_email)
    storage = CrawlStorageService(customer_identifier)
    try:
        pref = prefix or ''
        files = await storage.list_files(pref or '', session_id)
        
        # Add storage path info for debugging
        storage_path = None
        if hasattr(storage, '_storage_root'):
            storage_path = str(storage.get_session_path(session_id))
        
        return {
            "session_id": session_id, 
            "prefix": pref, 
            "files": files,
            "storage_info": {
                "customer_identifier": customer_identifier,
                "customer_hash": storage._user_hash,
                "storage_path": storage_path,
                "is_cloud": storage._is_cloud
            }
        }
    except Exception as e:
        logger.error(f"Failed to list session files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/debug/storage")
async def debug_storage(
    customer_id: Optional[str] = None,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """Debug endpoint to inspect storage structure and contents."""
    import os
    from pathlib import Path
    
    customer_identifier = get_customer_identifier(customer_id, user_email)
    storage = CrawlStorageService(customer_identifier)
    
    result = {
        "customer_identifier": customer_identifier,
        "customer_hash": storage._user_hash,
        "is_cloud": storage._is_cloud,
        "storage_root": str(storage._storage_root) if hasattr(storage, '_storage_root') else "N/A"
    }
    
    # List all directories and files in storage
    if hasattr(storage, '_storage_root'):
        storage_root = storage._storage_root
        customer_path = storage_root / storage._user_hash
        
        result["customer_path"] = str(customer_path)
        result["customer_path_exists"] = customer_path.exists()
        
        if customer_path.exists():
            # List all sessions
            sessions = []
            for session_dir in customer_path.iterdir():
                if session_dir.is_dir():
                    session_info = {
                        "session_id": session_dir.name,
                        "path": str(session_dir),
                        "files": []
                    }
                    
                    # List files recursively
                    for root, dirs, files in os.walk(session_dir):
                        for file in files:
                            file_path = Path(root) / file
                            session_info["files"].append({
                                "name": file,
                                "relative_path": str(file_path.relative_to(session_dir)),
                                "size": file_path.stat().st_size
                            })
                    
                    sessions.append(session_info)
            
            result["sessions"] = sessions
            result["total_sessions"] = len(sessions)
    
    return result


@router.get("/sessions/{session_id}/file")
async def get_session_file(
    session_id: str, 
    path: str, 
    customer_id: Optional[str] = None,
    user_email: Optional[str] = Depends(get_optional_user_email)
):
    """Fetch a stored file for a session by relative path (e.g., 'results/abc.json')."""
    customer_identifier = get_customer_identifier(customer_id, user_email)
    storage = CrawlStorageService(customer_identifier)
    try:
        data = await storage.get_file(path, session_id)
        # Best-effort content type based on extension
        if path.endswith('.json'):
            return Response(content=data, media_type='application/json')
        elif path.endswith('.png'):
            return Response(content=data, media_type='image/png')
        elif path.endswith('.txt') or path.endswith('.md'):
            return Response(content=data, media_type='text/plain')
        return Response(content=data, media_type='application/octet-stream')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        logger.error(f"Failed to fetch session file '{path}': {e}")
        raise HTTPException(status_code=500, detail=str(e))
