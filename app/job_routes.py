"""Job API routes for Grub Crawler"""
from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Optional, List
from pydantic import BaseModel
import logging
import json

from app.jobs import JobType, JobManager, JobProcessor
from app.storage import CrawlStorageService
from app.auth import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api", tags=["jobs"])


# --- Request/Response Models ---

class CreateJobRequest(BaseModel):
    session_id: str
    job_type: str
    input_data: dict = {}

class CreateJobResponse(BaseModel):
    job_id: str
    session_id: str
    message: str

class CrawlJobRequest(BaseModel):
    url: str
    javascript: bool = True
    screenshot: bool = False
    screenshot_mode: str = "full"
    timeout: Optional[int] = None
    callback_url: Optional[str] = None

class BatchCrawlJobRequest(BaseModel):
    urls: List[str]
    javascript: bool = True
    screenshot: bool = False
    max_concurrent: int = 3
    callback_url: Optional[str] = None

class MarkdownJobRequest(BaseModel):
    url: str
    javascript: bool = True
    timeout: Optional[int] = None
    callback_url: Optional[str] = None

class GrubJobRequest(BaseModel):
    prompt: str
    callback_url: str  # Required for AI-driven workflows
    max_urls: int = 10
    javascript: bool = True
    screenshot: bool = False

class StageStatus(BaseModel):
    status: str
    total_urls: int
    urls_processed: int
    progress_percent: int
    is_running: bool

class SessionStatusResponse(BaseModel):
    session_id: str
    stages: dict[str, StageStatus]
    updated_at: str


# --- Dependencies ---

async def get_storage_service(user: dict = Depends(get_current_user)) -> CrawlStorageService:
    user_email = user.get("email", "anonymous@grub-crawl.local")
    return CrawlStorageService(user_email=user_email)


# --- API Endpoints ---

@router.post("/jobs/create", response_model=CreateJobResponse)
async def create_job(
    request: CreateJobRequest,
    user: dict = Depends(get_current_user),
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Submits a new job to the queue."""
    try:
        try:
            job_type = JobType(request.job_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid job type: {request.job_type}. Valid types: {[t.value for t in JobType]}"
            )

        user_email = user.get("email", "anonymous@grub-crawl.local")
        job_manager = JobManager(storage_service)
        
        job_id = await job_manager.create_job(
            session_id=request.session_id,
            job_type=job_type,
            input_data=request.input_data,
            user_email=user_email
        )
        
        return CreateJobResponse(
            job_id=job_id,
            session_id=request.session_id,
            message="Job submitted successfully."
        )
        
    except Exception as e:
        logger.error(f"Error creating job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/crawl", response_model=CreateJobResponse)
async def create_crawl_job(
    request: CrawlJobRequest,
    user: dict = Depends(get_current_user),
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Submit a single URL crawl job."""
    try:
        user_email = user.get("email", "anonymous@grub-crawl.local")
        job_manager = JobManager(storage_service)

        # Generate session ID
        import uuid
        session_id = str(uuid.uuid4())

        # Get bearer token for callbacks - will need to be passed from request context
        bearer_token = None  # TODO: Get from request context if needed for callbacks

        job_id = await job_manager.create_job(
            session_id=session_id,
            job_type=JobType.CRAWL_URL,
            input_data={
                "url": request.url,
                "javascript": request.javascript,
                "screenshot": request.screenshot,
                "screenshot_mode": request.screenshot_mode,
                "timeout": request.timeout
            },
            user_email=user_email,
            callback_url=request.callback_url,
            bearer_token=bearer_token
        )
        
        return CreateJobResponse(
            job_id=job_id,
            session_id=session_id,
            message=f"Crawl job submitted for {request.url}"
        )
        
    except Exception as e:
        logger.error(f"Error creating crawl job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/batch-crawl", response_model=CreateJobResponse)
async def create_batch_crawl_job(
    request: BatchCrawlJobRequest,
    user: dict = Depends(get_current_user),
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Submit a batch crawl job for multiple URLs."""
    try:
        if not request.urls:
            raise HTTPException(status_code=400, detail="URLs list cannot be empty")
        
        user_email = user.get("email", "anonymous@grub-crawl.local")
        job_manager = JobManager(storage_service)

        # Generate session ID
        import uuid
        session_id = str(uuid.uuid4())

        # Get bearer token for callbacks - will need to be passed from request context
        bearer_token = None  # TODO: Get from request context if needed for callbacks

        job_id = await job_manager.create_job(
            session_id=session_id,
            job_type=JobType.BATCH_CRAWL,
            input_data={
                "urls": request.urls,
                "javascript": request.javascript,
                "screenshot": request.screenshot,
                "max_concurrent": request.max_concurrent
            },
            user_email=user_email,
            callback_url=request.callback_url,
            bearer_token=bearer_token
        )
        
        return CreateJobResponse(
            job_id=job_id,
            session_id=session_id,
            message=f"Batch crawl job submitted for {len(request.urls)} URLs"
        )
        
    except Exception as e:
        logger.error(f"Error creating batch crawl job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/markdown", response_model=CreateJobResponse)
async def create_markdown_job(
    request: MarkdownJobRequest,
    user: dict = Depends(get_current_user),
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Submit a markdown-only crawl job."""
    try:
        user_email = user.get("email", "anonymous@grub-crawl.local")
        job_manager = JobManager(storage_service)

        # Generate session ID
        import uuid
        session_id = str(uuid.uuid4())

        # Get bearer token for callbacks - will need to be passed from request context
        bearer_token = None  # TODO: Get from request context if needed for callbacks

        job_id = await job_manager.create_job(
            session_id=session_id,
            job_type=JobType.MARKDOWN_ONLY,
            input_data={
                "url": request.url,
                "javascript": request.javascript,
                "timeout": request.timeout
            },
            user_email=user_email,
            callback_url=request.callback_url,
            bearer_token=bearer_token
        )
        
        return CreateJobResponse(
            job_id=job_id,
            session_id=session_id,
            message=f"Markdown job submitted for {request.url}"
        )
        
    except Exception as e:
        logger.error(f"Error creating markdown job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/status")
async def get_session_status(
    session_id: str,
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Gets the overall progress status for a session."""
    try:
        status_data = await JobManager(storage_service).get_session_status(session_id)
        if not status_data:
            raise HTTPException(status_code=404, detail="Session status not found.")
        
        return status_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/results")
async def get_session_results(
    session_id: str,
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Gets all crawl results for a session."""
    try:
        # Get session metadata
        try:
            metadata_bytes = await storage_service.get_file('metadata.json', session_id)
            metadata = json.loads(metadata_bytes.decode('utf-8'))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Session not found.")
        
        # Get all result files
        results = []
        try:
            files = await storage_service.list_files("results", session_id)
            for file_info in files:
                if file_info.get('name', '').endswith('.json'):
                    try:
                        data_bytes = await storage_service.get_file(f"results/{file_info['name']}", session_id)
                        result_data = json.loads(data_bytes.decode('utf-8'))
                        results.append(result_data)
                    except Exception as e:
                        logger.warning(f"Failed to load result file {file_info['name']}: {e}")
        except Exception as e:
            logger.warning(f"Could not list result files: {e}")
        
        return {
            "session_id": session_id,
            "metadata": metadata,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session results: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/screenshots")
async def list_session_screenshots(
    session_id: str,
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """Lists all screenshots for a session."""
    try:
        screenshots = []
        try:
            files = await storage_service.list_files("screenshots", session_id)
            for file_info in files:
                if file_info.get('name', '').endswith('.png'):
                    screenshots.append({
                        "filename": file_info['name'],
                        "path": f"screenshots/{file_info['name']}",
                        "size": file_info.get('size', 0),
                        "modified": file_info.get('modified')
                    })
        except Exception as e:
            logger.warning(f"Could not list screenshot files: {e}")
        
        return {
            "session_id": session_id,
            "screenshots": screenshots
        }
        
    except Exception as e:
        logger.error(f"Error listing session screenshots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/process-job")
async def process_job_worker(request: Request):
    """Worker endpoint called by Cloud Tasks to process jobs"""
    job_id = None
    try:
        # Get job details from request
        job_data = await request.json()
        job_id = job_data.get("job_id")
        session_id = job_data.get("session_id")
        user_email = job_data.get("user_email")
        
        if not job_id or not session_id:
            raise HTTPException(status_code=400, detail="Missing job_id or session_id")
        
        logger.info(f"Worker processing job {job_id} for session {session_id}")
        
        # Create storage service with user context
        storage_service = CrawlStorageService(user_email=user_email)
        
        # Create job manager and processor
        job_manager = JobManager(storage_service)
        processor = JobProcessor(job_manager, storage_service)
        
        await processor.process_job(job_data)
        
        return {"status": "success", "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Worker failed to process job {job_id}: {e}", exc_info=True)
        # Return 500 to trigger Cloud Tasks retry
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/grub", response_model=CreateJobResponse)
async def create_grub_job(
    request: GrubJobRequest,
    user: dict = Depends(get_current_user),
    storage_service: CrawlStorageService = Depends(get_storage_service)
):
    """
    AI-driven crawl workflow endpoint.

    Example: "crawl 5 urls from hn front page and show funny ai ones"

    This endpoint:
    1. Uses AI to interpret the prompt and identify URLs
    2. Submits a batch crawl job
    3. Returns job_id for tracking
    4. Sends results via callback when complete
    """
    try:
        user_email = user.get("email", "anonymous@grub-crawl.local")
        job_manager = JobManager(storage_service)

        # Generate session ID for this grub workflow
        import uuid
        session_id = str(uuid.uuid4())

        # Get bearer token for callbacks - will need to be passed from request context
        bearer_token = None  # TODO: Get from request context if needed for callbacks

        # TODO: Implement AI interpretation of prompt to extract URLs
        # For now, this is a placeholder that would:
        # 1. Send prompt to OpenAI/Claude/local model
        # 2. Parse response to extract URLs
        # 3. Filter/validate URLs
        # 4. Submit batch crawl job

        # Placeholder response - in real implementation this would:
        # - Call AI service to interpret prompt
        # - Extract URLs from AI response
        # - Create batch crawl job with those URLs

        # For demo purposes, return error indicating this needs AI integration
        raise HTTPException(
            status_code=501,
            detail="AI-driven URL extraction not yet implemented. This endpoint needs integration with OpenAI/Claude/local model to interpret prompts and extract URLs."
        )

        # This is what the full implementation would look like:
        """
        # 1. Send prompt to AI service
        ai_response = await interpret_crawl_prompt(request.prompt, request.max_urls)

        # 2. Extract URLs from AI response
        urls = extract_urls_from_ai_response(ai_response)

        if not urls:
            raise HTTPException(
                status_code=400,
                detail="AI could not identify any URLs from the prompt"
            )

        # 3. Submit batch crawl job
        job_id = await job_manager.create_job(
            session_id=session_id,
            job_type=JobType.BATCH_CRAWL,
            input_data={
                "urls": urls,
                "javascript": request.javascript,
                "screenshot": request.screenshot,
                "max_concurrent": min(len(urls), 5),
                "ai_prompt": request.prompt,
                "ai_context": ai_response
            },
            user_email=user_email,
            callback_url=request.callback_url,
            bearer_token=bearer_token
        )

        return CreateJobResponse(
            job_id=job_id,
            session_id=session_id,
            message=f"AI-driven crawl job submitted for prompt: '{request.prompt}'"
        )
        """

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating grub job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))