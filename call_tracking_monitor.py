#!/usr/bin/env python3
"""
Call Tracking Monitor

A utility script to monitor and manage Redis-based call tracking
for the ingestion scheduler service.

Usage:
  python call_tracking_monitor.py stats    - Show tracking statistics  
  python call_tracking_monitor.py list     - List all tracked calls
  python call_tracking_monitor.py cleanup  - Clear all tracking entries
  python call_tracking_monitor.py test     - Test Redis connection
  
Author: AgentScoring Team
Date: 2025-09-26
"""

import asyncio
import sys
from datetime import datetime

from app.common.redis_client import get_call_tracker


async def show_stats():
    """Display call tracking statistics."""
    tracker = get_call_tracker()
    try:
        stats = await tracker.get_tracking_stats()
        
        print("=== Call Tracking Statistics ===")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if "error" in stats:
            print(f"❌ Error: {stats['error']}")
        else:
            print(f"✅ Redis Connected: {stats.get('redis_connected', False)}")
            print(f"📞 Tracked Calls: {stats.get('tracked_calls', 0)}")
            
    except Exception as e:
        print(f"❌ Failed to get stats: {e}")
    finally:
        await tracker.close()


async def list_tracked_calls():
    """List all currently tracked calls with their TTL."""
    tracker = get_call_tracker()
    try:
        # Access the Redis client directly for this operation
        if not await tracker._ensure_connection():
            print("❌ Cannot connect to Redis")
            return
            
        pattern = tracker._get_tracking_key("*")
        tracked_calls = []
        
        async for key in tracker._redis.scan_iter(match=pattern, count=100):
            ttl = await tracker._redis.ttl(key)
            call_id = key.replace("call:tracking:", "")
            tracked_calls.append((call_id, ttl))
        
        print("=== Currently Tracked Calls ===")
        if not tracked_calls:
            print("No calls are currently being tracked")
        else:
            print(f"Found {len(tracked_calls)} tracked calls:")
            for call_id, ttl in sorted(tracked_calls):
                if ttl > 0:
                    print(f"  📞 {call_id} (expires in {ttl}s)")
                elif ttl == -1:
                    print(f"  📞 {call_id} (no expiration)")
                else:
                    print(f"  📞 {call_id} (expired)")
                    
    except Exception as e:
        print(f"❌ Failed to list calls: {e}")
    finally:
        await tracker.close()


async def cleanup_all():
    """Clear all call tracking entries."""
    tracker = get_call_tracker()
    try:
        if not await tracker._ensure_connection():
            print("❌ Cannot connect to Redis")
            return
            
        # Get count before cleanup
        stats = await tracker.get_tracking_stats()
        before_count = stats.get('tracked_calls', 0)
        
        if before_count == 0:
            print("✅ No tracked calls to cleanup")
            return
            
        # Confirm cleanup
        response = input(f"⚠️  This will remove {before_count} tracked calls. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Cleanup cancelled")
            return
            
        # Delete all tracking keys
        pattern = tracker._get_tracking_key("*")
        deleted = 0
        
        async for key in tracker._redis.scan_iter(match=pattern, count=100):
            await tracker._redis.delete(key)
            deleted += 1
            
        print(f"✅ Cleaned up {deleted} call tracking entries")
        
    except Exception as e:
        print(f"❌ Failed to cleanup: {e}")
    finally:
        await tracker.close()


async def test_connection():
    """Test Redis connection and basic operations."""
    tracker = get_call_tracker()
    try:
        print("=== Redis Connection Test ===")
        
        # Test connection
        connected = await tracker._ensure_connection()
        if not connected:
            print("❌ Failed to connect to Redis")
            return
            
        print("✅ Connected to Redis successfully")
        
        # Test basic operations
        test_call_id = f"test_call_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Test tracking
        print(f"🧪 Testing call tracking with ID: {test_call_id}")
        
        # Check if call is being tracked (should be False)
        is_tracked = await tracker.is_call_being_tracked(test_call_id)
        print(f"   Initial tracking status: {is_tracked} (should be False)")
        
        # Start tracking
        success = await tracker.track_call(test_call_id, ttl_seconds=60)
        print(f"   Track call result: {success} (should be True)")
        
        # Check if call is now being tracked (should be True)
        is_tracked = await tracker.is_call_being_tracked(test_call_id)
        print(f"   After tracking status: {is_tracked} (should be True)")
        
        # Test filtering
        test_calls = {test_call_id, "non_tracked_call"}
        untracked = await tracker.filter_tracked_calls(test_calls)
        print(f"   Filtered calls: {untracked} (should contain only 'non_tracked_call')")
        
        # Cleanup test call
        await tracker.untrack_call(test_call_id)
        print(f"✅ Test completed successfully")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        await tracker.close()


async def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
        
    command = sys.argv[1].lower()
    
    if command == "stats":
        await show_stats()
    elif command == "list":
        await list_tracked_calls()
    elif command == "cleanup":
        await cleanup_all()
    elif command == "test":
        await test_connection()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())