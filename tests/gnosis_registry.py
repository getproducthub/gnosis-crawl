#!/usr/bin/env python3
"""
Gnosis service registry for test automation
Provides centralized service discovery to eliminate hardcoded ports
"""
import json
import os
from typing import Dict, Optional

class GnosisRegistry:
    """Service registry for gnosis stack components"""
    
    def __init__(self, config_path: Optional[str] = None, environment: str = "development"):
        """
        Initialize registry with service configuration
        
        Args:
            config_path: Path to gnosis_services.json, defaults to ../gnosis_services.json
            environment: Environment to use (development, test, production)
        """
        if config_path is None:
            # Default to gnosis_services.json in parent directory
            config_path = os.path.join(os.path.dirname(__file__), "..", "gnosis_services.json")
        
        self.config_path = config_path
        self.environment = environment
        self._services = self._load_services()
    
    def _load_services(self) -> Dict:
        """Load service configuration from JSON file"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            if self.environment not in config:
                raise ValueError(f"Environment '{self.environment}' not found in service config")
            
            return config[self.environment]
        except FileNotFoundError:
            raise FileNotFoundError(f"Service config not found at {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in service config: {e}")
    
    def get_service_url(self, service_name: str) -> str:
        """
        Get service URL by name
        
        Args:
            service_name: Name of service (e.g., 'gnosis-ahp', 'gnosis-crawl')
            
        Returns:
            Service URL string
            
        Raises:
            KeyError: If service not found
        """
        if service_name not in self._services:
            available = list(self._services.keys())
            raise KeyError(f"Service '{service_name}' not found. Available: {available}")
        
        url = self._services[service_name]["url"]
        
        # Handle environment variable substitution for production
        if url.startswith("${") and url.endswith("}"):
            env_var = url[2:-1]  # Remove ${ and }
            env_value = os.getenv(env_var)
            if not env_value:
                raise ValueError(f"Environment variable {env_var} not set for service {service_name}")
            return env_value
        
        return url
    
    def get_service_info(self, service_name: str) -> Dict:
        """Get full service info including URL and description"""
        if service_name not in self._services:
            available = list(self._services.keys())
            raise KeyError(f"Service '{service_name}' not found. Available: {available}")
        
        info = self._services[service_name].copy()
        # Resolve URL if needed
        info["url"] = self.get_service_url(service_name)
        return info
    
    def list_services(self) -> Dict[str, str]:
        """List all services with their URLs"""
        return {name: self.get_service_url(name) for name in self._services.keys()}
    
    @property
    def ahp_url(self) -> str:
        """Convenience property for AHP service URL"""
        return self.get_service_url("gnosis-ahp")
    
    @property 
    def crawl_url(self) -> str:
        """Convenience property for crawl service URL"""
        return self.get_service_url("gnosis-crawl")
    
    @property
    def ocr_url(self) -> str:
        """Convenience property for OCR service URL"""
        return self.get_service_url("gnosis-ocr")


# Global registry instance for test environment
registry = GnosisRegistry(environment="test")