"""
Core crawler orchestration for gnosis-crawl
Combines browser automation with markdown generation
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, urljoin
from pathlib import Path

from app.browser import get_browser_engine, cleanup_browser
from app.markdown import MarkdownGenerator, ContentFilter
from app.storage import CrawlStorageService
from app.config import settings

logger = logging.getLogger(__name__)


class CrawlResult:
    """Result of a single URL crawl operation."""
    
    def __init__(self, url: str, success: bool = False):
        self.url = url
        self.success = success
        self.timestamp = time.time()
        
        # Content
        self.html = ""
        self.markdown = ""
        self.title = ""
        self.status_code = None
        
        # Metadata
        self.page_info = {}
        self.screenshot_path = ""
        self.error_message = ""
        self.crawl_options = {}
        
        # Processing info
        self.processing_time = 0.0
        self.browser_time = 0.0
        self.markdown_time = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "url": self.url,
            "success": self.success,
            "timestamp": self.timestamp,
            "html": self.html,
            "markdown": self.markdown,
            "title": self.title,
            "status_code": self.status_code,
            "page_info": self.page_info,
            "screenshot_path": self.screenshot_path,
            "error_message": self.error_message,
            "crawl_options": self.crawl_options,
            "processing_time": self.processing_time,
            "browser_time": self.browser_time,
            "markdown_time": self.markdown_time
        }


class CrawlerEngine:
    """Main crawler engine that orchestrates browser and markdown generation."""
    
    def __init__(self, user_email: Optional[str] = None):
        self.user_email = user_email
        self.storage = CrawlStorageService(user_email)
        self.markdown_generator = MarkdownGenerator(ContentFilter())
        self._crawl_lock = asyncio.Lock()
    
    async def crawl_url(
        self,
        url: str,
        javascript: bool = True,
        screenshot: bool = False,
        screenshot_mode: str = "full",
        timeout: int = None,
        session_id: Optional[str] = None,
        javascript_payload: Optional[str] = None
    ) -> CrawlResult:
        """
        Crawl a single URL and return comprehensive results.
        
        Args:
            url: URL to crawl
            javascript: Enable JavaScript execution
            screenshot: Take screenshot
            screenshot_mode: Screenshot mode ("full", "top", "off")
            timeout: Browser timeout in milliseconds
            session_id: Session ID for storage organization
            
        Returns:
            CrawlResult with all crawl data
        """
        start_time = time.time()
        result = CrawlResult(url)
        result.crawl_options = {
            "javascript": javascript,
            "screenshot": screenshot,
            "screenshot_mode": screenshot_mode,
            "timeout": timeout or settings.browser_timeout
        }
        
        try:
            # Validate URL
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError(f"Invalid URL: {url}")
            
            # Get browser engine and crawl with isolated context
            browser = await get_browser_engine()
            
            # Browser operations with isolated context (no lock needed)
            browser_start = time.time()
            # Convert timeout from seconds to milliseconds for Playwright
            timeout_ms = (timeout * 1000) if timeout else settings.browser_timeout
            
            # Use isolated context for concurrent crawling
            result.html, result.page_info, screenshot_data = await browser.crawl_with_context(
                url,
                javascript_enabled=javascript,
                timeout=timeout_ms,
                take_screenshot=screenshot and screenshot_mode != "off",
                javascript_payload=javascript_payload
            )
            
            result.title = result.page_info.get("title", "")
            result.browser_time = time.time() - browser_start
            
            # Handle screenshot if captured
            if screenshot_data and session_id:
                screenshot_paths = await self._save_screenshot_data(screenshot_data, url, session_id)
                result.screenshot_path = screenshot_paths
            
            # Generate markdown
            markdown_start = time.time()
            markdown_result = self.markdown_generator.generate_markdown(result.html, url)
            result.markdown = markdown_result.clean_markdown
            result.markdown_time = time.time() - markdown_start
            
            # Save results to storage
            if session_id:
                await self._save_crawl_result(result, session_id)
            
            result.success = True
            result.processing_time = time.time() - start_time
            
            logger.info(f"Successfully crawled {url} in {result.processing_time:.2f}s")
            
        except Exception as e:
            result.error_message = str(e)
            result.processing_time = time.time() - start_time
            logger.error(f"Failed to crawl {url}: {e}", exc_info=True)
        
        return result
    
    async def crawl_for_markdown_only(
        self,
        url: str,
        javascript: bool = True,
        timeout: int = None,
        javascript_payload: Optional[str] = None
    ) -> str:
        """
        Crawl URL and return only the markdown content.
        
        Args:
            url: URL to crawl
            javascript: Enable JavaScript execution
            timeout: Browser timeout in milliseconds
            
        Returns:
            Markdown content as string
        """
        try:
            result = await self.crawl_url(
                url=url,
                javascript=javascript,
                screenshot=False,
                timeout=timeout,
                javascript_payload=javascript_payload
            )
            
            if result.success:
                return result.markdown
            else:
                return f"Error crawling {url}: {result.error_message}"
                
        except Exception as e:
            logger.error(f"Error in markdown-only crawl: {e}")
            return f"Error: {str(e)}"

    async def crawl_raw_html(
        self,
        url: str,
        javascript: bool = True,
        timeout: int = None,
        javascript_payload: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Crawl URL and return only raw HTML content.
        """
        start_time = time.time()
        result: Dict[str, Any] = {
            "success": False,
            "html": "",
            "error": None,
            "page_info": {},
            "processing_time": 0.0
        }
        try:
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError(f"Invalid URL: {url}")

            browser = await get_browser_engine()
            timeout_ms = (timeout * 1000) if timeout else settings.browser_timeout

            html, page_info, _ = await browser.crawl_with_context(
                url,
                javascript_enabled=javascript,
                timeout=timeout_ms,
                take_screenshot=False,
                javascript_payload=javascript_payload
            )

            result["success"] = True
            result["html"] = html
            result["page_info"] = page_info
        except Exception as e:
            logger.error(f"Failed to fetch raw HTML for {url}: {e}", exc_info=True)
            result["error"] = str(e)
        finally:
            result["processing_time"] = time.time() - start_time

        return result
    
    async def batch_crawl(
        self,
        urls: List[str],
        javascript: bool = True,
        screenshot: bool = False,
        max_concurrent: int = 3,
        session_id: Optional[str] = None,
        javascript_payload: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Crawl multiple URLs concurrently.
        
        Args:
            urls: List of URLs to crawl
            javascript: Enable JavaScript execution
            screenshot: Take screenshots
            max_concurrent: Maximum concurrent crawls
            session_id: Session ID for storage organization
            
        Returns:
            Dictionary with batch results
        """
        if not urls:
            return {"urls": [], "results": [], "summary": {"total": 0, "success": 0, "failed": 0}}
        
        # Limit concurrent crawls
        semaphore = asyncio.Semaphore(min(max_concurrent, settings.max_concurrent_crawls))
        
        async def crawl_with_semaphore(url: str) -> CrawlResult:
            async with semaphore:
                return await self.crawl_url(
                    url=url,
                    javascript=javascript,
                    screenshot=screenshot,
                    session_id=session_id,
                    javascript_payload=javascript_payload
                )
        
        # Execute crawls concurrently
        start_time = time.time()
        results = await asyncio.gather(
            *[crawl_with_semaphore(url) for url in urls],
            return_exceptions=True
        )
        
        # Process results
        successful_results = []
        failed_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_results.append({
                    "url": urls[i],
                    "error": str(result)
                })
            elif isinstance(result, CrawlResult):
                if result.success:
                    successful_results.append(result.to_dict())
                else:
                    failed_results.append({
                        "url": result.url,
                        "error": result.error_message
                    })
        
        total_time = time.time() - start_time
        
        batch_result = {
            "urls": urls,
            "results": successful_results,
            "failed": failed_results,
            "summary": {
                "total": len(urls),
                "success": len(successful_results),
                "failed": len(failed_results),
                "processing_time": total_time
            },
            "session_id": session_id
        }
        
        # Save batch results
        if session_id:
            await self._save_batch_result(batch_result, session_id)
        
        logger.info(f"Batch crawl completed: {len(successful_results)}/{len(urls)} successful in {total_time:.2f}s")
        
        return batch_result
    
    def _extract_page_info_from_html(self, html: str) -> Dict[str, Any]:
        """Extract basic page information from HTML content."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract title
            title_tag = soup.find('title')
            title = title_tag.text.strip() if title_tag else ""
            
            # Extract meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            description = meta_desc.get('content', '') if meta_desc else ""
            
            # Extract basic info
            return {
                "title": title,
                "description": description,
                "url": "",  # Will be set by caller
                "status_code": 200,  # Assume success if we got HTML
                "content_type": "text/html",
                "content_length": len(html)
            }
        except Exception as e:
            logger.warning(f"Error extracting page info from HTML: {e}")
            return {
                "title": "",
                "description": "",
                "url": "",
                "status_code": 200,
                "content_type": "text/html",
                "content_length": len(html)
            }
    
    async def _save_screenshot_data(self, screenshot_data, url: str, session_id: str):
        """Save screenshot data to storage and return the path(s)."""
        try:
            # Generate base info from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace(":", "_").replace("/", "_")
            timestamp = int(time.time())
            
            logger.info(f"Saving screenshot data for {url}, session_id: {session_id}")
            logger.info(f"Screenshot data type: {type(screenshot_data)}, size: {len(screenshot_data) if isinstance(screenshot_data, (list, bytes)) else 'unknown'}")
            
            # Handle multiple screenshot segments
            if isinstance(screenshot_data, list):
                # Multiple segments from long page
                saved_paths = []
                for i, segment_data in enumerate(screenshot_data):
                    filename = f"screenshot_{domain}_{timestamp}_segment_{i+1}.png"
                    logger.info(f"Saving screenshot segment {i+1}: {filename}, size: {len(segment_data)} bytes")
                    await self.storage.save_file(segment_data, filename, session_id)
                    saved_paths.append(filename)
                    logger.info(f"Successfully saved screenshot segment {i+1}/{len(screenshot_data)}: {filename}")
                
                logger.info(f"Saved {len(saved_paths)} screenshot segments for {url}")
                return saved_paths
            
            else:
                # Single screenshot
                filename = f"screenshot_{domain}_{timestamp}.png"
                logger.info(f"Saving single screenshot: {filename}, size: {len(screenshot_data)} bytes")
                await self.storage.save_file(screenshot_data, filename, session_id)
                logger.info(f"Successfully saved screenshot: {filename}")
                return filename
            
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}", exc_info=True)
            return None
    
    async def _save_screenshot(
        self,
        browser,
        url: str,
        mode: str,
        session_id: Optional[str]
    ) -> str:
        """Save screenshot and return the path."""
        try:
            # Generate screenshot filename
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace(".", "_")
            timestamp = int(time.time())
            filename = f"screenshot_{domain}_{timestamp}.png"
            
            # Get storage path
            if session_id:
                screenshot_dir = self.storage.get_session_path(session_id) / "screenshots"
                screenshot_dir.mkdir(exist_ok=True)
                screenshot_path = screenshot_dir / filename
            else:
                screenshot_path = Path(f"./screenshots/{filename}")
                screenshot_path.parent.mkdir(exist_ok=True)
            
            # Take screenshot
            success = await browser.take_screenshot(str(screenshot_path), mode)
            
            if success:
                logger.info(f"Screenshot saved: {screenshot_path}")
                return str(screenshot_path)
            else:
                return ""
                
        except Exception as e:
            logger.error(f"Error saving screenshot: {e}")
            return ""
    
    async def _save_crawl_result(self, result: CrawlResult, session_id: str) -> str:
        """Save crawl result to storage and return filename."""
        try:
            # Generate filename
            parsed_url = urlparse(result.url)
            domain = parsed_url.netloc.replace(".", "_")
            timestamp = int(time.time())
            filename = f"crawl_{domain}_{timestamp}.json"
            
            # Save to storage
            await self.storage.save_json(
                data=result.to_dict(),
                filename=filename,
                session_id=session_id
            )
            
            logger.debug(f"Saved crawl result: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving crawl result: {e}")
            return ""
    
    async def _save_batch_result(self, batch_result: Dict[str, Any], session_id: str) -> None:
        """Save batch crawl result to storage."""
        try:
            timestamp = int(time.time())
            filename = f"batch_crawl_{timestamp}.json"
            
            await self.storage.save_json(
                data=batch_result,
                filename=filename,
                session_id=session_id
            )
            
            logger.debug(f"Saved batch result: {filename}")
            
        except Exception as e:
            logger.error(f"Error saving batch result: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup crawler resources."""
        try:
            await cleanup_browser()
            logger.info("Crawler cleanup completed")
        except Exception as e:
            logger.error(f"Error during crawler cleanup: {e}")


# Global crawler instance cache
_crawler_instances = {}

async def get_crawler_engine(user_email: Optional[str] = None) -> CrawlerEngine:
    """Get or create a crawler engine instance for a user."""
    key = user_email or "default"
    
    if key not in _crawler_instances:
        _crawler_instances[key] = CrawlerEngine(user_email)
    
    return _crawler_instances[key]

async def cleanup_all_crawlers():
    """Cleanup all crawler instances."""
    for crawler in _crawler_instances.values():
        await crawler.cleanup()
    _crawler_instances.clear()
    logger.info("All crawlers cleaned up")
