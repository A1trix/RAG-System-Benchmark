"""Rate limiting middleware using token bucket algorithm.

In-process rate limiter (no external dependencies) matching n8n's concurrency controls.
"""
import time
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class TokenBucket:
    """Token bucket rate limiter for in-process use.
    
    Thread-safe token bucket that refills tokens at a fixed rate.
    """
    
    def __init__(self, capacity: float, refill_rate: float):
        """Initialize token bucket.
        
        Args:
            capacity: Maximum number of tokens in the bucket.
            refill_rate: Tokens per second to add to the bucket.
        """
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        
    def is_allowed(self) -> bool:
        """Check if a request is allowed and consume a token.
        
        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        # Refill tokens based on time passed
        now = time.time()
        self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.refill_rate)
        self.last_refill = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with per-endpoint configuration.
    
    Uses token bucket algorithm with in-process state (no Redis).
    Skips health check endpoints.
    """
    
    # Per-endpoint rate limits (requests per minute)
    DEFAULT_LIMITS = {
        "/query": (100, 60),      # 100 requests per 60 seconds (100 req/min)
        "/ingest": (20, 60),      # 20 requests per 60 seconds (20 req/min)
        "/delete": (20, 60),      # 20 requests per 60 seconds (20 req/min)
    }
    
    # Endpoints to skip (health checks, metrics)
    SKIPPED_ENDPOINTS = {"/health", "/metrics", "/"}
    
    def __init__(
        self,
        app: FastAPI,
        limits: Optional[dict] = None,
    ):
        """Initialize rate limiter middleware.
        
        Args:
            app: FastAPI application instance.
            limits: Optional dict mapping paths to (capacity, window_seconds) tuples.
                   Defaults to DEFAULT_LIMITS.
        """
        super().__init__(app)
        self.limits = limits or self.DEFAULT_LIMITS
        # Create token bucket for each configured endpoint
        self.buckets: dict[str, TokenBucket] = {}
        for path, (capacity, window_seconds) in self.limits.items():
            refill_rate = capacity / window_seconds
            self.buckets[path] = TokenBucket(capacity=capacity, refill_rate=refill_rate)
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting.
        
        Args:
            request: Incoming request.
            call_next: Next middleware/handler in chain.
            
        Returns:
            Response from handler or 429 error response.
        """
        path = request.url.path
        
        # Skip rate limiting for health endpoints
        if path in self.SKIPPED_ENDPOINTS:
            return await call_next(request)
        
        # Check rate limit if endpoint is configured
        if path in self.buckets:
            if not self.buckets[path].is_allowed():
                # Return 429 Too Many Requests
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Please try again later.",
                        "status_code": 429,
                    },
                )
        
        # Request allowed, continue to next middleware/handler
        return await call_next(request)


def add_rate_limiting(app: FastAPI, limits: Optional[dict] = None) -> FastAPI:
    """Add rate limiting middleware to FastAPI app.
    
    Args:
        app: FastAPI application instance.
        limits: Optional custom rate limits dict mapping paths to (capacity, window_seconds).
        
    Returns:
        The app with rate limiting middleware added.
    """
    app.add_middleware(RateLimiterMiddleware, limits=limits)
    return app
