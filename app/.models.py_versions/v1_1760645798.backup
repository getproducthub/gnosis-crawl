"""
Pydantic models for gnosis-crawl API requests and responses
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime


# Request Models
class CrawlOptions(BaseModel):
    """Options for crawling configuration"""
    javascript: bool = True
    screenshot: bool = False
    screenshot_mode: str = "full"
    full_content: bool = True
    timeout: int = Field(default=30, ge=5, le=300)


class CrawlRequest(BaseModel):
    """Single URL crawl request"""
    url: HttpUrl
    options: CrawlOptions = CrawlOptions()
    session_id: Optional[str] = None


class MarkdownRequest(BaseModel):
    """Markdown-only crawl request"""
    url: HttpUrl
    options: CrawlOptions = CrawlOptions()
    session_id: Optional[str] = None


class BatchRequest(BaseModel):
    """Batch crawl request"""
    urls: List[HttpUrl] = Field(..., min_items=1, max_items=50)
    options: CrawlOptions = CrawlOptions()
    concurrent: int = Field(default=3, ge=1, le=10)
    session_id: Optional[str] = None


# Response Models
class CrawlResult(BaseModel):
    """Single crawl result"""
    success: bool
    url: str
    html: Optional[str] = None
    markdown: Optional[str] = None
    screenshot_url: Optional[str] = None
    metadata: Dict[str, Any] = {}
    crawled_at: datetime
    error: Optional[str] = None


class MarkdownResult(BaseModel):
    """Markdown-only result"""
    success: bool
    url: str
    markdown: Optional[str] = None
    metadata: Dict[str, Any] = {}
    crawled_at: datetime
    error: Optional[str] = None


class BatchResult(BaseModel):
    """Batch crawl result summary"""
    success: bool
    job_id: str
    total_urls: int
    message: str = "Batch job created successfully"


class JobStatus(BaseModel):
    """Job status response"""
    job_id: str
    status: str  # pending, running, completed, failed
    progress: float = Field(ge=0.0, le=1.0)
    total_urls: int
    completed_urls: int
    results: List[CrawlResult] = []
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class JobListResponse(BaseModel):
    """List of user jobs"""
    jobs: List[Dict[str, Any]]
    total: int


# Health Response
class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    cloud_mode: bool