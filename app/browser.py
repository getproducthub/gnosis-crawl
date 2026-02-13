"""
Browser automation engine for gnosis-crawl
Ported from gnosis-wraith with enhanced stability and anti-detection
"""
import os
import random
import asyncio
import logging
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

from app.config import settings

logger = logging.getLogger(__name__)


def split_image_by_height(image_bytesio: BytesIO, viewport_width: int, output_format: str = 'PNG') -> list[BytesIO]:
    """
    Splits an image stored in a BytesIO object by height into segments.
    Uses reasonable proportions based on 8.5x11 aspect ratio (~2.5x viewport height).

    Args:
        image_bytesio (BytesIO): BytesIO object containing the image.
        viewport_width (int): Width of the viewport used for capture.
        output_format (str): Output format for segmented images (e.g., 'PNG', 'JPEG').

    Returns:
        List of BytesIO objects containing segmented images.
    """
    try:
        # Calculate reasonable max height based on 8.5x11 proportions
        # 8.5x11 aspect ratio: height = width * (11/8.5) = width * 1.294
        segment_height = int(viewport_width * (11/8.5))
        
        # Open the image from BytesIO
        image_bytesio.seek(0)
        image = Image.open(image_bytesio)
        
        width, height = image.size
        
        # If image is smaller than segment height, return as-is
        if height <= segment_height:
            image_bytesio.seek(0)
            return [image_bytesio]
        
        # Calculate number of segments needed
        num_segments = (height + segment_height - 1) // segment_height
        segments = []
        
        logger.info(f"Splitting {width}x{height} image into {num_segments} segments of {segment_height}px each")
        
        for i in range(num_segments):
            # Calculate segment boundaries
            top = i * segment_height
            bottom = min((i + 1) * segment_height, height)
            
            # Crop the segment
            segment = image.crop((0, top, width, bottom))
            
            # Save segment to BytesIO
            segment_bytesio = BytesIO()
            segment.save(segment_bytesio, format=output_format)
            segment_bytesio.seek(0)
            segments.append(segment_bytesio)
            
            logger.debug(f"Created segment {i + 1}/{num_segments}: {width}x{bottom - top}px")
        
        return segments
        
    except Exception as e:
        logger.error(f"Failed to split image: {e}")
        # Return original image as fallback
        image_bytesio.seek(0)
        return [image_bytesio]


