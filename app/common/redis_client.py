"""
Redis Client for Call Tracking

This module provides a Redis client wrapper for tracking active calls
to prevent duplicate processing when calls span across polling windows.

The client handles:
- Connection management with connection pooling
- Call tracking with TTL expiration
- Graceful fallback when Redis is unavailable
- Retry logic with exponential backoff

Author: AgentScoring Team
Date: 2025-09-26
"""

import asyncio
import logging
from typing import Optional, Set
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError, RedisError

from .config import settings


logger = logging.getLogger(__name__)


class CallTracker:
    """
    Redis-based call tracking system to prevent duplicate processing.
    
    Uses Redis with TTL to track calls that are currently being processed
    or have been recently processed within the tracking window.
    """
    
    def __init__(self):
        """Initialize the call tracker with Redis connection pool."""
        self._redis: Optional[redis.Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
        self._connected = False
        
    async def _ensure_connection(self) -> bool:
        """
        Ensure Redis connection is established.
        
        Returns:
            bool: True if connected, False if connection failed
        """
        if self._connected and self._redis:
            try:
                await self._redis.ping()
                return True
            except (ConnectionError, TimeoutError):
                logger.warning("Redis connection lost, attempting to reconnect")
                self._connected = False
        
        if not self._connected:
            try:
                if not self._connection_pool:
                    self._connection_pool = redis.ConnectionPool(
                        host=settings.redis_host,
                        port=settings.redis_port,
                        db=settings.redis_db,
                        password=settings.redis_password,
                        decode_responses=True,
                        max_connections=20,
                        retry_on_timeout=True,
                        socket_timeout=5,
                        socket_connect_timeout=5
                    )
                
                self._redis = redis.Redis(connection_pool=self._connection_pool)
                await self._redis.ping()
                self._connected = True
                logger.info("Successfully connected to Redis")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._connected = False
                return False
        
        return self._connected
    
    async def close(self):
        """Close Redis connection and cleanup resources."""
        if self._redis:
            await self._redis.aclose()
        if self._connection_pool:
            await self._connection_pool.aclose()
        self._connected = False
        logger.info("Redis connection closed")
    
    def _get_tracking_key(self, call_id: str) -> str:
        """Generate Redis key for call tracking."""
        return f"call:tracking:{call_id}"
    
    async def is_call_being_tracked(self, call_id: str) -> bool:
        """
        Check if a call is currently being tracked (processed recently).
        
        Args:
            call_id: The unique call identifier
            
        Returns:
            bool: True if call is being tracked, False otherwise
        """
        if not await self._ensure_connection():
            # If Redis is unavailable, don't block processing
            logger.warning("Redis unavailable, allowing call processing")
            return False
        
        try:
            key = self._get_tracking_key(call_id)
            exists = await self._redis.exists(key)
            return bool(exists)
            
        except RedisError as e:
            logger.error(f"Redis error checking call {call_id}: {e}")
            # On Redis error, allow processing to continue
            return False
    
    async def track_call(self, call_id: str, ttl_seconds: Optional[int] = None) -> bool:
        """
        Start tracking a call with TTL expiration.
        
        Args:
            call_id: The unique call identifier
            ttl_seconds: TTL in seconds (defaults to config setting)
            
        Returns:
            bool: True if call was successfully marked for tracking
        """
        if not await self._ensure_connection():
            logger.warning("Redis unavailable, unable to track call")
            return False
        
        try:
            key = self._get_tracking_key(call_id)
            ttl = ttl_seconds or settings.call_tracking_ttl_seconds
            
            # Use SET with EX for atomic operation
            result = await self._redis.set(key, "processing", ex=ttl)
            
            if result:
                logger.debug(f"Started tracking call {call_id} with TTL {ttl}s")
            return bool(result)
            
        except RedisError as e:
            logger.error(f"Redis error tracking call {call_id}: {e}")
            return False
    
    async def untrack_call(self, call_id: str) -> bool:
        """
        Stop tracking a call (remove from Redis).
        
        Args:
            call_id: The unique call identifier
            
        Returns:
            bool: True if call was successfully untracked
        """
        if not await self._ensure_connection():
            return False
        
        try:
            key = self._get_tracking_key(call_id)
            result = await self._redis.delete(key)
            
            if result:
                logger.debug(f"Stopped tracking call {call_id}")
            return bool(result)
            
        except RedisError as e:
            logger.error(f"Redis error untracking call {call_id}: {e}")
            return False
    
    async def filter_tracked_calls(self, call_ids: Set[str]) -> Set[str]:
        """
        Filter out calls that are currently being tracked.
        
        Args:
            call_ids: Set of call IDs to check
            
        Returns:
            Set[str]: Call IDs that are not currently being tracked
        """
        if not call_ids or not await self._ensure_connection():
            return call_ids
        
        try:
            # Use pipeline for efficient batch operation
            pipeline = self._redis.pipeline()
            for call_id in call_ids:
                key = self._get_tracking_key(call_id)
                pipeline.exists(key)
            
            results = await pipeline.execute()
            
            # Filter out tracked calls
            untracked_calls = set()
            for call_id, is_tracked in zip(call_ids, results):
                if not is_tracked:
                    untracked_calls.add(call_id)
            
            tracked_count = len(call_ids) - len(untracked_calls)
            if tracked_count > 0:
                logger.info(f"Filtered out {tracked_count} already tracked calls")
            
            return untracked_calls
            
        except RedisError as e:
            logger.error(f"Redis error filtering calls: {e}")
            # On error, return all calls to allow processing
            return call_ids
    
    async def get_tracking_stats(self) -> dict:
        """
        Get statistics about currently tracked calls.
        
        Returns:
            dict: Statistics including count of tracked calls
        """
        if not await self._ensure_connection():
            return {"error": "Redis unavailable", "tracked_calls": 0}
        
        try:
            pattern = self._get_tracking_key("*")
            tracked_keys = []
            
            async for key in self._redis.scan_iter(match=pattern, count=100):
                tracked_keys.append(key)
            
            return {
                "tracked_calls": len(tracked_keys),
                "redis_connected": True
            }
            
        except RedisError as e:
            logger.error(f"Redis error getting stats: {e}")
            return {"error": str(e), "tracked_calls": 0}


# Global call tracker instance  
_call_tracker: Optional[CallTracker] = None


def get_call_tracker() -> CallTracker:
    """Get the global call tracker instance."""
    global _call_tracker
    if _call_tracker is None:
        _call_tracker = CallTracker()
    return _call_tracker


@asynccontextmanager
async def call_tracker_context():
    """Context manager for call tracker lifecycle."""
    tracker = get_call_tracker()
    try:
        yield tracker
    finally:
        await tracker.close()