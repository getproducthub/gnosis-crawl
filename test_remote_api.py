"""
Remote API Testing Script for gnosis-crawl
Test the deployed API with various scenarios
"""
import requests
import json
import time
from typing import Optional, Dict, Any

# Configuration - UPDATE THESE
API_BASE_URL = "https://crawler-agent-11733-2111b026-6tr5gw8l.onporter.run/"  # Update with actual URL
CUSTOMER_ID = "kordless"  # Your test customer ID
BEARER_TOKEN = None  # Set if testing with auth: "your-bearer-token-here"

# Test URLs
TEST_URLS = {
    "simple": "https://example.com",
    "complex": "https://news.ycombinator.com",
    "with_js": "https://www.github.com"
}


class APITester:
    """Test harness for gnosis-crawl API"""
    
    def __init__(self, base_url: str, customer_id: str, bearer_token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.customer_id = customer_id
        self.bearer_token = bearer_token
        self.session = requests.Session()
        
        # Set auth header if token provided
        if self.bearer_token:
            self.session.headers.update({
                "Authorization": f"Bearer {self.bearer_token}"
            })
    
    def print_section(self, title: str):
        """Print a section header"""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}\n")
    
    def print_result(self, success: bool, message: str):
        """Print test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {message}")
    
    def test_health(self) -> bool:
        """Test health endpoint"""
        self.print_section("Testing Health Endpoint")
        
        try:
            response = self.session.get(f"{self.base_url}/health")
            success = response.status_code == 200
            
            if success:
                data = response.json()
                print(f"Status: {data.get('status')}")
                print(f"Service: {data.get('service')}")
                print(f"Version: {data.get('version')}")
                print(f"Cloud Mode: {data.get('cloud_mode')}")
            
            self.print_result(success, f"Health check - Status {response.status_code}")
            return success
            
        except Exception as e:
            self.print_result(False, f"Health check failed: {e}")
            return False
    
    def test_single_crawl(self, url: str, use_customer_id: bool = True) -> Optional[Dict[str, Any]]:
        """Test single URL crawl"""
        self.print_section(f"Testing Single Crawl: {url}")
        
        payload = {
            "url": url,
            "options": {
                "javascript": False,
                "screenshot": False,
                "timeout": 30
            }
        }
        
        if use_customer_id:
            payload["customer_id"] = self.customer_id
        
        try:
            print(f"Request payload: {json.dumps(payload, indent=2)}")
            response = self.session.post(
                f"{self.base_url}/api/crawl",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"\nResponse Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {data.get('success')}")
                print(f"URL: {data.get('url')}")
                print(f"Customer ID: {data.get('metadata', {}).get('customer_identifier')}")
                print(f"Session ID: {data.get('metadata', {}).get('session_id')}")
                print(f"HTML Length: {len(data.get('html', ''))}")
                print(f"Markdown Length: {len(data.get('markdown', ''))}")
                
                self.print_result(data.get('success', False), f"Single crawl completed")
                return data
            else:
                print(f"Error Response: {response.text}")
                self.print_result(False, f"Single crawl failed - Status {response.status_code}")
                return None
                
        except Exception as e:
            self.print_result(False, f"Single crawl exception: {e}")
            return None
    
    def test_markdown_only(self, url: str) -> Optional[Dict[str, Any]]:
        """Test markdown-only crawl"""
        self.print_section(f"Testing Markdown-Only Crawl: {url}")
        
        payload = {
            "url": url,
            "customer_id": self.customer_id,
            "options": {
                "javascript": False,
                "timeout": 30
            }
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/markdown",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {data.get('success')}")
                print(f"Markdown Length: {len(data.get('markdown', ''))}")
                print(f"Markdown Preview:\n{data.get('markdown', '')[:200]}...")
                
                self.print_result(data.get('success', False), "Markdown crawl completed")
                return data
            else:
                print(f"Error Response: {response.text}")
                self.print_result(False, f"Markdown crawl failed - Status {response.status_code}")
                return None
                
        except Exception as e:
            self.print_result(False, f"Markdown crawl exception: {e}")
            return None
    
    def test_batch_crawl(self, urls: list) -> Optional[Dict[str, Any]]:
        """Test batch crawl"""
        self.print_section(f"Testing Batch Crawl: {len(urls)} URLs")
        
        payload = {
            "urls": urls,
            "customer_id": self.customer_id,
            "options": {
                "javascript": False,
                "screenshot": False,
                "max_concurrent": 3
            }
        }
        
        try:
            print(f"Crawling URLs: {', '.join(urls)}")
            response = self.session.post(
                f"{self.base_url}/api/batch",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"\nResponse Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {data.get('success')}")
                print(f"Job ID: {data.get('job_id')}")
                print(f"Total URLs: {data.get('total_urls')}")
                print(f"Message: {data.get('message')}")
                
                if 'summary' in data:
                    summary = data['summary']
                    print(f"\nSummary:")
                    print(f"  Total: {summary.get('total')}")
                    print(f"  Success: {summary.get('success')}")
                    print(f"  Failed: {summary.get('failed')}")
                
                self.print_result(data.get('success', False), "Batch crawl completed")
                return data
            else:
                print(f"Error Response: {response.text}")
                self.print_result(False, f"Batch crawl failed - Status {response.status_code}")
                return None
                
        except Exception as e:
            self.print_result(False, f"Batch crawl exception: {e}")
            return None
    
    def test_session_files(self, session_id: str) -> bool:
        """Test session file listing"""
        self.print_section(f"Testing Session File Listing: {session_id}")
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/sessions/{session_id}/files",
                params={"customer_id": self.customer_id}
            )
            
            print(f"Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Session ID: {data.get('session_id')}")
                print(f"Files found: {len(data.get('files', []))}")
                
                for file_info in data.get('files', [])[:5]:  # Show first 5
                    print(f"  - {file_info.get('name')} ({file_info.get('size')} bytes)")
                
                self.print_result(True, "Session files listed")
                return True
            else:
                print(f"Error Response: {response.text}")
                self.print_result(False, f"Session files failed - Status {response.status_code}")
                return False
                
        except Exception as e:
            self.print_result(False, f"Session files exception: {e}")
            return False
    
    def test_without_customer_id(self, url: str) -> bool:
        """Test crawl without customer_id (should use anonymous or fail)"""
        self.print_section("Testing Without Customer ID")
        
        payload = {
            "url": url,
            "options": {"javascript": False}
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/crawl",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                customer_id = data.get('metadata', {}).get('customer_identifier')
                print(f"Customer Identifier: {customer_id}")
                
                if self.bearer_token:
                    success = customer_id and customer_id != "anonymous@gnosis-crawl.local"
                    self.print_result(success, "Used authenticated user email")
                else:
                    success = customer_id == "anonymous@gnosis-crawl.local"
                    self.print_result(success, "Used anonymous identifier")
                
                return success
            else:
                self.print_result(False, f"Request failed - Status {response.status_code}")
                return False
                
        except Exception as e:
            self.print_result(False, f"Exception: {e}")
            return False
    
    def test_storage_debug(self) -> bool:
        """Test storage debug endpoint to see where files are"""
        self.print_section("Testing Storage Debug Info")
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/debug/storage",
                params={"customer_id": self.customer_id}
            )
            
            print(f"Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Customer Hash: {data.get('customer_hash')}")
                print(f"Storage Root: {data.get('storage_root')}")
                print(f"Customer Path: {data.get('customer_path')}")
                print(f"Path Exists: {data.get('customer_path_exists')}")
                print(f"Total Sessions: {data.get('total_sessions', 0)}")
                
                for session in data.get('sessions', [])[:3]:  # Show first 3
                    print(f"\n  Session: {session.get('session_id')}")
                    print(f"  Files: {len(session.get('files', []))}")
                    for file_info in session.get('files', [])[:5]:  # First 5 files
                        print(f"    - {file_info.get('relative_path')} ({file_info.get('size')} bytes)")
                
                self.print_result(True, "Storage debug info retrieved")
                return True
            else:
                print(f"Error Response: {response.text}")
                self.print_result(False, f"Storage debug failed - Status {response.status_code}")
                return False
                
        except Exception as e:
            self.print_result(False, f"Storage debug exception: {e}")
            return False
    
    def run_all_tests(self):
        """Run complete test suite"""
        print(f"\n{'#'*60}")
        print(f"  GNOSIS-CRAWL API TEST SUITE")
        print(f"{'#'*60}")
        print(f"\nBase URL: {self.base_url}")
        print(f"Customer ID: {self.customer_id}")
        print(f"Auth Token: {'Set' if self.bearer_token else 'Not Set'}")
        
        results = []
        
        # Test 1: Health Check
        results.append(("Health Check", self.test_health()))
        time.sleep(1)
        
        # Test 2: Simple Crawl
        crawl_result = self.test_single_crawl(TEST_URLS["simple"])
        results.append(("Simple Crawl", crawl_result is not None))
        time.sleep(1)
        
        # Test 3: Markdown Only
        markdown_result = self.test_markdown_only(TEST_URLS["simple"])
        results.append(("Markdown Only", markdown_result is not None))
        time.sleep(1)
        
        # Test 4: Batch Crawl
        batch_result = self.test_batch_crawl([TEST_URLS["simple"], TEST_URLS["complex"]])
        results.append(("Batch Crawl", batch_result is not None))
        
        # Test 5: Session Files (if we have a session ID)
        if crawl_result and 'metadata' in crawl_result:
            session_id = crawl_result['metadata'].get('session_id')
            if session_id:
                time.sleep(1)
                results.append(("Session Files", self.test_session_files(session_id)))
        
        # Test 6: Without Customer ID
        time.sleep(1)
        results.append(("No Customer ID", self.test_without_customer_id(TEST_URLS["simple"])))
        
        # Print Summary
        self.print_section("TEST SUMMARY")
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status}: {test_name}")
        
        print(f"\n{'='*60}")
        print(f"Results: {passed}/{total} tests passed")
        print(f"{'='*60}\n")
        
        return passed == total


def main():
    """Main test runner"""
    print("\n🚀 Starting gnosis-crawl API tests...\n")
    
    # Update these values before running
    if API_BASE_URL == "http://your-deployed-url.com":
        print("❌ ERROR: Please update API_BASE_URL in the script!")
        print("Set API_BASE_URL to your deployed service URL")
        return
    
    # Create tester instance
    tester = APITester(
        base_url=API_BASE_URL,
        customer_id=CUSTOMER_ID,
        bearer_token=BEARER_TOKEN
    )
    
    # Run all tests
    success = tester.run_all_tests()
    
    if success:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed. Check output above.")


if __name__ == "__main__":
    main()