class BrowserEngine:
    """Advanced browser automation with anti-detection and stability features."""
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._browser_lock = asyncio.Lock()
        
    async def start_browser(self, javascript_enabled: bool = True) -> None:
        """Start browser with enhanced configuration and anti-detection."""
        async with self._browser_lock:
            if self.browser and not self.browser.is_connected():
                logger.info("Browser disconnected, recreating")
                await self.close()
            
            if self.browser:
                logger.debug("Browser already running")
                return
                
            try:
                logger.info("Starting Playwright and browser")
                self.playwright = await async_playwright().start()
                
                # Enhanced browser arguments for stability and stealth
                browser_args = [
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-accelerated-video-decode',
                    '--disable-features=site-per-process',
                    '--disable-extensions',
                    '--disable-background-networking',
                    '--disable-default-apps',
                    '--disable-sync',
                    '--disable-translate',
                    '--hide-scrollbars',
                    '--metrics-recording-only',
                    '--mute-audio',
                    '--no-first-run',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
                
                # Add headless configuration
                headless_mode = settings.browser_headless
                if headless_mode:
                    browser_args.extend([
                        '--headless=new',
                        '--disable-notifications',
                        '--disable-infobars'
                    ])
                
                logger.info(f"Launching browser (headless={headless_mode}, js_enabled={javascript_enabled})")
                self.browser = await self.playwright.chromium.launch(
                    headless=headless_mode,
                    args=browser_args
                )
                
                # Create context with randomized fingerprint
                viewport = self._get_random_viewport()
                user_agent = self._get_random_user_agent()
                timezone_id = self._get_random_timezone()
                locale = self._get_random_locale()
                
                logger.info(f"Browser context: viewport={viewport}, timezone={timezone_id}")
                
                self.context = await self.browser.new_context(
                    viewport=viewport,
                    user_agent=user_agent,
                    locale=locale,
                    timezone_id=timezone_id,
                    has_touch=random.choice([True, False]),
                    java_script_enabled=javascript_enabled,
                    ignore_https_errors=True
                )
                
                # Create page with enhanced headers
                self.page = await self.context.new_page()
                await self._set_realistic_headers()
                
                logger.info("Browser started successfully")
                
            except Exception as e:
                logger.error(f"Failed to start browser: {e}", exc_info=True)
                await self.close()
                raise
    
    async def create_isolated_context(self, javascript_enabled: bool = True) -> tuple[BrowserContext, Page]:
        """Create a new isolated browser context and page for concurrent operations."""
        if not self.browser:
            logger.info("Browser not started, initializing")
            await self.start_browser(javascript_enabled=javascript_enabled)
        
        # Create new context with randomized fingerprint
        context_options = {
            'viewport': {
                'width': random.randint(1200, 1920),
                'height': random.randint(800, 1080)
            },
            'user_agent': self._get_random_user_agent(),
            'locale': random.choice(['en-US', 'en-GB', 'en-CA']),
            'timezone_id': random.choice([
                'America/New_York', 'America/Los_Angeles', 'Europe/London',
                'Europe/Paris', 'Asia/Tokyo', 'Australia/Sydney'
            ]),
            'permissions': [],
            'java_script_enabled': javascript_enabled
        }
        
        context = await self.browser.new_context(**context_options)
        page = await context.new_page()
        
        # Apply stealth configurations
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
        
        return context, page

    async def crawl_with_context(
        self,
        url: str,
        javascript_enabled: bool = True,
        timeout: int = 30000,
        take_screenshot: bool = False,
        javascript_payload: Optional[str] = None,
        wait_until: str = "domcontentloaded",
        wait_for_selector: Optional[str] = None,
        wait_after_load_ms: int = 1000
    ) -> tuple[str, dict, bytes]:
        """Crawl URL using an isolated context for concurrent operations."""
        context, page = await self.create_isolated_context(javascript_enabled)
        
        try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"Navigating to {url} (attempt {attempt + 1}/{max_retries})")

                    crawl_started_at = asyncio.get_running_loop().time()
                    wait_strategy = wait_until if wait_until in {"domcontentloaded", "networkidle", "selector"} else "domcontentloaded"
                    goto_wait_until = "domcontentloaded" if wait_strategy == "selector" else wait_strategy

                    navigation_started_at = asyncio.get_running_loop().time()
                    response = await page.goto(url, timeout=timeout, wait_until=goto_wait_until)
                    navigation_ms = int((asyncio.get_running_loop().time() - navigation_started_at) * 1000)

                    wait_started_at = asyncio.get_running_loop().time()
                    if wait_strategy == "selector" and wait_for_selector:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout)
                    if wait_after_load_ms > 0:
                        await asyncio.sleep(wait_after_load_ms / 1000.0)
                    wait_ms = int((asyncio.get_running_loop().time() - wait_started_at) * 1000)
                    
                    logger.info(f"Successfully navigated to {url}")
                    
                    # Execute user-provided JavaScript payload before capturing HTML
                    if javascript_enabled and javascript_payload:
                        try:
                            logger.info("Executing custom JavaScript payload")
                            await page.evaluate(
                                """
                                async payload => {
                                    const executor = new Function("return (async () => { " + payload + "\\n})();");
                                    try {
                                        return await executor();
                                    } catch (error) {
                                        console.error("Injected JavaScript payload failed", error);
                                        throw error;
                                    }
                                }
                                """,
                                javascript_payload
                            )
                            # Give DOM a brief moment to settle after script execution
                            await asyncio.sleep(0.5)
                            wait_ms += 500
                        except Exception as e:
                            logger.warning(f"JavaScript payload execution failed: {e}")
                    
                    # Get page content
                    content_started_at = asyncio.get_running_loop().time()
                    content = await page.content()
                    content_ms = int((asyncio.get_running_loop().time() - content_started_at) * 1000)
                    logger.debug(f"Retrieved content ({len(content)} characters)")
                    
                    # Get page info
                    page_info = {
                        "title": await page.title(),
                        "url": page.url,
                        "status_code": response.status if response else None,
                        "content_type": "text/html",
                        "content_length": len(content),
                        "render_mode": "js_rendered" if javascript_enabled else "html_only",
                        "wait_strategy": wait_strategy,
                        "timings_ms": {
                            "navigation_ms": navigation_ms,
                            "wait_ms": wait_ms,
                            "content_ms": content_ms,
                            "total_ms": int((asyncio.get_running_loop().time() - crawl_started_at) * 1000)
                        }
                    }
                    
                    # Take screenshot if requested
                    screenshot_data = None
                    if take_screenshot:
                        try:
                            # Capture full page screenshot
                            raw_screenshot = await page.screenshot(full_page=True)
                            logger.debug(f"Screenshot captured ({len(raw_screenshot)} bytes)")
                            
                            # Split image if it's very long (using viewport-proportional height)
                            screenshot_bytesio = BytesIO(raw_screenshot)
                            
                            # Get viewport width from context
                            viewport = await page.viewport_size()
                            viewport_width = viewport['width'] if viewport else 1429
                            
                            screenshot_segments = split_image_by_height(screenshot_bytesio, viewport_width)
                            
                            if len(screenshot_segments) > 1:
                                logger.info(f"Screenshot split into {len(screenshot_segments)} segments")
                                # Return all segments as a list
                                screenshot_data = [segment.getvalue() for segment in screenshot_segments]
                            else:
                                # Single image - return as bytes
                                screenshot_data = raw_screenshot
                                
                        except Exception as e:
                            logger.warning(f"Failed to take screenshot: {e}")
                            screenshot_data = None
                    
                    return content, page_info, screenshot_data
                    
                except Exception as e:
                    logger.warning(f"Navigation error on attempt {attempt + 1}: {e}")
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to navigate to {url} after {max_retries} attempts")
                        raise
                    
                    # Wait before retry
                    await asyncio.sleep(1)
        
        finally:
            # Always cleanup the isolated context
            try:
                await context.close()
            except Exception as e:
                logger.warning(f"Error closing context: {e}")

    async def navigate(self, url: str, javascript_enabled: bool = True, timeout: int = 30000) -> None:
        """Navigate to URL with enhanced error handling and retry logic."""
        if not self.page:
            logger.info("Browser not started, initializing")
            await self.start_browser(javascript_enabled=javascript_enabled)
        
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                logger.info(f"Navigating to {url} (attempt {retry_count + 1}/{max_retries + 1})")
                
                # Navigate with DOM content loaded strategy
                await self.page.goto(url, timeout=timeout, wait_until='domcontentloaded')
                
                # Wait for render stability
                logger.info("Waiting for render stability")
                await self._wait_for_render_stability(javascript_enabled)
                
                if javascript_enabled:
                    await asyncio.sleep(3)  # Additional JS execution time
                
                logger.info(f"Successfully navigated to {url}")
                return
                
            except Exception as e:
                retry_count += 1
                error_message = str(e)
                logger.warning(f"Navigation error on attempt {retry_count}: {error_message}")
                
                # Handle page crashes
                if "Page crashed" in error_message or "Target closed" in error_message:
                    logger.info("Page crash detected, recreating page")
                    try:
                        if self.page and not self.page.is_closed():
                            await self.page.close()
                        self.page = await self.context.new_page()
                        await self._set_realistic_headers()
                        logger.info("Created new page after crash")
                    except Exception as recovery_error:
                        logger.error(f"Error during page recreation: {recovery_error}")
                
                if retry_count > max_retries:
                    logger.error(f"Failed to navigate to {url} after {max_retries + 1} attempts")
                    raise
                
                await asyncio.sleep(2)  # Wait before retry
    
    async def get_content(self) -> str:
        """Get page HTML content."""
        if not self.page:
            raise Exception("Browser not started or page not available")
        
        try:
            content = await self.page.content()
            logger.debug(f"Retrieved content ({len(content)} characters)")
            return content
        except Exception as e:
            logger.error(f"Error getting page content: {e}")
            raise
    
    async def get_page_info(self) -> Dict[str, Any]:
        """Get comprehensive page information."""
        if not self.page:
            raise Exception("Browser not started or page not available")
        
        try:
            # Get basic page info
            title = await self.page.title()
            url = self.page.url
            
            # Get page metrics
            metrics = await self.page.evaluate("""() => {
                return {
                    elements: document.querySelectorAll('*').length,
                    links: document.querySelectorAll('a').length,
                    images: document.querySelectorAll('img').length,
                    scripts: document.querySelectorAll('script').length,
                    readyState: document.readyState,
                    contentLength: document.documentElement.innerHTML.length
                };
            }""")
            
            return {
                "title": title,
                "url": url,
                "metrics": metrics
            }
            
        except Exception as e:
            logger.error(f"Error getting page info: {e}")
            return {"title": "", "url": "", "metrics": {}}
    
    async def take_screenshot(self, path: str, mode: str = "full") -> bool:
        """Take screenshot with error handling and fallback."""
        if not self.page:
            raise Exception("Browser not started or page not available")
        
        try:
            if mode == "top":
                await self.page.screenshot(path=path, full_page=False)
                logger.info(f"Top viewport screenshot saved to {path}")
            elif mode == "full":
                await self.page.screenshot(path=path, full_page=True)
                logger.info(f"Full page screenshot saved to {path}")
            else:
                logger.info(f"Screenshot skipped (mode: {mode})")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            
            # Create error image as fallback
            try:
                self._create_error_image(path, str(e))
                logger.info(f"Created error image at {path}")
                return False
            except Exception as img_error:
                logger.error(f"Error creating error image: {img_error}")
                raise e
    
    async def execute_javascript(self, script: str) -> Any:
        """Execute JavaScript in the page context."""
        if not self.page:
            raise Exception("Browser not started or page not available")
        
        try:
            result = await self.page.evaluate(script)
            logger.debug(f"Executed JavaScript: {script[:100]}...")
            return result
        except Exception as e:
            logger.error(f"Error executing JavaScript: {e}")
            raise
    
    async def close(self) -> None:
        """Close browser and release resources."""
        async with self._browser_lock:
            try:
                if self.page and not self.page.is_closed():
                    await self.page.close()
                    self.page = None
                
                if self.context:
                    await self.context.close()
                    self.context = None
                
                if self.browser:
                    await self.browser.close()
                    self.browser = None
                
                if self.playwright:
                    await self.playwright.stop()
                    self.playwright = None
                
                logger.info("Browser closed successfully")
                
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
    
    async def _wait_for_render_stability(self, javascript_enabled: bool = False) -> bool:
        """Wait for page render stability by monitoring DOM changes."""
        if not javascript_enabled:
            await asyncio.sleep(1)
            return True
        
        try:
            await asyncio.sleep(1)  # Initial delay
            
            previous_count = -1
            stable_checks = 0
            max_checks = 10
            check_interval = 0.5
            
            for i in range(max_checks):
                current_count = await self.page.evaluate("""() => {
                    return document.querySelectorAll('*').length;
                }""")
                
                logger.debug(f"DOM stability check {i+1}/{max_checks}: {current_count} elements")
                
                if current_count == previous_count and current_count > 10:
                    stable_checks += 1
                    if stable_checks >= 2:
                        logger.info(f"DOM appears stable after {i+1} checks")
                        break
                else:
                    stable_checks = 0
                
                previous_count = current_count
                await asyncio.sleep(check_interval)
            
            # Additional wait for animations
            await asyncio.sleep(2)
            
            # Verify content exists
            content_check = await self.page.evaluate("""() => {
                const mainContent = document.querySelector('main') || 
                                    document.querySelector('#content') || 
                                    document.querySelector('.content') ||
                                    document.querySelector('article') ||
                                    document.querySelector('body');
                                    
                return mainContent ? mainContent.querySelectorAll('*').length : 0;
            }""")
            
            logger.info(f"Content elements found: {content_check}")
            
            if content_check < 5:
                logger.warning("Few content elements detected, waiting longer")
                await asyncio.sleep(3)
            
            return True
            
        except Exception as e:
            logger.warning(f"Error during render stability check: {e}")
            await asyncio.sleep(3)
            return False
    
    async def _set_realistic_headers(self) -> None:
        """Set realistic browser headers."""
        await self.page.set_extra_http_headers({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        })
    
    def _get_random_user_agent(self) -> str:
        """Return a random, realistic user agent string."""
        chrome_versions = [
            '120.0.6099.109', '121.0.6167.85', '122.0.6261.69',
            '123.0.6312.58', '124.0.6367.60', '125.0.6422.60'
        ]
        
        os_versions = [
            ('Windows NT 10.0; Win64; x64', 'Windows 10'),
            ('Windows NT 11.0; Win64; x64', 'Windows 11'),
            ('Macintosh; Intel Mac OS X 10_15_7', 'macOS'),
            ('X11; Linux x86_64', 'Linux'),
        ]
        
        chrome_version = random.choice(chrome_versions)
        os_info, _ = random.choice(os_versions)
        
        return f'Mozilla/5.0 ({os_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36'
    
    def _get_random_viewport(self) -> Dict[str, int]:
        """Return a random viewport size based on common screen resolutions."""
        common_resolutions = [
            {'width': 1366, 'height': 768},
            {'width': 1920, 'height': 1080},
            {'width': 1536, 'height': 864},
            {'width': 1440, 'height': 900},
            {'width': 1280, 'height': 800},
            {'width': 1680, 'height': 1050},
        ]
        
        selected = random.choice(common_resolutions)
        jitter = random.randint(-10, 10)
        
        return {
            'width': max(800, selected['width'] + jitter),
            'height': max(600, selected['height'] + jitter)
        }
    
    def _get_random_timezone(self) -> str:
        """Return a random timezone."""
        timezones = [
            'America/New_York', 'America/Chicago', 'America/Los_Angeles',
            'Europe/London', 'Europe/Paris', 'Asia/Tokyo'
        ]
        return random.choice(timezones)
    
    def _get_random_locale(self) -> str:
        """Return a random locale."""
        locales = ['en-US', 'en-GB', 'en-CA', 'fr-FR', 'de-DE']
        return random.choice(locales)
    
    def _create_error_image(self, path: str, error_message: str) -> None:
        """Create an error image when screenshot fails."""
        img = Image.new('RGB', (1280, 800), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("Arial", 20)
        except:
            font = ImageFont.load_default()
        
        draw.text((50, 50), "Error Capturing Page", fill=(255, 0, 0), font=font)
        draw.text((50, 100), f"Error: {error_message}", fill=(0, 0, 0), font=font)
        
        if self.page:
            draw.text((50, 150), f"URL: {self.page.url}", fill=(0, 0, 0), font=font)
        
        img.save(path)


# Global browser instance
_browser_engine = None

async def get_browser_engine() -> BrowserEngine:
    """Get or create the global browser engine instance."""
    global _browser_engine
    if _browser_engine is None:
        _browser_engine = BrowserEngine()
    return _browser_engine

async def cleanup_browser():
    """Cleanup the global browser instance."""
    global _browser_engine
    if _browser_engine:
        await _browser_engine.close()
        _browser_engine = None
