# Real-Time Progress Tracking

## Overview

The query refinement module provides real-time progress tracking for long-running refinement operations. This allows clients (web frontends, middleware integrations) to display progress indicators to users while refinement workflows execute in the background.

**Key Features:**
- 🎯 **13 granular progress stages** - From query creation to completion
- ⏱️ **Polling-based architecture** - Simple REST endpoint, 1-2 second polling intervals
- 🔒 **Secure access** - Progress only accessible by query owner
- 💾 **In-memory storage** - Fast access with automatic TTL cleanup (1 hour default)
- 📊 **Rich metadata** - LLM call counts, aspect/turn tracking, elapsed time
- 🛡️ **Thread-safe** - AsyncIO locks for concurrent access

## Architecture

### Polling vs. WebSocket

This implementation uses **polling** instead of WebSockets for simplicity:

✅ **Polling Advantages:**
- No persistent connections to manage
- Works through all proxies/load balancers
- Simpler client implementation
- Automatic reconnection on network issues
- Lower server resource usage for sporadic updates

❌ **WebSocket Trade-offs:**
- Would provide instant updates (vs 1-2s latency)
- More complex infrastructure requirements
- Better for millisecond-scale updates (not needed here)

**Verdict:** Polling provides 90% of benefits with 10% of complexity for this use case.

### Progress Stages

The workflow progresses through these stages:

| Stage                    | Progress % | Description                                  |
| ------------------------ | ---------- | -------------------------------------------- |
| `CREATED`                | 0%         | Query received and stored                    |
| `EXTRACTING_ASPECTS`     | 5%         | Analyzing query structure                    |
| `ASPECTS_EXTRACTED`      | 10%        | Identified refinement dimensions             |
| `GENERATING_SUGGESTIONS` | 20-40%     | LLM generating refinement options (per turn) |
| `SUGGESTIONS_READY`      | 40-50%     | Suggestions ready for user review            |
| `WAITING_FOR_USER`       | 50%        | Awaiting user input                          |
| `USER_REFINING`          | 50-70%     | Processing user selections                   |
| `SYNTHESIZING`           | 80%        | Generating final refined query               |
| `SYNTHESIS_COMPLETE`     | 90%        | Synthesis finished                           |
| `COMPLETED`              | 100%       | Refinement fully complete                    |
| `FAILED`                 | 100%       | Refinement failed (see error field)          |
| `CANCELLED`              | 100%       | User cancelled refinement                    |

## API Endpoint

### Get Progress

```http
GET /api/v1/refinement/queries/{query_id}/progress
Authorization: Bearer {access_token}
```

**Response:**

```json
{
  "query_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "GENERATING_SUGGESTIONS",
  "progress": 0.35,
  "message": "Generating refinement suggestions (turn 2 of 3)...",
  "started_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:12Z",
  "elapsed_seconds": 12.5,
  "turn_number": 2,
  "total_turns": 3,
  "aspects_count": 5,
  "suggestions_count": null,
  "llm_calls_made": 2,
  "error": null,
  "details": {
    "framework": "academic",
    "current_aspect": "methodology"
  }
}
```

**Status Codes:**
- `200 OK` - Progress retrieved successfully
- `401 Unauthorized` - Missing or invalid authentication
- `403 Forbidden` - User does not own this query
- `404 Not Found` - Query does not exist

**Notes:**
- For completed/old queries without tracking data, synthetic progress is returned (100%, COMPLETED stage)
- Progress entries expire after 1 hour (queries remain in database)
- Polling every 1-2 seconds provides good responsiveness

## Frontend Integration

### React Example

