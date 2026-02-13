"""
Job management system with cloud/local abstraction for gnosis-crawl
Adapted from gnosis-ocr job system
"""
import os
import json
import uuid
import asyncio
import logging
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor
import threading
from collections import deque
import httpx

from app.storage import CrawlStorageService
from app.config import settings
from app.crawler import CrawlerEngine

logger = logging.getLogger(__name__)

# Cloud Tasks client (lazy initialization)
_cloud_tasks_client = None

def get_cloud_tasks_client():
    """Get or create Cloud Tasks client (lazy initialization)"""
    global _cloud_tasks_client
    if _cloud_tasks_client is None and os.environ.get('RUNNING_IN_CLOUD') == 'true':
        try:
            from google.cloud import tasks_v2
            _cloud_tasks_client = tasks_v2.CloudTasksClient()
            logger.info("Cloud Tasks client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Tasks client: {e}")
            _cloud_tasks_client = None
    return _cloud_tasks_client

class JobType(Enum):
    """Types of jobs that can be created"""
    CRAWL_URL = "crawl_url"
    BATCH_CRAWL = "batch_crawl"
    MARKDOWN_ONLY = "markdown_only"
    AGENT_RUN = "agent_run"

class JobManager:
    """Manages submitting jobs to a queue without tracking their individual state in files."""

    def __init__(self, storage_service: CrawlStorageService):
        self.storage_service = storage_service
        self._is_cloud = os.environ.get('RUNNING_IN_CLOUD') == 'true'
        self._metadata_lock = asyncio.Lock()
        self.active_local_jobs = {}  # Track active local jobs by session_id

        if not self._is_cloud:
            self.executor = ThreadPoolExecutor(max_workers=2)
            logger.info("JobManager initialized in LOCAL mode with ThreadPoolExecutor(max_workers=2)")
        else:
            self.executor = None
            logger.info("JobManager initialized in CLOUD mode with Cloud Tasks")

    async def create_job(
        self,
        session_id: str,
        job_type: JobType,
        input_data: Dict[str, Any],
        user_email: Optional[str] = None,
        delay_seconds: int = 0,
        callback_url: Optional[str] = None,
        bearer_token: Optional[str] = None
    ) -> str:
        """Creates a job by submitting it directly to the queue."""
        job_id = str(uuid.uuid4())

        # Save job reference in metadata.json
        async with self._metadata_lock:
            try:
                metadata_bytes = await self.storage_service.get_file('metadata.json', session_id)
                metadata = json.loads(metadata_bytes.decode('utf-8'))
            except FileNotFoundError:
                metadata = {
                    "session_id": session_id,
                    "created_at": datetime.utcnow().isoformat(),
                    "jobs": []
                }
            
            if "jobs" not in metadata:
                metadata["jobs"] = []

            job_data = {
                "job_id": job_id,
                "job_type": job_type.value,
                "created_at": datetime.utcnow().isoformat(),
                "input_data": input_data
            }
            if callback_url:
                job_data["callback_url"] = callback_url
            if bearer_token:
                job_data["bearer_token"] = bearer_token
            metadata["jobs"].append(job_data)

            await self.storage_service.save_file(
                json.dumps(metadata, indent=2), 'metadata.json', session_id
            )

        logger.info(f"Submitting job {job_id} of type {job_type.value} for session {session_id}")

        # Prepare job payload
        job_payload = {
            "job_id": job_id,
            "session_id": session_id,
            "job_type": job_type,
            "input_data": input_data,
            "user_email": user_email,
            "delay_seconds": delay_seconds,
            "callback_url": callback_url,
            "bearer_token": bearer_token
        }
        
        # Create initial status file for crawl jobs
        if job_type in [JobType.CRAWL_URL, JobType.BATCH_CRAWL]:
            initial_status = {
                "session_id": session_id,
                "stages": {
                    "crawling": {
                        "status": "processing",
                        "is_running": True,
                        "total_urls": len(input_data.get("urls", [input_data.get("url")])),
                        "urls_processed": 0,
                        "progress_percent": 0,
                        "results": {}
                    }
                },
                "updated_at": datetime.utcnow().isoformat()
            }
            await self.storage_service.save_file(
                json.dumps(initial_status, indent=2), "session_status.json", session_id
            )

        if self._is_cloud:
            await self._create_cloud_task(job_payload)
        else:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self.executor, self._process_job_local_sync_wrapper, job_payload
            )
            self.active_local_jobs[session_id] = {"future": future, "job_type": job_type.value}

            # Add completion callback
            def handle_completion(fut):
                try:
                    result = fut.result()
                    logger.info(f"Job completed - ID: {result['job_id']}, Type: {result['job_type']}, Status: {result['status']}")
                except Exception as e:
                    logger.error(f"Job {job_id} callback error: {e}")
                finally:
                    if session_id in self.active_local_jobs:
                        del self.active_local_jobs[session_id]
            
            future.add_done_callback(handle_completion)
            logger.info(f"Job {job_id} submitted to ThreadPoolExecutor for local processing")

        return job_id

    def _process_job_local_sync_wrapper(self, job_payload: Dict) -> Dict:
        """Synchronous wrapper to run async job processing in a separate thread."""
        delay = job_payload.get("delay_seconds", 0)
        if delay > 0:
            import time
            logger.info(f"Local worker delaying job start by {delay} seconds.")
            time.sleep(delay)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        job_id = job_payload.get("job_id")
        job_type = job_payload.get("job_type")
        session_id = job_payload.get("session_id")
        user_email = job_payload.get("user_email")

        # Create fresh instances for this thread
        thread_storage_service = CrawlStorageService(user_email=user_email)
        thread_job_manager = JobManager(thread_storage_service)
        processor = JobProcessor(thread_job_manager, thread_storage_service)
        
        result = {
            "job_id": job_id,
            "job_type": job_type.value if hasattr(job_type, 'value') else str(job_type),
            "session_id": session_id,
            "status": "failed",
            "message": "Unknown error"
        }
        
        try:
            loop.run_until_complete(processor.process_job(job_payload))
            result["status"] = "completed"
            result["message"] = f"Job {job_type.value if hasattr(job_type, 'value') else job_type} completed successfully"
        except Exception as e:
            logger.error(f"Error processing job in background thread: {e}", exc_info=True)
            result["message"] = str(e)
        finally:
            loop.close()
            
        return result

    async def _create_cloud_task(self, job_payload: Dict):
        """Create a Cloud Task for job processing."""
        client = get_cloud_tasks_client()
        if not client:
            logger.error("Cloud Tasks client not available.")
            return

        try:
            project = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
            location = os.environ.get('CLOUD_TASKS_LOCATION', 'us-central1')
            queue = os.environ.get('CLOUD_TASKS_QUEUE', 'crawl-processing')
            worker_url = os.environ.get('WORKER_SERVICE_URL', '')
            
            if not all([project, location, queue, worker_url]):
                logger.error("Cloud Tasks environment variables not fully configured.")
                return

            parent = client.queue_path(project, location, queue)
            
            # Convert Enum to string for JSON serialization
            job_payload['job_type'] = job_payload['job_type'].value
            
            task = {
                "http_request": {
                    "http_method": "POST",
                    "url": f"{worker_url}/api/jobs/process-job",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(job_payload).encode('utf-8')
                },
                "dispatch_deadline": timedelta(seconds=300)  # 5 minutes per crawl task
            }
            
            delay_seconds = job_payload.get("delay_seconds", 0)
            if delay_seconds > 0:
                from google.protobuf import timestamp_pb2
                import time
                
                schedule_time = timestamp_pb2.Timestamp()
                future_time = time.time() + delay_seconds
                schedule_time.FromSeconds(int(future_time))
                task['schedule_time'] = schedule_time
                logger.info(f"Scheduling job {job_payload['job_id']} to run in {delay_seconds} seconds.")

            response = client.create_task(parent=parent, task=task)
            logger.info(f"Created Cloud Task {response.name} for job {job_payload['job_id']}")

        except Exception as e:
            logger.error(f"Failed to create Cloud Task for job {job_payload['job_id']}: {e}", exc_info=True)

    async def get_session_status(self, session_id: str) -> Optional[Dict]:
        """Retrieves the overall session status from its JSON file."""
        try:
            status_bytes = await self.storage_service.get_file("session_status.json", session_id)
            return json.loads(status_bytes.decode('utf-8'))
        except FileNotFoundError:
            return None

    async def update_session_status(self, session_id: str, status_data: Dict):
        """Updates session status file."""
        try:
            await self.storage_service.save_file(
                json.dumps(status_data, indent=2), "session_status.json", session_id
            )
            logger.debug(f"Updated session status for {session_id}")
        except Exception as e:
            logger.error(f"Error updating session status: {e}")


