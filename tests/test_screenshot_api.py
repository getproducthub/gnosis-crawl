"""
Test screenshot splitting through the actual API endpoints with proper auth
"""
import requests
import json
import time
import argparse


def get_bearer_token(service_token: str, ahp_url: str) -> str:
    """Get bearer token from AHP service."""
    print(f"Getting bearer token from {ahp_url}")
    
    response = requests.get(f"{ahp_url}/auth", params={"token": service_token})
    
    if response.status_code != 200:
        raise Exception(f"Failed to get bearer token: {response.status_code} - {response.text}")
    
    data = response.json()
    
    # AHP returns bearer token embedded in tool URLs
    tools = data.get("tools", [])
    if tools and len(tools) > 0:
        # Extract bearer_token from first tool URL
        first_tool_url = tools[0].get("url", "")
        if "bearer_token=" in first_tool_url:
            jwt_token = first_tool_url.split("bearer_token=")[1].split("&")[0]
            print(f"✓ Got JWT token: {jwt_token[:20]}...")
            return jwt_token
    
    raise Exception(f"No bearer token found in AHP response: {data}")


def test_screenshot_splitting(bearer_token: str, crawl_url: str):
    """Test screenshot splitting through the crawl API."""
    
    test_urls = [
        # Test the requested URL
        "https://gtnera.ai/",
        # Long page - should split
        "https://en.wikipedia.org/wiki/List_of_countries_by_population"
    ]
    
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    
    results = []
    
    for url in test_urls:
        print(f"\nTesting screenshot splitting: {url}")
        
        payload = {
            "url": url,
            "options": {
                "javascript": True,
                "screenshot": True,
                "screenshot_mode": "full",
                "timeout": 20
            }
        }
        
        try:
            response = requests.post(f"{crawl_url}/api/crawl", 
                                   headers=headers, 
                                   json=payload,
                                   timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                
                # Debug: show all response keys
                print(f"  API response keys: {list(data.keys())}")
                
                # Check if screenshot was split - API uses screenshot_url not screenshot_path
                screenshot_url = data.get("screenshot_url")
                
                if isinstance(screenshot_url, list):
                    print(f"✓ Screenshot SPLIT into {len(screenshot_url)} segments")
                    for i, url in enumerate(screenshot_url):
                        print(f"  Segment {i+1}: {url}")
                    segments = len(screenshot_url)
                elif screenshot_url:
                    print(f"✓ Single screenshot: {screenshot_url}")
                    segments = 1
                else:
                    print(f"✗ No screenshot captured")
                    print(f"  screenshot_url value: {screenshot_url}")
                    segments = 0
                
                print(f"  Title: {data.get('title', 'No title')[:60]}...")
                print(f"  Processing time: {data.get('processing_time', 0):.2f}s")
                print(f"  Markdown length: {len(data.get('markdown', ''))} chars")
                
                results.append({
                    'url': url,
                    'success': True,
                    'segments': segments
                })
                
            else:
                print(f"✗ API error: {response.status_code} - {response.text[:200]}")
                results.append({
                    'url': url,
                    'success': False,
                    'error': f"HTTP {response.status_code}"
                })
                
        except Exception as e:
            print(f"✗ Request error: {e}")
            results.append({
                'url': url,
                'success': False,
                'error': str(e)
            })
    
    # Summary
    print(f"\n{'='*60}")
    print("SCREENSHOT SPLITTING API TEST RESULTS")
    print(f"{'='*60}")
    
    successful = 0
    split_screenshots = 0
    
    for result in results:
        if result['success']:
            successful += 1
            segments = result['segments']
            if segments > 1:
                split_screenshots += 1
            print(f"✓ {result['url']}: {segments} segment{'s' if segments != 1 else ''}")
        else:
            print(f"✗ {result['url']}: {result['error']}")
    
    print(f"\nSummary:")
    print(f"- {successful}/{len(test_urls)} tests successful")
    print(f"- {split_screenshots} screenshots were split")
    print(f"- Screenshot splitting: {'WORKING' if split_screenshots > 0 else 'NOT TRIGGERED'}")
    
    return successful > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test screenshot splitting API")
    parser.add_argument("--service-token", required=True, help="Service token for authentication")
    parser.add_argument("--ahp-url", default="http://localhost:6793", help="AHP service URL")
    parser.add_argument("--crawl-url", default="http://localhost:6792", help="Crawl service URL")
    
    args = parser.parse_args()
    
    try:
        # Get bearer token
        bearer_token = get_bearer_token(args.service_token, args.ahp_url)
        print(f"✓ Got bearer token")
        
        # Test screenshot splitting
        success = test_screenshot_splitting(bearer_token, args.crawl_url)
        
        if success:
            print(f"\n✓ Screenshot splitting API tests completed!")
            exit(0)
        else:
            print(f"\n✗ All API tests failed!")
            exit(1)
            
    except Exception as e:
        print(f"✗ Test failed: {e}")
        exit(1)