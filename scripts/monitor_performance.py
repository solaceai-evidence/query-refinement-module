"""
Performance Monitoring Dashboard for Load Testing

Real-time monitoring of API performance during load tests:
- Request metrics (response times, throughput, errors)
- Database connection pool status
- Redis connection stats
- System resources (CPU, memory)
- LLM API calls and costs

Usage:
    # Monitor local API
    poetry run python scripts/monitor_performance.py

    # Monitor remote API
    poetry run python scripts/monitor_performance.py --host http://api.example.com

    # Save metrics to file
    poetry run python scripts/monitor_performance.py --output metrics.json

    # Monitor for specific duration
    poetry run python scripts/monitor_performance.py --duration 600  # 10 minutes
"""

import argparse
import asyncio
import json
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

import httpx
import psutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.logging_utils import get_logger

logger = get_logger(__name__)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_HOST = "http://localhost:8000"
DEFAULT_INTERVAL = 5  # seconds
MAX_HISTORY = 120  # Keep 10 minutes of data (at 5s intervals)


# ============================================================================
# Metrics Collection
# ============================================================================

class MetricsCollector:
    """Collects and stores performance metrics."""

    def __init__(self, host: str, interval: int = DEFAULT_INTERVAL):
        self.host = host.rstrip("/")
        self.interval = interval
        self.client = httpx.AsyncClient(timeout=10.0)
        
        # Metric history (deques for efficient rolling windows)
        self.response_times: Deque[float] = deque(maxlen=MAX_HISTORY)
        self.error_counts: Deque[int] = deque(maxlen=MAX_HISTORY)
        self.request_counts: Deque[int] = deque(maxlen=MAX_HISTORY)
        self.timestamps: Deque[str] = deque(maxlen=MAX_HISTORY)
        
        # System metrics
        self.cpu_usage: Deque[float] = deque(maxlen=MAX_HISTORY)
        self.memory_usage: Deque[float] = deque(maxlen=MAX_HISTORY)
        
        # Database metrics
        self.db_pool_size: Deque[int] = deque(maxlen=MAX_HISTORY)
        self.db_checked_out: Deque[int] = deque(maxlen=MAX_HISTORY)
        
        # Counters
        self.total_requests = 0
        self.total_errors = 0
        self.start_time = time.time()

    async def check_health(self) -> Dict:
        """Check API health endpoint."""
        try:
            response = await self.client.get(f"{self.host}/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_readiness(self) -> Dict:
        """Check API readiness endpoint."""
        try:
            response = await self.client.get(f"{self.host}/ready")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            return {"status": "not ready", "error": str(e)}

    async def measure_response_time(self) -> float:
        """Measure API response time."""
        try:
            start = time.time()
            response = await self.client.get(f"{self.host}/health")
            elapsed = time.time() - start
            
            if response.status_code == 200:
                return elapsed * 1000  # Convert to ms
            else:
                self.total_errors += 1
                return -1  # Error indicator
        except Exception as e:
            self.total_errors += 1
            logger.error(f"Response time measurement failed: {e}")
            return -1

    def collect_system_metrics(self) -> Dict:
        """Collect system resource metrics."""
        try:
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "memory_available_mb": psutil.virtual_memory().available / (1024 * 1024),
                "disk_usage_percent": psutil.disk_usage("/").percent,
            }
        except Exception as e:
            logger.error(f"System metrics collection failed: {e}")
            return {}

    async def collect_metrics(self) -> Dict:
        """Collect all metrics for current interval."""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # API metrics
        health = await self.check_health()
        readiness = await self.check_readiness()
        response_time = await self.measure_response_time()
        
        # System metrics
        system = self.collect_system_metrics()
        
        # Update history
        self.timestamps.append(timestamp)
        self.response_times.append(response_time if response_time > 0 else 0)
        self.error_counts.append(1 if response_time < 0 else 0)
        self.cpu_usage.append(system.get("cpu_percent", 0))
        self.memory_usage.append(system.get("memory_percent", 0))
        
        self.total_requests += 1
        
        # Calculate statistics
        valid_response_times = [rt for rt in self.response_times if rt > 0]
        avg_response_time = (
            sum(valid_response_times) / len(valid_response_times)
            if valid_response_times
            else 0
        )
        
        error_rate = (
            sum(self.error_counts) / len(self.error_counts) * 100
            if self.error_counts
            else 0
        )
        
        uptime = time.time() - self.start_time
        
        metrics = {
            "timestamp": timestamp,
            "uptime_seconds": uptime,
            "health": health,
            "readiness": readiness,
            "response_time_ms": response_time,
            "avg_response_time_ms": avg_response_time,
            "error_rate_percent": error_rate,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "system": system,
        }
        
        return metrics

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


# ============================================================================
# Display Functions
# ============================================================================

def clear_screen():
    """Clear terminal screen."""
    print("\033[2J\033[H", end="")


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_status(status: str) -> str:
    """Format status with color."""
    if status == "healthy" or status == "ready":
        return f"\033[92m{status.upper()}\033[0m"  # Green
    elif status == "not ready":
        return f"\033[93m{status.upper()}\033[0m"  # Yellow
    else:
        return f"\033[91m{status.upper()}\033[0m"  # Red