class JobProcessor:
    """Processes jobs by executing their logic."""

    def __init__(self, job_manager: JobManager, storage_service: CrawlStorageService):
        self.job_manager = job_manager
        self.storage_service = storage_service

    async def _send_callback(self, callback_url: str, bearer_token: Optional[str], session_id: str, status: str, data: Optional[Dict] = None):
        """Sends a callback to the specified URL."""
        if not callback_url:
            return

        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        payload = {
            "session_id": session_id,
            "status": status,
            "data": data or {}
        }

        try:
            logger.info(f"Sending callback to {callback_url} for session {session_id}")
            async with httpx.AsyncClient() as client:
                response = await client.post(callback_url, json=payload, headers=headers)
                response.raise_for_status()
            logger.info(f"Callback for session {session_id} sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send callback for session {session_id}: {e}")

    async def process_job(self, job_payload: Dict):
        """Process a job using the details passed in the payload."""
        job_id = job_payload.get("job_id")
        job_type = job_payload.get("job_type")
        session_id = job_payload.get("session_id")
        callback_url = job_payload.get("callback_url")
        bearer_token = job_payload.get("bearer_token")
        
        try:
            logger.info(f"Worker started processing job {job_id}")
            
            # Ensure job_type is an Enum member
            if not isinstance(job_type, JobType):
                job_type = JobType(job_type)

            if job_type == JobType.CRAWL_URL:
                await self._handle_crawl_url(job_payload)
            elif job_type == JobType.BATCH_CRAWL:
                await self._handle_batch_crawl(job_payload)
            elif job_type == JobType.MARKDOWN_ONLY:
                await self._handle_markdown_only(job_payload)
            elif job_type == JobType.AGENT_RUN:
                await self._handle_agent_run(job_payload)
            else:
                raise ValueError(f"Unknown job type: {job_type}")
            
            logger.info(f"Worker finished processing job {job_id}")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            await self._send_callback(callback_url, bearer_token, session_id, "failed", {"error": str(e)})
            raise

    async def _handle_crawl_url(self, job_payload: dict):
        """Handle single URL crawl job."""
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        url = input_data["url"]
        callback_url = job_payload.get("callback_url")
        bearer_token = job_payload.get("bearer_token")
        user_email = job_payload.get("user_email")

        # Create crawler instance
        crawler = CrawlerEngine(user_email)
        
        try:
            # Perform crawl
            result = await crawler.crawl_url(
                url=url,
                javascript=input_data.get("javascript", True),
                screenshot=input_data.get("screenshot", False),
                screenshot_mode=input_data.get("screenshot_mode", "full"),
                timeout=input_data.get("timeout"),
                session_id=session_id,
                dedupe_tables=input_data.get("dedupe_tables", True)
            )

            # Update status
            status_data = {
                "session_id": session_id,
                "stages": {
                    "crawling": {
                        "status": "complete" if result.success else "failed",
                        "is_running": False,
                        "total_urls": 1,
                        "urls_processed": 1,
                        "progress_percent": 100,
                        "results": {url: result.markdown if result.success else result.error_message}
                    }
                },
                "updated_at": datetime.utcnow().isoformat()
            }
            
            await self.job_manager.update_session_status(session_id, status_data)

            # Send completion callback
            if result.success:
                await self._send_callback(callback_url, bearer_token, session_id, "completed", {
                    "url": url,
                    "markdown": result.markdown,
                    "screenshot_path": result.screenshot_path
                })
            else:
                await self._send_callback(callback_url, bearer_token, session_id, "failed", {
                    "url": url,
                    "error": result.error_message
                })

        finally:
            await crawler.cleanup()

    async def _handle_batch_crawl(self, job_payload: dict):
        """Handle batch URL crawl job."""
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        urls = input_data["urls"]
        callback_url = job_payload.get("callback_url")
        bearer_token = job_payload.get("bearer_token")
        user_email = job_payload.get("user_email")

        # Create crawler instance
        crawler = CrawlerEngine(user_email)
        
        try:
            # Perform batch crawl
            batch_result = await crawler.batch_crawl(
                urls=urls,
                javascript=input_data.get("javascript", True),
                screenshot=input_data.get("screenshot", False),
                max_concurrent=input_data.get("max_concurrent", 3),
                session_id=session_id,
                dedupe_tables=input_data.get("dedupe_tables", True)
            )

            # Update final status
            status_data = {
                "session_id": session_id,
                "stages": {
                    "crawling": {
                        "status": "complete",
                        "is_running": False,
                        "total_urls": batch_result["summary"]["total"],
                        "urls_processed": batch_result["summary"]["success"],
                        "progress_percent": 100,
                        "results": {r["url"]: r["markdown"] for r in batch_result["results"]}
                    }
                },
                "updated_at": datetime.utcnow().isoformat()
            }
            
            await self.job_manager.update_session_status(session_id, status_data)

            # Send completion callback
            await self._send_callback(callback_url, bearer_token, session_id, "completed", {
                "batch_result": batch_result
            })

        finally:
            await crawler.cleanup()

    async def _handle_agent_run(self, job_payload: dict):
        """Handle an internal agent run (Mode B)."""
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        task = input_data["task"]
        callback_url = job_payload.get("callback_url")
        bearer_token = job_payload.get("bearer_token")
        user_email = job_payload.get("user_email")

        from app.agent.types import RunConfig
        from app.agent.dispatcher import Dispatcher
        from app.agent.engine import AgentEngine
        from app.agent.providers import create_provider_from_config
        from app.observability.trace import persist_trace
        from app.tools.tool_registry import get_global_registry

        # Build run config from input overrides + defaults
        run_config = settings.build_run_config()
        if input_data.get("max_steps"):
            run_config.max_steps = input_data["max_steps"]
        if input_data.get("max_wall_time_ms"):
            run_config.max_wall_time_ms = input_data["max_wall_time_ms"]
        if input_data.get("allowed_domains"):
            run_config.allowed_domains = input_data["allowed_domains"]
        if input_data.get("allowed_tools"):
            run_config.allowed_tools = input_data["allowed_tools"]

        # Wire up engine
        registry = get_global_registry()
        provider = create_provider_from_config()
        dispatcher = Dispatcher(registry, run_config)
        tool_schemas = registry.get_schemas()
        engine = AgentEngine(provider, dispatcher, tool_schemas)

        # Run the agent
        result, summary = await engine.run_task(task, run_config)

        # Persist trace
        try:
            await persist_trace(summary, session_id, user_email=user_email)
        except Exception as e:
            logger.error("Failed to persist agent trace: %s", e, exc_info=True)

        # Update session status
        status_data = {
            "session_id": session_id,
            "stages": {
                "agent": {
                    "status": "complete" if result.success else "failed",
                    "is_running": False,
                    "run_id": result.run_id,
                    "stop_reason": result.stop_reason.value,
                    "steps": result.steps,
                    "wall_time_ms": result.wall_time_ms,
                }
            },
            "updated_at": datetime.utcnow().isoformat(),
        }
        await self.job_manager.update_session_status(session_id, status_data)

        # Callback
        await self._send_callback(callback_url, bearer_token, session_id,
            "completed" if result.success else "failed",
            {
                "run_id": result.run_id,
                "response": result.response,
                "stop_reason": result.stop_reason.value,
                "steps": result.steps,
                "wall_time_ms": result.wall_time_ms,
                "error": result.error,
            },
        )

    async def _handle_markdown_only(self, job_payload: dict):
        """Handle markdown-only crawl job."""
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        url = input_data["url"]
        callback_url = job_payload.get("callback_url")
        bearer_token = job_payload.get("bearer_token")
        user_email = job_payload.get("user_email")

        # Create crawler instance
        crawler = CrawlerEngine(user_email)
        
        try:
            # Perform markdown-only crawl
            markdown = await crawler.crawl_for_markdown_only(
                url=url,
                javascript=input_data.get("javascript", True),
                timeout=input_data.get("timeout"),
                dedupe_tables=input_data.get("dedupe_tables", True)
            )

            # Send completion callback
            await self._send_callback(callback_url, bearer_token, session_id, "completed", {
                "url": url,
                "markdown": markdown
            })

        finally:
            await crawler.cleanup()