```javascript
import { useState, useEffect } from 'react';

function RefinementProgress({ queryId, accessToken }) {
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let intervalId = null;

    const fetchProgress = async () => {
      try {
        const response = await fetch(
          `/api/v1/refinement/queries/${queryId}/progress`,
          {
            headers: {
              'Authorization': `Bearer ${accessToken}`
            }
          }
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        setProgress(data);

        // Stop polling when complete
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(data.stage)) {
          if (intervalId) {
            clearInterval(intervalId);
          }
        }
      } catch (err) {
        setError(err.message);
        if (intervalId) {
          clearInterval(intervalId);
        }
      }
    };

    // Initial fetch
    fetchProgress();

    // Poll every 1.5 seconds
    intervalId = setInterval(fetchProgress, 1500);

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [queryId, accessToken]);

  if (error) {
    return <div className="error">Error: {error}</div>;
  }

  if (!progress) {
    return <div>Loading progress...</div>;
  }

  return (
    <div className="progress-container">
      <div className="progress-bar">
        <div 
          className="progress-fill" 
          style={{ width: `${progress.progress * 100}%` }}
        />
      </div>
      <div className="progress-info">
        <p className="stage">{progress.stage.replace(/_/g, ' ')}</p>
        <p className="message">{progress.message}</p>
        <p className="details">
          {progress.llm_calls_made > 0 && (
            <span>LLM calls: {progress.llm_calls_made} • </span>
          )}
          {progress.turn_number && (
            <span>Turn {progress.turn_number} of {progress.total_turns} • </span>
          )}
          <span>Elapsed: {Math.round(progress.elapsed_seconds)}s</span>
        </p>
      </div>
      {progress.error && (
        <div className="error-message">{progress.error}</div>
      )}
    </div>
  );
}
```

### Vue Example

```vue
<template>
  <div class="progress-container">
    <div v-if="error" class="error">{{ error }}</div>
    <div v-else-if="progress">
      <progress :value="progress.progress" max="1.0"></progress>
      <p class="stage">{{ formatStage(progress.stage) }}</p>
      <p class="message">{{ progress.message }}</p>
      <p class="details">
        <span v-if="progress.llm_calls_made">
          LLM calls: {{ progress.llm_calls_made }} •
        </span>
        <span v-if="progress.turn_number">
          Turn {{ progress.turn_number }} of {{ progress.total_turns }} •
        </span>
        <span>Elapsed: {{ Math.round(progress.elapsed_seconds) }}s</span>
      </p>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    queryId: String,
    accessToken: String
  },
  data() {
    return {
      progress: null,
      error: null,
      intervalId: null
    };
  },
  mounted() {
    this.startPolling();
  },
  beforeUnmount() {
    this.stopPolling();
  },
  methods: {
    async fetchProgress() {
      try {
        const response = await fetch(
          `/api/v1/refinement/queries/${this.queryId}/progress`,
          {
            headers: {
              'Authorization': `Bearer ${this.accessToken}`
            }
          }
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        this.progress = await response.json();

        // Stop polling when complete
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(this.progress.stage)) {
          this.stopPolling();
        }
      } catch (err) {
        this.error = err.message;
        this.stopPolling();
      }
    },
    startPolling() {
      this.fetchProgress();
      this.intervalId = setInterval(() => this.fetchProgress(), 1500);
    },
    stopPolling() {
      if (this.intervalId) {
        clearInterval(this.intervalId);
        this.intervalId = null;
      }
    },
    formatStage(stage) {
      return stage.replace(/_/g, ' ');
    }
  }
};
</script>
```

## Middleware Integration

### Python Client Example

```python
import time
import requests
from typing import Optional, Dict, Any

class RefinementProgressClient:
    """Client for polling refinement progress."""
    
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}
    
    def get_progress(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress for a query."""
        url = f"{self.base_url}/api/v1/refinement/queries/{query_id}/progress"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            response.raise_for_status()
    
    def wait_for_completion(
        self,
        query_id: str,
        poll_interval: float = 1.5,
        timeout: float = 300.0,
        callback=None
    ) -> Dict[str, Any]:
        """
        Wait for refinement to complete, optionally calling a callback on each update.
        
        Args:
            query_id: The query ID to monitor
            poll_interval: Seconds between polls (default 1.5)
            timeout: Maximum wait time in seconds (default 300)
            callback: Optional function called with progress data on each update
        
        Returns:
            Final progress data
        
        Raises:
            TimeoutError: If refinement doesn't complete within timeout
            Exception: If refinement fails
        """
        start_time = time.time()
        terminal_stages = {"COMPLETED", "FAILED", "CANCELLED"}
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Refinement did not complete within {timeout}s"
                )
            
            progress = self.get_progress(query_id)
            
            if not progress:
                raise ValueError(f"Query {query_id} not found")
            
            if callback:
                callback(progress)
            
            if progress["stage"] in terminal_stages:
                if progress["stage"] == "FAILED":
                    raise Exception(
                        f"Refinement failed: {progress.get('error', 'Unknown error')}"
                    )
                return progress
            
            time.sleep(poll_interval)

# Usage example
client = RefinementProgressClient(
    base_url="https://api.example.com",
    access_token="your_token_here"
)

# Simple progress display callback
def print_progress(progress):
    print(
        f"[{progress['stage']}] {progress['progress']*100:.0f}% - "
        f"{progress['message']}"
    )

try:
    final_progress = client.wait_for_completion(
        query_id="550e8400-e29b-41d4-a716-446655440000",
        callback=print_progress
    )
    print(f"Refinement completed in {final_progress['elapsed_seconds']:.1f}s")
except TimeoutError as e:
    print(f"Timeout: {e}")
except Exception as e:
    print(f"Refinement failed: {e}")
```