def display_metrics(metrics: Dict):
    """Display metrics in terminal dashboard."""
    clear_screen()
    
    print("=" * 80)
    print("📊 QUERY REFINEMENT API - PERFORMANCE MONITOR")
    print("=" * 80)
    
    # Header
    print(f"\n🕐 Uptime: {format_uptime(metrics['uptime_seconds'])}")
    print(f"📅 Timestamp: {metrics['timestamp']}")
    
    # Health Status
    health_status = metrics['health'].get('status', 'unknown')
    ready_status = metrics['readiness'].get('status', 'unknown')
    print(f"\n💚 Health: {format_status(health_status)}")
    print(f"✅ Readiness: {format_status(ready_status)}")
    
    # Response Times
    print(f"\n⚡ RESPONSE TIMES")
    print(f"  Current: {metrics['response_time_ms']:.2f}ms")
    print(f"  Average: {metrics['avg_response_time_ms']:.2f}ms")
    
    # Error Rate
    error_color = "\033[91m" if metrics['error_rate_percent'] > 1 else "\033[92m"
    print(f"\n❌ ERROR RATE")
    print(f"  Rate: {error_color}{metrics['error_rate_percent']:.2f}%\033[0m")
    print(f"  Total Errors: {metrics['total_errors']} / {metrics['total_requests']}")
    
    # System Resources
    system = metrics.get('system', {})
    cpu = system.get('cpu_percent', 0)
    memory = system.get('memory_percent', 0)
    memory_avail = system.get('memory_available_mb', 0)
    disk = system.get('disk_usage_percent', 0)
    
    cpu_color = "\033[91m" if cpu > 80 else "\033[93m" if cpu > 60 else "\033[92m"
    mem_color = "\033[91m" if memory > 80 else "\033[93m" if memory > 60 else "\033[92m"
    
    print(f"\n💻 SYSTEM RESOURCES")
    print(f"  CPU: {cpu_color}{cpu:.1f}%\033[0m")
    print(f"  Memory: {mem_color}{memory:.1f}%\033[0m ({memory_avail:.0f}MB available)")
    print(f"  Disk: {disk:.1f}%")
    
    # Readiness Checks
    if 'checks' in metrics['readiness']:
        checks = metrics['readiness']['checks']
        print(f"\n🔍 DEPENDENCY CHECKS")
        for check_name, check_status in checks.items():
            status_icon = "✅" if check_status == "ok" else "❌"
            print(f"  {status_icon} {check_name.capitalize()}: {check_status}")
    
    print("\n" + "=" * 80)
    print("Press Ctrl+C to stop monitoring")
    print("=" * 80)


# ============================================================================
# Main Monitoring Loop
# ============================================================================

async def monitor(
    host: str,
    interval: int,
    duration: Optional[int] = None,
    output_file: Optional[str] = None,
):
    """
    Main monitoring loop.
    
    Args:
        host: API host URL
        interval: Polling interval in seconds
        duration: Total duration in seconds (None for infinite)
        output_file: Optional file to save metrics
    """
    collector = MetricsCollector(host, interval)
    all_metrics: List[Dict] = []
    
    try:
        logger.info(f"Starting performance monitoring: {host}")
        logger.info(f"Interval: {interval}s, Duration: {duration or 'infinite'}s")
        
        start_time = time.time()
        
        while True:
            # Collect metrics
            metrics = await collector.collect_metrics()
            all_metrics.append(metrics)
            
            # Display in terminal
            display_metrics(metrics)
            
            # Check duration
            if duration and (time.time() - start_time) >= duration:
                logger.info("Monitoring duration reached")
                break
            
            # Wait for next interval
            await asyncio.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user")
    except Exception as e:
        logger.error(f"Monitoring error: {e}", exc_info=True)
    finally:
        await collector.close()
        
        # Save metrics if requested
        if output_file and all_metrics:
            output_path = Path(output_file)
            with open(output_path, "w") as f:
                json.dump(
                    {
                        "host": host,
                        "interval": interval,
                        "duration": duration,
                        "start_time": all_metrics[0]["timestamp"],
                        "end_time": all_metrics[-1]["timestamp"],
                        "total_samples": len(all_metrics),
                        "metrics": all_metrics,
                    },
                    f,
                    indent=2,
                )
            logger.info(f"Metrics saved to: {output_path}")
        
        # Print summary
        if all_metrics:
            print("\n" + "=" * 80)
            print("📈 MONITORING SUMMARY")
            print("=" * 80)
            
            valid_times = [m["response_time_ms"] for m in all_metrics if m["response_time_ms"] > 0]
            total_errors = sum(m["error_rate_percent"] for m in all_metrics)
            avg_cpu = sum(m["system"].get("cpu_percent", 0) for m in all_metrics) / len(all_metrics)
            avg_memory = sum(m["system"].get("memory_percent", 0) for m in all_metrics) / len(all_metrics)
            
            print(f"\n⏱️  Response Times:")
            print(f"  Average: {sum(valid_times) / len(valid_times):.2f}ms")
            print(f"  Min: {min(valid_times):.2f}ms")
            print(f"  Max: {max(valid_times):.2f}ms")
            
            print(f"\n❌ Errors:")
            print(f"  Total: {all_metrics[-1]['total_errors']}")
            print(f"  Rate: {total_errors / len(all_metrics):.2f}%")
            
            print(f"\n💻 System:")
            print(f"  Avg CPU: {avg_cpu:.1f}%")
            print(f"  Avg Memory: {avg_memory:.1f}%")
            
            print(f"\n📊 Samples: {len(all_metrics)}")
            print(f"🕐 Duration: {format_uptime(time.time() - start_time)}")
            print("=" * 80)


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor Query Refinement API performance"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"API host URL (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Polling interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        help="Total monitoring duration in seconds (default: infinite)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for metrics (JSON format)",
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(
            monitor(
                host=args.host,
                interval=args.interval,
                duration=args.duration,
                output_file=args.output,
            )
        )
    except Exception as e:
        logger.error(f"Monitoring failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
