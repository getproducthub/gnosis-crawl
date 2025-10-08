"""
Simple crawl test that dumps markdown content
"""
import requests
import json
import os
import argparse
from pathlib import Path


def load_or_save_token(token_arg: str = None) -> str:
    """Load token from .auth directory or save provided token."""
    auth_dir = Path(__file__).parent / ".auth"
    token_file = auth_dir / "service_token.txt"
    
    # Create .auth directory if it doesn't exist
    auth_dir.mkdir(exist_ok=True)
    
    if token_arg:
        # Save new token
        token_file.write_text(token_arg.strip())
        print(f"✓ Token saved to {token_file}")
        return token_arg
    elif token_file.exists():
        # Load existing token
        token = token_file.read_text().strip()
        print(f"✓ Token loaded from {token_file}")
        return token
    else:
        raise Exception("No token provided and no saved token found. Use --service-token to provide one.")


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


def crawl_and_dump_markdown(bearer_token: str, url: str, crawl_url: str):
    """Crawl URL and dump the markdown."""
    print(f"\nCrawling: {url}")
    
    payload = {
        "url": url,
        "options": {
            "javascript": True,
            "screenshot": True,
            "screenshot_mode": "full",
            "timeout": 30
        }
    }
    
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(f"{crawl_url}/api/crawl", 
                               headers=headers, 
                               json=payload,
                               timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✓ Crawl successful")
            print(f"  Title: {data.get('metadata', {}).get('title', 'No title')}")
            print(f"  Processing time: {data.get('metadata', {}).get('processing_time', 0):.2f}s")
            
            # Check screenshot
            screenshot_url = data.get("screenshot_url")
            if isinstance(screenshot_url, list):
                print(f"  Screenshot SPLIT into {len(screenshot_url)} segments:")
                for i, path in enumerate(screenshot_url):
                    print(f"    Segment {i+1}: {path}")
            elif screenshot_url:
                print(f"  Screenshot: {screenshot_url}")
            else:
                print(f"  No screenshot captured")
            
            # Dump markdown
            markdown = data.get('markdown', '')
            if markdown:
                print(f"\n{'='*60}")
                print("MARKDOWN CONTENT:")
                print(f"{'='*60}")
                print(markdown)
                print(f"{'='*60}")
                print(f"Total markdown length: {len(markdown)} characters")
            else:
                print("No markdown content returned")
                
            return True
            
        else:
            print(f"✗ API error: {response.status_code} - {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"✗ Request error: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple crawl test with markdown dump")
    parser.add_argument("url", nargs="?", default="https://gtnera.ai/", help="URL to crawl (default: https://gtnera.ai/)")
    parser.add_argument("--service-token", help="Service token for authentication (will be saved)")
    parser.add_argument("--ahp-url", default="http://localhost:6793", help="AHP service URL")
    parser.add_argument("--crawl-url", default="http://localhost:6792", help="Crawl service URL")
    
    args = parser.parse_args()
    
    try:
        # Load or save token
        service_token = load_or_save_token(args.service_token)
        
        # Get bearer token
        bearer_token = get_bearer_token(service_token, args.ahp_url)
        
        # Crawl and dump markdown
        success = crawl_and_dump_markdown(bearer_token, args.url, args.crawl_url)
        
        if success:
            print(f"\n✓ Crawl test completed!")
        else:
            print(f"\n✗ Crawl test failed!")
            exit(1)
            
    except Exception as e:
        print(f"✗ Test failed: {e}")
        exit(1)