## Best Practices

### Polling Frequency

- **Recommended:** 1-2 seconds between polls
- **Too frequent (<500ms):** Unnecessary server load, no visible benefit
- **Too slow (>5s):** Poor user experience, appears "stuck"

### Error Handling

```javascript
async function fetchProgressSafely(queryId, accessToken) {
  const maxRetries = 3;
  let retries = 0;
  
  while (retries < maxRetries) {
    try {
      const response = await fetch(
        `/api/v1/refinement/queries/${queryId}/progress`,
        {
          headers: { 'Authorization': `Bearer ${accessToken}` },
          signal: AbortSignal.timeout(5000) // 5s timeout
        }
      );
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      retries++;
      
      if (retries === maxRetries) {
        throw error;
      }
      
      // Exponential backoff
      await new Promise(resolve => 
        setTimeout(resolve, Math.pow(2, retries) * 1000)
      );
    }
  }
}
```

### Stop Polling on Completion

Always stop polling when the refinement reaches a terminal state:

```javascript
if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(progress.stage)) {
  clearInterval(pollIntervalId);
}
```

### Display Recommendations

- **Progress bar:** Visual indicator of overall completion (0-100%)
- **Stage name:** Human-readable current stage (replace underscores with spaces)
- **Message:** Detailed status message from server
- **Metadata:** Show LLM calls, turn numbers, elapsed time for context
- **Error display:** Show error field prominently if stage is FAILED

## Internal Implementation

### Progress Models

```python
class ProgressStage(str, Enum):
    """All possible refinement stages."""
    CREATED = "CREATED"
    EXTRACTING_ASPECTS = "EXTRACTING_ASPECTS"
    ASPECTS_EXTRACTED = "ASPECTS_EXTRACTED"
    GENERATING_SUGGESTIONS = "GENERATING_SUGGESTIONS"
    SUGGESTIONS_READY = "SUGGESTIONS_READY"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    USER_REFINING = "USER_REFINING"
    SYNTHESIZING = "SYNTHESIZING"
    SYNTHESIS_COMPLETE = "SYNTHESIS_COMPLETE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class ProgressStatus(BaseModel):
    """Current progress status."""
    query_id: str
    stage: ProgressStage
    progress: float  # 0.0 to 1.0
    message: str
    started_at: datetime
    updated_at: datetime
    elapsed_seconds: float
    
    # Optional metadata
    turn_number: Optional[int] = None
    total_turns: Optional[int] = None
    aspects_count: Optional[int] = None
    suggestions_count: Optional[int] = None
    llm_calls_made: int = 0
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
```

### Progress Tracker Service

```python
class ProgressTracker:
    """Thread-safe in-memory progress tracking with TTL."""
    
    async def create(
        self,
        query_id: str,
        initial_stage: ProgressStage = ProgressStage.CREATED
    ) -> ProgressStatus:
        """Create initial progress entry."""
        
    async def update(
        self,
        query_id: str,
        update: ProgressUpdate
    ) -> Optional[ProgressStatus]:
        """Update existing progress."""
        
    async def get(self, query_id: str) -> Optional[ProgressStatus]:
        """Get current progress."""
        
    async def delete(self, query_id: str) -> bool:
        """Delete progress entry."""
        
    async def increment_llm_calls(self, query_id: str) -> None:
        """Increment LLM call counter."""
        
    async def cleanup_expired(self) -> int:
        """Remove expired entries (TTL exceeded)."""
```

