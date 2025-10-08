"""
Gnosis-Crawl FastAPI Application
Pure API crawling service with AHP agent architecture
"""
import os
import logging
import uuid
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, AsyncGenerator
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import router
from app.job_routes import router as job_router
from app.tools.tool_registry import get_global_registry, ToolError
from app.core.middleware import ContentTypeMiddleware, AuthMiddleware
from app.auth import validate_token_from_query

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
CRAWL_SECRET_KEY = os.getenv("CRAWL_SECRET_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info(f"Starting Gnosis-Crawl agentic service on {settings.host}:{settings.port}")
    logger.info(f"Cloud mode: {settings.is_cloud_environment()}")
    logger.info(f"Auth service: {settings.gnosis_auth_url}")
    
    # Discover and register tools
    tool_registry = get_global_registry()
    try:
        discovered_schemas = tool_registry.discover_tools("app/tools")
        logger.info(f"Discovered {len(discovered_schemas)} crawling tools")
        for schema in discovered_schemas:
            logger.info(f"  - {schema['name']}: {schema['description']}")
    except Exception as e:
        logger.error(f"Failed to discover tools: {e}")
    
    yield
    
    # Shutdown  
    logger.info("Shutting down Gnosis-Crawl service")


# Auth Dependency for AHP Tool Routes
async def verify_internal_token(request: Request):
    """
    Dependency that validates the short-lived, internal HMAC token found in
    pre-signed tool URLs and populates request.state.actor with the payload.
    """
    bearer_token = request.query_params.get("bearer_token")
    if not bearer_token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        # Validates signature and expiration, returns the full payload
        token_payload = validate_token_from_query(bearer_token, CRAWL_SECRET_KEY)
        request.state.actor = token_payload  # Payload is {"sub": "...", "agent_id": "..."}
        request.state.bearer_token = bearer_token
        
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"Internal token validation failed with an unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Token validation failed")


# Create FastAPI application
app = FastAPI(
    title="Gnosis-Crawl",
    description="Agentic web crawling service with markdown generation",
    version="1.0.0",
    docs_url=None,  # Disable default docs for AHP pattern
    redoc_url=None,
    lifespan=lifespan
)

# Add middleware (order matters)
app.add_middleware(ContentTypeMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes (traditional REST endpoints)
app.include_router(router, prefix="/api")
app.include_router(job_router)  # Job routes already have /api prefix

# Health check endpoint (no auth required) - MUST be before catch-all route
@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    logger.debug("Health endpoint called - starting execution")
    try:
        tool_registry = get_global_registry()
        result = {
            "status": "healthy",
            "service": "gnosis-crawl",
            "version": "1.0.0",
            "cloud_mode": settings.is_cloud_environment(),
            "tools_registered": len(tool_registry.tools)
        }
        logger.debug(f"Health endpoint returning: {result}")
        return result
    except Exception as e:
        logger.error(f"Health endpoint error: {e}")
        raise

# Tools listing endpoint
@app.get("/tools")
async def list_tools():
    """List all available crawling tools"""
    tool_registry = get_global_registry()
    schemas = tool_registry.get_schemas()
    return {"tools": schemas}

# TODO: Agent search/suggestion endpoint - needs documentation and design review
# This endpoint will provide AI-driven tool discovery and suggestions for AHP integration
# @app.get("/@search")
# async def agent_search(q: str = ""):
#     """
#     Agent search and tool suggestion endpoint for AHP integration
#     
#     This endpoint enables AI agents to:
#     - Discover available crawling tools dynamically
#     - Get usage suggestions based on natural language queries
#     - Find appropriate tools for specific crawling tasks
#     
#     Future features:
#     - Semantic search across tool descriptions
#     - Usage pattern recommendations
#     - Tool chaining suggestions
#     - Context-aware tool selection
#     """
#     pass

# AHP Tool Routes - Dynamic tool execution (CATCH-ALL - must be last)
@app.get("/{tool_name}")
async def execute_tool(
    tool_name: str, 
    request: Request,
    _auth: Dict = Depends(verify_internal_token)
):
    """Execute a tool via AHP protocol"""
    tool_registry = get_global_registry()
    
    try:
        tool_instance = tool_registry.get_tool(tool_name)
    except ToolError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    # Extract parameters from query string
    params = dict(request.query_params)
    # Remove bearer_token from params as it's handled by auth
    params.pop("bearer_token", None)
    
    try:
        # Execute the tool
        result = await tool_instance.execute(**params)
        
        if result.success:
            return {"success": True, "data": result.data, "metadata": result.metadata}
        else:
            return {"success": False, "error": result.error}
            
    except Exception as e:
        logger.error(f"Tool execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )