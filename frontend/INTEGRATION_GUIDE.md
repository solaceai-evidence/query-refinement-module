# Frontend Integration Guide - Progress Tracking & Circuit Breaker

This document describes how frontend clients should integrate progress tracking and circuit breaker monitoring when running against the production microservice stack.

## Deployment Context

Canonical production routing:

- Browser traffic enters through nginx on `http(s)://<host>`
- API calls use `/api/v1/...` from that same origin
- Avoid hardcoding direct `:8001` URLs in browser code for production

Recommended frontend environment variable pattern:

- `VITE_API_BASE_URL=/api/v1` (same-origin via nginx)

This keeps CORS simpler and matches the deployment model in `docker-compose.yml + docker-compose.prod.yml`.

## Overview

Two operational features are exposed by backend APIs:

1. **Real-Time Progress Tracking** - Polling updates for long-running refinement operations
2. **Circuit Breaker Monitoring** - LLM provider health and circuit-breaker state

## Progress Tracking Integration

### 1. Custom Hook: `useProgressTracking`

Location: `frontend/src/hooks/useProgressTracking.js`

```javascript
import { useProgressTracking } from '../hooks/useProgressTracking';

// In your component
const { progress, isPolling, error } = useProgressTracking(queryId);
```

**Features:**
- Auto-starts polling when queryId is provided
- Auto-stops on terminal states (completed, failed, cancelled)
- 1.5 second poll interval (configurable)
- Automatic cleanup on unmount
- Works with authenticated API calls to `/api/v1/refinement/queries/{id}/progress`

**Returns:**
- `progress`: Current progress object (null if not started)
- `isPolling`: Boolean indicating active polling
- `error`: Error message if polling failed

### 2. Progress Indicator Component

Location: `frontend/src/components/ProgressIndicator.jsx`

```jsx
import ProgressIndicator from '../components/ProgressIndicator';

<ProgressIndicator progress={progress} />
<ProgressIndicator progress={progress} compact={true} />
```

**Props:**
- `progress` (object): Progress data from the hook
- `compact` (boolean): Compact mode (bar only, no metadata)

**Displays:**
- Current stage with color-coded status
- Progress bar (0-100%)
- Descriptive message
- LLM call count
- Turn number (if applicable)
- Elapsed time
- Error messages (if failed)

### 3. Integration in Refinement Page

Location: `frontend/src/pages/Refinement.jsx`

```jsx
import { useProgressTracking } from '../hooks/useProgressTracking';
import ProgressIndicator from '../components/ProgressIndicator';

const Refinement = () => {
    const [queryId, setQueryId] = useState(null);
    
    // Hook automatically tracks when queryId changes
    const { progress, isPolling } = useProgressTracking(queryId);
    
    return (
        <div>
            {/* Show progress during long operations */}
            {isPolling && progress && (
                <ProgressIndicator progress={progress} />
            )}
            
            {/* Your existing UI */}
        </div>
    );
};
```

### 4. Progress States

The progress tracker reports these stages:

| Stage                    | Progress % | When                       |
| ------------------------ | ---------- | -------------------------- |
| `created`                | 0%         | Query received             |
| `extracting_aspects`     | 5%         | Analyzing query            |
| `aspects_extracted`      | 10%        | Aspects identified         |
| `generating_suggestions` | 20-40%     | LLM generating suggestions |
| `suggestions_ready`      | 40-50%     | Ready for user input       |
| `waiting_for_user`       | 50%        | Awaiting answer            |
| `user_refining`          | 50-70%     | Processing answer          |
| `synthesizing`           | 80%        | Creating final query       |
| `synthesis_complete`     | 90%        | Synthesis done             |
| `completed`              | 100%       | Workflow complete          |
| `failed`                 | 100%       | Error occurred             |
| `cancelled`              | 100%       | User cancelled             |

Terminal states are: `completed`, `failed`, `cancelled`.

### 5. Example Progress Data

```json
{
  "query_id": "123",
  "stage": "generating_suggestions",
  "progress": 0.35,
  "message": "Generating refinement suggestions (turn 2 of 3)...",
  "started_at": "2026-02-11T10:30:00Z",
  "updated_at": "2026-02-11T10:30:12Z",
  "elapsed_seconds": 12.5,
  "turn_number": 2,
  "total_turns": 3,
  "aspects_count": 5,
  "llm_calls_made": 2,
  "error": null
}
```

## Circuit Breaker Monitoring (Optional)

### Monitoring Service

Location: `frontend/src/services/monitoring.js`

```javascript
import { monitoringService } from '../services/monitoring';

// Get circuit breaker status for all providers
const status = await monitoringService.getCircuitBreakerStatus();

// Get overall LLM health
const health = await monitoringService.getLLMHealth();

// Check specific provider
const isHealthy = await monitoringService.isProviderHealthy('openai');
```

Backend endpoints used:

- `GET /api/v1/monitoring/llm-health`
- `GET /api/v1/monitoring/circuit-breakers`

### Use Cases

**1. Admin Dashboard**
```jsx
const AdminDashboard = () => {
    const [health, setHealth] = useState(null);
    
    useEffect(() => {
        const fetchHealth = async () => {
            const data = await monitoringService.getLLMHealth();
            setHealth(data);
        };
        
        fetchHealth();
        const interval = setInterval(fetchHealth, 30000); // 30s refresh
        
        return () => clearInterval(interval);
    }, []);
    
    return (
        <div>
            <h2>LLM Provider Health</h2>
            {health?.providers && Object.entries(health.providers).map(([name, data]) => (
                <div key={name}>
                    <strong>{name}</strong>: {data.circuit_state}
                    {!data.is_healthy && <span> ⚠️ DEGRADED</span>}
                </div>
            ))}
        </div>
    );
};
```

**2. Error Handling Enhancement** 

```javascript
const handleRefinementError = async (error) => {
    if (error.response?.status === 503) {
        // Check if it's a circuit breaker issue
        const health = await monitoringService.getLLMHealth();
        
        if (health.overall_health === 'degraded') {
            showError(
                'LLM services are experiencing issues. ' +
                'Your request will be retried automatically when service recovers.'
            );
        }
    }
};
```

**3. Preventive User Feedback**
```javascript
// Before starting a refinement
const checkHealthBeforeStart = async () => {
    try {
        const isHealthy = await monitoringService.isProviderHealthy('openai');
        
        if (!isHealthy) {
            showWarning(
                'LLM service is currently experiencing issues. ' +
                'You may experience delays or need to retry your request.'
            );
        }
    } catch (err) {
        // Silently fail - don't block user if monitoring unavailable
    }
};
```

## Best Practices

### Progress Tracking

✅ **DO:**
- Show progress indicator during `startRefinement()` and `getSynthesis()`
- Display progress for operations taking >3 seconds
- Keep progress visible until terminal state reached
- Use compact mode in tight spaces
- Surface graceful error messages for `502/504` when downstream QA forwarding fails
- Keep polling requests authenticated and scoped to current user session

❌ **DON'T:**
- Poll more frequently than 1 second (unnecessary load)
- Show progress for instant operations
- Block UI during progress tracking
- Forget to handle `error` state
- Assume `:8001` is publicly accessible in production VM environments

### Error Handling

```javascript
const { progress, error } = useProgressTracking(queryId);

useEffect(() => {
    if (error) {
        // Handle progress tracking errors gracefully
        console.error('Progress tracking unavailable:', error);
        // Fall back to simple loading spinner
    }
}, [error]);
```

### Accessibility

```jsx
<ProgressIndicator 
    progress={progress}
    aria-label="Refinement progress"
    role="progressbar"
    aria-valuenow={progress?.progress * 100}
    aria-valuemin="0"
    aria-valuemax="100"
/>
```

## Testing

### Test Progress States

```javascript
// Mock progress data for testing
const mockProgress = {
    query_id: "test_123",
    stage: "generating_suggestions",
    progress: 0.4,
    message: "Generating suggestions...",
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    elapsed_seconds: 5.2,
    llm_calls_made: 2
};

<ProgressIndicator progress={mockProgress} />
```

### Test Hook

```javascript
import { renderHook, act } from '@testing-library/react-hooks';
import { useProgressTracking } from '../hooks/useProgressTracking';

test('starts polling when queryId provided', () => {
    const { result } = renderHook(() => useProgressTracking(123));
    
    expect(result.current.isPolling).toBe(true);
});
```

## Performance Considerations

- **Poll Frequency**: Default 1.5s is optimal for user experience vs server load
- **Memory**: Hook cleans up intervals on unmount  
- **Network**: Minimal overhead (~500 bytes per poll)
- **Battery**: Polling stops automatically on completion

## Microservice VM Operational Notes

- Prefer relative API paths (`/api/v1/...`) so frontend works behind reverse proxy and TLS termination
- If you run synthetic monitoring from the browser tier, monitor:
    - `/health` for liveness
    - `/api/v1/monitoring/llm-health` for model-provider status
- Keep frontend retry logic bounded for long operations:
    - retry transient network errors and `5xx` failures with backoff
    - avoid retry loops on `4xx` authorization/validation failures

## Migration Checklist

- [ ] Install `useProgressTracking` hook
- [ ] Add `ProgressIndicator` component
- [ ] Import monitoring service (if using circuit breaker features)
- [ ] Update `Refinement.jsx` with progress tracking
- [ ] Add progress UI to long-running operations
- [ ] Test progress states (loading, completed, failed)
- [ ] Add error handling for progress fetch failures
- [ ] (Optional) Add admin dashboard for circuit breaker monitoring
- [ ] Update user documentation with new loading experience

## Additional Resources

- Backend API: `/api/v1/refinement/queries/{id}/progress`
- Circuit Breaker: `/api/v1/monitoring/circuit-breakers`
- LLM Health: `/api/v1/monitoring/llm-health`
- Full docs: `docs/PROGRESS_TRACKING.md`
- Circuit breaker docs: `docs/CIRCUIT_BREAKER.md`
