"""
Configuration management for gnosis-crawl
Environment-based configuration following gnosis-ocr pattern
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables"""
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    
    # Storage Configuration
    storage_path: str = "./storage"
    running_in_cloud: bool = False
    gcs_bucket_name: Optional[str] = None
    
    # Authentication
    disable_auth: bool = False
    gnosis_auth_url: str = "http://gnosis-auth:5000"
    
    # Crawling Configuration
    max_concurrent_crawls: int = 5
    crawl_timeout: int = 30
    enable_javascript: bool = True
    enable_screenshots: bool = False
    
    # Browser Configuration
    browser_headless: bool = True
    browser_timeout: int = 30000
    
    # Cloud Configuration
    google_cloud_project: Optional[str] = None
    cloud_tasks_queue: str = "crawl-jobs"
    cloud_tasks_location: str = "us-central1"
    worker_service_url: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
        # Map environment variable names
        fields = {
            'running_in_cloud': {'env': 'RUNNING_IN_CLOUD'},
            'gcs_bucket_name': {'env': 'GCS_BUCKET_NAME'},
            'gnosis_auth_url': {'env': 'GNOSIS_AUTH_URL'},
            'max_concurrent_crawls': {'env': 'MAX_CONCURRENT_CRAWLS'},
            'crawl_timeout': {'env': 'CRAWL_TIMEOUT'},
            'enable_javascript': {'env': 'ENABLE_JAVASCRIPT'},
            'enable_screenshots': {'env': 'ENABLE_SCREENSHOTS'},
            'google_cloud_project': {'env': 'GOOGLE_CLOUD_PROJECT'},
            'cloud_tasks_queue': {'env': 'CLOUD_TASKS_QUEUE'},
            'cloud_tasks_location': {'env': 'CLOUD_TASKS_LOCATION'},
            'worker_service_url': {'env': 'WORKER_SERVICE_URL'},
        }

    def is_cloud_environment(self) -> bool:
        """Check if running in cloud environment"""
        return os.environ.get('RUNNING_IN_CLOUD', '').lower() == 'true'


# Global settings instance
settings = Settings()