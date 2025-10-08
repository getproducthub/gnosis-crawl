"""Crawling tools for gnosis-crawl agent."""

import uuid
import logging
from typing import List, Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult, tool
from app.crawler import get_crawler_engine

logger = logging.getLogger(__name__)


@tool(description="Crawl a single URL and return HTML content and markdown")
async def crawl(url: str, javascript: bool = True, screenshot: bool = False) -> Dict[str, Any]:
    """Crawl a single URL with configurable options.
    
    Args:
        url: The URL to crawl
        javascript: Whether to enable JavaScript rendering (default: True)
        screenshot: Whether to take a screenshot (default: False)
        
    Returns:
        Dict containing HTML, markdown, and metadata
    """
    try:
        # Get crawler engine (user context would come from auth in real implementation)
        crawler = await get_crawler_engine()
        
        # Perform crawl
        result = await crawler.crawl_url(
            url=url,
            javascript=javascript,
            screenshot=screenshot,
            session_id=str(uuid.uuid4())  # Generate session ID
        )
        
        if result.success:
            return {
                "url": result.url,
                "title": result.title,
                "html": result.html,
                "markdown": result.markdown,
                "metadata": {
                    "javascript_enabled": javascript,
                    "screenshot_taken": bool(result.screenshot_path),
                    "screenshot_path": result.screenshot_path,
                    "processing_time": result.processing_time,
                    "browser_time": result.browser_time,
                    "markdown_time": result.markdown_time,
                    "page_info": result.page_info,
                    "status": "success"
                }
            }
        else:
            return {
                "url": result.url,
                "error": result.error_message,
                "metadata": {
                    "javascript_enabled": javascript,
                    "processing_time": result.processing_time,
                    "status": "failed"
                }
            }
            
    except Exception as e:
        logger.error(f"Error in crawl tool: {e}", exc_info=True)
        return {
            "url": url,
            "error": str(e),
            "metadata": {
                "status": "error"
            }
        }


@tool(description="Crawl a URL and return only markdown content")
async def markdown(url: str, javascript: bool = True) -> str:
    """Crawl a URL and return only the markdown content.
    
    Args:
        url: The URL to crawl
        javascript: Whether to enable JavaScript rendering (default: True)
        
    Returns:
        Markdown content as string
    """
    try:
        # Get crawler engine
        crawler = await get_crawler_engine()
        
        # Perform markdown-only crawl
        markdown_content = await crawler.crawl_for_markdown_only(
            url=url,
            javascript=javascript
        )
        
        return markdown_content
        
    except Exception as e:
        logger.error(f"Error in markdown tool: {e}", exc_info=True)
        return f"Error crawling {url}: {str(e)}"


@tool(description="Crawl multiple URLs in batch and return results immediately")
async def batch(urls: List[str], javascript: bool = True, max_concurrent: int = 3) -> Dict[str, Any]:
    """Crawl multiple URLs in batch and return results.
    
    Args:
        urls: List of URLs to crawl
        javascript: Whether to enable JavaScript rendering (default: True)
        max_concurrent: Maximum concurrent crawls (default: 3)
        
    Returns:
        Dict containing batch results
    """
    try:
        # Get crawler engine
        crawler = await get_crawler_engine()
        
        # Generate session ID for this batch
        session_id = str(uuid.uuid4())
        
        # Perform batch crawl
        batch_result = await crawler.batch_crawl(
            urls=urls,
            javascript=javascript,
            screenshot=False,  # Disable screenshots for batch to save time
            max_concurrent=max_concurrent,
            session_id=session_id
        )
        
        return {
            "session_id": session_id,
            "urls": batch_result["urls"],
            "successful_results": batch_result["results"],
            "failed_results": batch_result["failed"],
            "summary": batch_result["summary"],
            "status": "completed"
        }
        
    except Exception as e:
        logger.error(f"Error in batch tool: {e}", exc_info=True)
        return {
            "urls": urls,
            "error": str(e),
            "summary": {
                "total": len(urls),
                "success": 0,
                "failed": len(urls)
            },
            "status": "error"
        }


@tool(description="Get information about the crawler service")
async def crawler_info() -> Dict[str, Any]:
    """Get information about the crawler service capabilities.
    
    Returns:
        Dict containing crawler service information
    """
    from app.config import settings
    
    return {
        "service": "gnosis-crawl",
        "version": "1.0.0",
        "capabilities": {
            "javascript_execution": True,
            "screenshots": True,
            "batch_crawling": True,
            "markdown_generation": True,
            "content_filtering": True
        },
        "configuration": {
            "max_concurrent_crawls": settings.max_concurrent_crawls,
            "default_timeout": settings.browser_timeout,
            "headless_browser": settings.browser_headless,
            "javascript_enabled": settings.enable_javascript,
            "screenshots_enabled": settings.enable_screenshots
        },
        "supported_formats": ["html", "markdown", "json"],
        "supported_screenshot_modes": ["full", "top", "off"]
    }