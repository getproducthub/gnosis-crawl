#!/usr/bin/env python3
"""
Simple test for gnosis-crawl with service token
Usage: python test_simple.py --service-token <token>
"""
import asyncio
import httpx
import argparse
from gnosis_registry import registry

async def get_jwt_token(service_token, ahp_url=None, use_post=False):
    """Exchange service token for JWT token via AHP"""
    if ahp_url is None:
        ahp_url = registry.ahp_url
    
    method = "POST" if use_post else "GET"
    print(f"🔑 Getting JWT token from AHP at {ahp_url} ({method})...")
    
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            if use_post:
                response = await client.post(
                    f"{ahp_url}/auth",
                    json={"token": service_token}
                )
            else:
                response = await client.get(
                    f"{ahp_url}/auth",
                    params={"token": service_token}
                )
            
            if response.status_code == 200:
                data = response.json()
                # AHP returns bearer token embedded in tool URLs
                tools = data.get("tools", [])
                if tools and len(tools) > 0:
                    # Extract bearer_token from first tool URL
                    first_tool_url = tools[0].get("url", "")
                    if "bearer_token=" in first_tool_url:
                        jwt_token = first_tool_url.split("bearer_token=")[1].split("&")[0]
                        print(f"✅ Got JWT token: {jwt_token[:20]}...")
                        return jwt_token
                
                print("❌ No bearer token found in AHP response")
                return None
            else:
                print(f"❌ Failed to get JWT token: {response.status_code} - {response.text}")
                return None
    except Exception as e:
        print(f"❌ Error getting JWT token: {e}")
        return None

async def test_crawl_health(crawl_url, service_token):
    """Quick health + auth test"""
    print(f"🏥 Testing {crawl_url}")
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test health (no auth)
            health_response = await client.get(f"{crawl_url}/health")
            if health_response.status_code == 200:
                print("✅ Service is healthy")
            else:
                print(f"❌ Service unhealthy: {health_response.status_code}")
                return False
            
            # Get JWT token for authenticated tests
            jwt_token = await get_jwt_token(service_token, use_post=False)
            if not jwt_token:
                print("❌ Cannot test auth without JWT token")
                return False
            
            # Test authenticated endpoint
            headers = {"Authorization": f"Bearer {jwt_token}"}
            tools_response = await client.get(f"{crawl_url}/tools", headers=headers)
            
            if tools_response.status_code == 200:
                print("✅ Authentication working")
                tools = tools_response.json().get("tools", [])
                print(f"   Available tools: {len(tools)}")
                return True
            else:
                print(f"❌ Auth failed: {tools_response.status_code}")
                print(f"   Response: {tools_response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Simple crawl service test")
    parser.add_argument("--service-token", required=True, help="Service token")
    parser.add_argument("--crawl-url", help="Crawl service URL (defaults to registry)")
    parser.add_argument("--use-post", action="store_true", help="Use POST to test redirect")
    args = parser.parse_args()
    
    # Use registry if no URL provided
    crawl_url = args.crawl_url or registry.crawl_url
    
    print("🧪 Simple Crawl Service Test")
    print("=" * 40)
    print(f"AHP: {registry.ahp_url}")
    print(f"Crawl: {crawl_url}")
    print(f"Method: {'POST (with redirect)' if args.use_post else 'GET'}")
    print("=" * 40)
    
    success = asyncio.run(test_crawl_health(crawl_url, args.service_token))
    
    if success:
        print("\n🎉 Ready for batch testing!")
        print(f"Next: python test_batch_crawl.py --service-token {args.service_token}")
    else:
        print("\n❌ Fix service issues before batch testing")

if __name__ == "__main__":
    main()