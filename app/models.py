"""
Pydantic models for gnosis-crawl API requests and responses
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, HttpUrl, Field
from pydantic import root_validator
from datetime import datetime


# Request Models
class CrawlOptions(BaseModel):
    """Options for crawling configuration"""
    javascript: bool = True
    screenshot: bool = False
    screenshot_mode: str = "full"
    full_content: bool = True
    dedupe_tables: bool = True
    timeout: int = Field(default=30, ge=5, le=300)
    javascript_payload: Optional[str] = None
    wait_until: Literal["domcontentloaded", "networkidle", "selector"] = "domcontentloaded"
    wait_for_selector: Optional[str] = None
    wait_after_load_ms: int = Field(default=1000, ge=0, le=60000)
    retry_with_js_if_thin: bool = False


class CrawlRequest(BaseModel):
    """Single URL crawl request"""
    url: HttpUrl
    options: CrawlOptions = CrawlOptions()
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    javascript_enabled: Optional[bool] = None
    javascript_payload: Optional[str] = None


class MarkdownRequest(BaseModel):
    """Markdown-only crawl request"""
    url: Optional[HttpUrl] = None
    urls: Optional[List[HttpUrl]] = Field(None, min_items=1, max_items=50)
    options: CrawlOptions = CrawlOptions()
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    javascript_enabled: Optional[bool] = None
    javascript_payload: Optional[str] = None

    @root_validator(pre=True)
    def require_url(cls, values):
        if not values.get("url") and not values.get("urls"):
            raise ValueError("url or urls required")
        return values


class RawHtmlRequest(BaseModel):
    """Raw HTML crawl request"""
    url: HttpUrl
    options: CrawlOptions = CrawlOptions()
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    javascript_enabled: Optional[bool] = None
    javascript_payload: Optional[str] = None


class BatchRequest(BaseModel):
    """Batch crawl request"""
    urls: List[HttpUrl] = Field(..., min_items=1, max_items=50)
    options: CrawlOptions = CrawlOptions()
    concurrent: int = Field(default=3, ge=1, le=10)
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    javascript_enabled: Optional[bool] = None
    javascript_payload: Optional[str] = None


# Response Models
class CrawlResult(BaseModel):
    """Single crawl result"""
    success: bool
    url: str
    html: Optional[str] = None
    markdown: Optional[str] = None
    markdown_plain: Optional[str] = None
    content: Optional[str] = None
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    captcha_detected: bool = False
    http_error_family: Optional[str] = None
    render_mode: Optional[str] = None
    wait_strategy: Optional[str] = None
    timings_ms: Dict[str, int] = {}
    body_char_count: int = 0
    body_word_count: int = 0
    content_quality: Optional[str] = None
    extractor_version: Optional[str] = None
    normalized_url: Optional[str] = None
    content_hash: Optional[str] = None
    screenshot_url: Optional[str] = None
    metadata: Dict[str, Any] = {}
    crawled_at: datetime
    error: Optional[str] = None


class MarkdownResult(BaseModel):
    """Markdown-only result"""
    success: bool
    url: str
    markdown: Optional[str] = None
    markdown_plain: Optional[str] = None
    content: Optional[str] = None
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    captcha_detected: bool = False
    http_error_family: Optional[str] = None
    render_mode: Optional[str] = None
    wait_strategy: Optional[str] = None
    timings_ms: Dict[str, int] = {}
    body_char_count: int = 0
    body_word_count: int = 0
    content_quality: Optional[str] = None
    extractor_version: Optional[str] = None
    normalized_url: Optional[str] = None
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = {}
    crawled_at: datetime
    error: Optional[str] = None


class BatchItemResult(BaseModel):
    url: str
    success: bool
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    markdown: Optional[str] = None
    markdown_plain: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    captcha_detected: bool = False
    http_error_family: Optional[str] = None
    render_mode: Optional[str] = None
    wait_strategy: Optional[str] = None
    timings_ms: Dict[str, int] = {}
    body_char_count: int = 0
    body_word_count: int = 0
    content_quality: Optional[str] = None
    extractor_version: Optional[str] = None
    normalized_url: Optional[str] = None
    content_hash: Optional[str] = None
    screenshot_url: Optional[str] = None


class RawHtmlResult(BaseModel):
    """Raw HTML result"""
    success: bool
    url: str
    html: Optional[str] = None
    metadata: Dict[str, Any] = {}
    crawled_at: datetime
    error: Optional[str] = None


class BatchResult(BaseModel):
    """Batch crawl result summary"""
    success: bool
    job_id: str
    total_urls: int
    message: str = "Batch job created successfully"
    results: List[BatchItemResult] = []
    summary: Dict[str, Any] = {}


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


class CacheSearchRequest(BaseModel):
    query: str
    domain: Optional[str] = None
    url_prefix: Optional[str] = None
    min_similarity: float = Field(default=0.4, ge=0.0, le=1.0)
    max_results: int = Field(default=20, ge=1, le=200)
    quality_in: Optional[List[str]] = None
    since_ts: Optional[str] = None


class CacheUpsertRequest(BaseModel):
    url: str
    markdown: str = ""
    markdown_plain: Optional[str] = None
    content: Optional[str] = None
    quality: str = "sufficient"
    status_code: Optional[int] = None
    extractor_version: Optional[str] = None
    normalized_url: Optional[str] = None
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = {}


class CachePruneRequest(BaseModel):
    domain: Optional[str] = None
    ttl_hours: Optional[int] = Field(default=None, ge=1, le=24 * 365)
    dry_run: bool = False