### Helper Function

```python
async def track_progress(
    query_id: str,
    stage: ProgressStage,
    message: str = None,
    **kwargs
) -> None:
    """Convenience function for updating progress."""
    tracker = get_progress_tracker()
    
    update = ProgressUpdate(
        stage=stage,
        progress=STAGE_PROGRESS_MAP[stage],
        message=message or STAGE_MESSAGES[stage],
        **kwargs
    )
    
    await tracker.update(query_id, update)
```

## Workflow Integration Points

Progress tracking is integrated at these key points in the refinement workflow:

1. **Query Creation** (`POST /refinement/queries`)
   - Stage: `CREATED` → `EXTRACTING_ASPECTS`

2. **Aspect Extraction** (`start_refinement()`)
   - Stage: `EXTRACTING_ASPECTS` → `ASPECTS_EXTRACTED`

3. **Question Generation** (LLM calls for suggestions)
   - Stage: `GENERATING_SUGGESTIONS`
   - Increments `llm_calls_made` counter

4. **Suggestions Ready**
   - Stage: `SUGGESTIONS_READY` → `WAITING_FOR_USER`

5. **User Input** (`POST /refinement/queries/{id}/answer`)
   - Stage: `USER_REFINING`

6. **Synthesis** (when all aspects complete)
   - Stage: `SYNTHESIZING` → `SYNTHESIS_COMPLETE` → `COMPLETED`

7. **Error Handling** (any exception)
   - Stage: `FAILED` with error message

## Performance Characteristics

- **Storage:** In-memory dictionary (O(1) lookups)
- **Concurrency:** AsyncIO lock (thread-safe)
- **TTL:** Default 1 hour (configurable)
- **Memory usage:** ~1-2KB per query
- **Cleanup:** Manual via `cleanup_expired()` or automatic on access

**Capacity estimate:**
- 10,000 concurrent refinements = ~20MB memory
- 1,000 requests/second polling = minimal CPU impact

## Security Considerations

- ✅ **Authentication required:** Must provide valid access token
- ✅ **Authorization enforced:** Users can only access their own queries
- ✅ **No sensitive data:** Progress contains only operational metadata
- ✅ **Rate limiting:** Standard API rate limits apply to progress endpoint
- ✅ **TTL expiration:** Old progress data automatically removed

## Troubleshooting

### Progress Returns null

**Symptom:** `GET /queries/{id}/progress` returns synthetic progress (100%, COMPLETED)

**Causes:**
1. Query completed more than 1 hour ago (TTL expired)
2. Server restarted (in-memory storage cleared)
3. Query ID is invalid

**Solutions:**
- Accept synthetic progress for old queries
- For recent queries, check if refinement actually started
- Verify query ID is correct

### Progress Appears Stuck

**Symptom:** Progress percentage not updating

**Causes:**
1. LLM provider slow/unresponsive
2. Circuit breaker opened (LLM provider down)
3. Refinement actually hanging

**Solutions:**
- Check `llm_calls_made` - if incrementing, LLM calls are happening
- Check circuit breaker status at `/api/v1/monitoring/circuit-breakers`
- Check logs for errors or timeout messages

### High Polling Load

**Symptom:** Server experiencing load from progress polling

**Solutions:**
1. Increase polling interval (1.5s → 2-3s)
2. Implement exponential backoff for errors
3. Stop polling on terminal states
4. Consider caching progress responses (1s TTL)

## Related Documentation

- [Circuit Breaker](./CIRCUIT_BREAKER.md) - LLM provider failure handling
- [API Integration Guide](./api_integration_guide.md) - General API usage
- [User Commands](./user_commands.md) - Refinement workflow commands

## Future Enhancements

Potential improvements (not currently implemented):

1. **WebSocket Support** - Real-time push updates instead of polling
2. **Persistent Storage** - Database-backed progress for server restarts
3. **Progress History** - Historical progress timeline for completed queries
4. **Batch Progress** - Get progress for multiple queries in one request
5. **Server-Sent Events (SSE)** - Alternative to WebSockets with simpler infrastructure
6. **Progress Webhooks** - Notify external systems on stage transitions

For production use, the current polling-based implementation provides excellent UX with minimal complexity.
