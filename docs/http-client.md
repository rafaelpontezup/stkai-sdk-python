# HTTP Client

The SDK uses a unified `HttpClient` abstraction for all HTTP communication. This allows you to customize authentication, rate limiting, and testing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Your Application                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   RemoteQuickCommand ─────┐                                         │
│                           ├──► HttpClient ──► StackSpot AI API     │
│   Agent ──────────────────┘                                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Built-in Implementations

### EnvironmentAwareHttpClient (Default)

Automatically detects the runtime environment and uses the appropriate client:

1. **CLI available** → Uses `StkCLIHttpClient`
2. **Credentials configured** → Uses `StandaloneHttpClient`
3. **Neither** → Raises `ValueError` with clear instructions

```python
from stkai import RemoteQuickCommand

# Works automatically in any environment
rqc = RemoteQuickCommand(slug_name="my-command")
```

The detection happens lazily on the first request, allowing you to call `STKAI.configure()` after import.

!!! tip "Zero Configuration"
    With `EnvironmentAwareHttpClient`, you don't need to worry about which client to use:

    - **Development**: Install CLI and run `stk login`
    - **Production/CI**: Set `STKAI_AUTH_CLIENT_ID` and `STKAI_AUTH_CLIENT_SECRET`

### StkCLIHttpClient

Explicitly delegates authentication to the StackSpot CLI (`oscli`):

```python
from stkai import RemoteQuickCommand, StkCLIHttpClient

# Explicit CLI usage
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=StkCLIHttpClient(),
)
```

!!! note "Requirements"
    StackSpot CLI must be installed and authenticated:
    ```bash
    stk login
    ```

### StandaloneHttpClient

Explicitly uses client credentials for environments without StackSpot CLI:

```python
from stkai import (
    RemoteQuickCommand,
    StandaloneHttpClient,
    ClientCredentialsAuthProvider,
)

# Create auth provider
auth_provider = ClientCredentialsAuthProvider(
    client_id="your-client-id",
    client_secret="your-client-secret",
)

# Create HTTP client
http_client = StandaloneHttpClient(auth_provider=auth_provider)

# Use with RQC
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
)
```

Or use the global configuration:

```python
from stkai import STKAI, create_standalone_auth, StandaloneHttpClient

# Configure credentials globally
STKAI.configure(
    auth={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
    }
)

# Create client using global config
auth_provider = create_standalone_auth()
http_client = StandaloneHttpClient(auth_provider=auth_provider)
```

### TokenBucketRateLimitedHttpClient

Wraps another client with Token Bucket rate limiting:

```python
from stkai import TokenBucketRateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = TokenBucketRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,      # Requests per window
    time_window=60.0,     # Window in seconds
)
```

### AdaptiveRateLimitedHttpClient

Adds adaptive rate control with AIMD algorithm:

```python
from stkai import AdaptiveRateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = AdaptiveRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,      # Never below 10%
    penalty_factor=0.2,      # Reduce by 20% on 429
    recovery_factor=0.05,    # Increase by 5% on success
)
```

!!! note "429 Handling"
    When the server returns HTTP 429, `AdaptiveRateLimitedHttpClient` applies the AIMD penalty (reduces rate) and raises `ServerSideRateLimitError`. The actual retry logic is handled by the `Retrying` class, which respects the `Retry-After` header.

## Rate Limiting

### Why Rate Limiting Matters for StackSpot AI

Agents and Remote Quick Commands (RQCs) make calls to LLM models that have **shared quotas** and **costs per request**. Without proper rate control:

- **HTTP 429 errors** flood your logs and waste retry cycles
- **Service degradation** affects other teams sharing the same quota
- **Unexpected costs** from runaway batch jobs
- **Thundering herd** when multiple processes start simultaneously

Rate limiting is especially important for:

| Scenario | Risk Without Rate Limiting |
|----------|---------------------------|
| Batch processing (e.g., processing 1000 files) | Burst of requests exhausts quota in seconds |
| Multiple CI/CD pipelines | Pipelines compete for shared quota |
| Microservices with multiple replicas | Each replica thinks it has full quota |
| Development + Production sharing quota | Dev experiments impact production |

### Strategies: Token Bucket vs Adaptive

The SDK offers two rate limiting strategies, each suited for different scenarios.

#### Token Bucket Strategy

**When to use:**

- You have a **fixed, known quota** (e.g., "100 requests/minute")
- Your process runs **alone** or has a **dedicated quota allocation**
- You want **predictable, simple** rate limiting

**How it works:**

```
┌──────────────────────────────────────────────────────────────────┐
│                      Token Bucket Algorithm                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   Bucket: [●●●●●○○○○○]  (5 tokens available, 5 used)             │
│                                                                   │
│   • Tokens refill over time at: max_requests / time_window       │
│   • Each POST request consumes 1 token                           │
│   • When empty, requests wait until tokens available             │
│   • If waiting exceeds max_wait_time → TokenAcquisitionTimeoutError     │
│   • GET requests (polling) pass through without consuming tokens │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**Points of attention:**

- Does **not react to HTTP 429** from the server — it only controls outgoing rate
- If your quota is shared with other processes, you may still get 429s
- Best combined with retry logic (which the SDK provides automatically)

#### Adaptive Strategy (AIMD)

**When to use:**

- **Multiple processes** share the same quota
- Your **quota is unpredictable** or varies over time
- You want the SDK to **automatically adjust** based on server feedback

**How it works:**

```
┌──────────────────────────────────────────────────────────────────┐
│                         AIMD Algorithm                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   On SUCCESS:                                                     │
│     effective_rate += max_requests × recovery_factor × jitter    │
│     (gradual increase, jittered ±20%)                            │
│                                                                   │
│   On HTTP 429:                                                    │
│     effective_rate *= (1 - penalty_factor × jitter)              │
│     (aggressive decrease, jittered ±20%)                         │
│     raise ServerSideRateLimitError → Retrying handles retry       │
│                                                                   │
│   On TOKEN WAIT:                                                  │
│     sleep(wait_time × jitter)                                     │
│     (sleep jitter ±20% to spread workers)                        │
│                                                                   │
│   Constraints:                                                    │
│     • Floor: effective_rate ≥ max_requests × min_rate_floor      │
│     • Ceiling: effective_rate ≤ max_requests                     │
│                                                                   │
│   Anti-Thundering Herd:                                           │
│     • Structural jitter: penalty/recovery vary ±20% per process  │
│     • Sleep jitter: token wait varies ±20%                       │
│     • Deterministic RNG per process (hostname+pid seed)          │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**Points of attention:**

- **Convergence time**: After a 429, it takes several successful requests to recover full rate
- **Cold start**: Starts at `max_requests` and decreases on first 429 — may cause initial burst
- `recovery_factor` too low = slow recovery after 429 spike
- `penalty_factor` too low = doesn't back off enough, keeps hitting 429s

**429 Handling:** When the server returns HTTP 429 (Too Many Requests), the `AdaptiveRateLimitedHttpClient`:

1. **Applies AIMD penalty** - Reduces effective rate by `penalty_factor`
2. **Raises `ServerSideRateLimitError`** - Contains the response for `Retry-After` parsing

The `Retrying` class then handles the retry:

1. **Parses `Retry-After` header** - If present and ≤ 60s, uses it as wait time
2. **Calculates wait time** - Uses max(Retry-After, exponential backoff)
3. **Adds jitter (0-30%)** - Prevents thundering herd
4. **Retries the request** - Up to `max_retries` times

!!! note "Protection against abusive Retry-After"
    The `Retrying` class ignores `Retry-After` values greater than 60 seconds to protect against buggy or malicious servers. In such cases, it falls back to exponential backoff.

#### Strategy Comparison

| Scenario | Recommended Strategy | Why |
|----------|---------------------|-----|
| Single process, known quota | `token_bucket` | Simple, predictable, no overhead |
| Multiple processes sharing quota | `adaptive` | Automatically adjusts based on 429s + jitter prevents sync |
| API returns 429 frequently | `adaptive` | Learns from server feedback |
| Stable workload, dedicated quota | `token_bucket` | No need for dynamic adjustment |
| CI/CD with variable load | `adaptive` | Handles concurrent pipeline runs with jitter desync |
| RQC with many processes (5+), shared quota | `congestion_controlled` | Preventive backpressure + concurrency control |

#### Congestion Controlled Strategy (EXPERIMENTAL)

!!! warning "Experimental Feature"
    This strategy is **experimental** and only available via programmatic configuration. It is **not** exposed through `STKAI.configure()` or environment variables. Use it when you understand the trade-offs and have validated it for your use case.

**When to use:**

- **Multiple processes** on different machines sharing the same API quota
- **RemoteQuickCommand** workflows (fast POST + long polling)
- You need **preventive backpressure** based on latency, not just reactive 429 handling
- You want to avoid **thundering herd** effects across processes

**When NOT to use:**

- **Agent::chat()** or any LLM-direct requests with inherently high latency
- Single process scenarios (use `token_bucket` or `adaptive` instead)
- When you need predictable, simple behavior

##### Mental Model

Unlike simple rate limiters, `CongestionControlledHttpClient` is a **congestion controller** inspired by TCP and AWS SDK. It uses three control dimensions:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Congestion Controller                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. RATE (Token Bucket + AIMD)                                             │
│      ─────────────────────────                                              │
│      Controls average request rate. Adapts via AIMD:                        │
│      • Success → rate increases gradually (additive)                        │
│      • HTTP 429 → rate decreases aggressively (multiplicative)              │
│                                                                              │
│   2. CONCURRENCY (Adaptive Semaphore)                                       │
│      ────────────────────────────────                                       │
│      Limits in-flight requests. Key insight:                                │
│                                                                              │
│          pressure = rate × latency                                          │
│                                                                              │
│      High latency → reduce concurrency BEFORE getting 429s                  │
│      (preventive backpressure)                                              │
│                                                                              │
│   3. LATENCY (EMA Tracking)                                                 │
│      ──────────────────────                                                 │
│      Tracks system pressure via Exponential Moving Average.                 │
│      Filters noise, detects sustained trends.                               │
│                                                                              │
│   + STRUCTURAL JITTER (Anti-Thundering Herd)                                │
│     ────────────────────────────────────────                                │
│     Each process has deterministic RNG (hostname+pid seed).                 │
│     Recovery/penalty factors vary ±20% across processes.                    │
│     Prevents synchronized oscillations.                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### Why It Works for RemoteQuickCommand

The RQC workflow has two phases:

```
[POST create-execution] ──► [GET poll] ──► [GET poll] ──► [GET poll] ──► Result
      ~200ms                   ~5s          ~5s           ~5s
         ↑
    Rate Limited              NOT Rate Limited
    (fast, releases          (polling is free)
     semaphore quickly)
```

- **POST is fast**: Semaphore is held briefly (~200ms), then released
- **Polling is free**: GET requests bypass rate limiting entirely
- **Latency is meaningful**: Slow POST = server congestion signal
- **Jitter prevents sync**: Multiple processes don't oscillate together

##### Why It Does NOT Work for Agent::chat()

```
[POST chat] ════════════════════════════════════════════════════════► Result
                           10-30 seconds (LLM processing)
                                    ↑
                           Semaphore held THE ENTIRE TIME!
```

- **POST is slow**: Semaphore held for 10-30s (LLM processing time)
- **High latency is NORMAL**: Not a congestion signal, just how LLMs work
- **Concurrency limit = bottleneck**: With `max_concurrency=5`, only 5 chats can run at once

**Impact example** (8 workers, each chat ~15s):

| Configuration | Total Time (8 chats) | Degradation |
|---------------|---------------------|-------------|
| No rate limit | ~18s | - |
| CongestionControlled (max_concurrency=5) | ~32s | +78% slower |

##### Programmatic Configuration

!!! warning "Disable Global Rate Limiting"
    When using `CongestionControlledHttpClient`, you must **not** enable rate limiting via `STKAI.configure()`. The congestion controller has its own built-in rate limiting. Using both would result in double rate limiting and unexpected behavior.

```python
from stkai import STKAI, RemoteQuickCommand, EnvironmentAwareHttpClient
from stkai._rate_limit import CongestionControlledHttpClient

# IMPORTANT: Ensure global rate limiting is disabled
STKAI.configure(
    rate_limit={"enabled": False}  # Congestion controller handles rate limiting
)

# Create the congestion-controlled client manually
http_client = CongestionControlledHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=100,           # Token bucket capacity
    time_window=60.0,           # Window in seconds
    min_rate_floor=0.1,         # Never below 10% of max
    penalty_factor=0.3,         # Reduce by 30% on 429
    recovery_factor=0.05,       # Increase by 5% on success
    max_wait_time=30.0,         # Timeout waiting for token
    max_concurrency=5,          # Max in-flight requests
    latency_alpha=0.2,          # EMA smoothing factor
)

# Use with RQC
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
)

# Works well with execute_many()
results = rqc.execute_many(requests)  # 8 workers default
```

##### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_requests` | `int` | - | Token bucket capacity (requests per window) |
| `time_window` | `float` | - | Time window in seconds |
| `min_rate_floor` | `float` | `0.1` | Minimum rate as fraction of max (10%) |
| `penalty_factor` | `float` | `0.3` | Rate reduction on 429 (×0.7) |
| `recovery_factor` | `float` | `0.05` | Rate increase on success (+5%) |
| `max_wait_time` | `float\|None` | `30.0` | Max wait for token (None = unlimited) |
| `max_concurrency` | `int` | `5` | Max concurrent in-flight requests |
| `latency_alpha` | `float` | `0.2` | EMA smoothing (0.1=stable, 0.5=reactive) |

##### Tuning for Your Environment

**Conservative (many processes, tight quota):**

```python
CongestionControlledHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,            # Lower capacity
    time_window=60.0,
    min_rate_floor=0.2,         # Higher floor (20%)
    penalty_factor=0.4,         # More aggressive penalty
    recovery_factor=0.03,       # Slower recovery
    max_wait_time=60.0,         # Patient
    max_concurrency=3,          # Very conservative
)
```

**Optimistic (few processes, generous quota):**

```python
CongestionControlledHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,
    penalty_factor=0.2,         # Lighter penalty
    recovery_factor=0.1,        # Faster recovery
    max_wait_time=30.0,
    max_concurrency=10,         # More aggressive
)
```

##### Decision Matrix

| Scenario | Strategy | Why |
|----------|----------|-----|
| RQC, 1 process | `token_bucket` or `adaptive` | Simpler, no concurrency control needed |
| RQC, N processes, shared quota | `congestion_controlled` | Jitter + preventive backpressure |
| Agent::chat(), any scenario | `adaptive` | High latency is normal for LLMs |
| Debugging/development | `token_bucket` | Predictable behavior |
| Production RQC with strict quota | `congestion_controlled` | Maximum stability |

##### FAQ

**Q: Why does CongestionControlledHttpClient use a semaphore if Token Bucket already limits rate?**

Token Bucket limits **average rate** (requests per time window), but doesn't limit **concurrent requests**. Imagine 8 workers sending requests simultaneously: Token Bucket allows all 8 to fire at once, then waits. The semaphore (`max_concurrency`) limits **in-flight requests**, spreading them over time. This prevents burst spikes that overwhelm the server.

**Q: What is the relationship between `max_workers` in RQC and `max_concurrency`?**

They are independent. `max_workers` (default 8) defines how many threads can execute RQC requests in parallel. `max_concurrency` (default 5) limits how many POST requests can be in-flight simultaneously. If `max_workers > max_concurrency`, some workers will wait for the semaphore. For RQC this is fine because POST is fast (~200ms) and most time is spent polling (which is not rate limited).

**Q: Why is `latency_alpha` important?**

`latency_alpha` controls EMA (Exponential Moving Average) smoothing. It determines how the controller reacts to latency changes:
- **Low alpha (0.1)**: Stable, ignores noise, slow to detect real changes
- **High alpha (0.5)**: Reactive, detects changes fast, but noisy

Think of it as a noise filter. Lower = more filtering.

**Q: Why doesn't CongestionControlled work well for Agent::chat()?**

The congestion controller was designed for workflows where POST is **fast** (just scheduling work) and results come via polling. In `Agent::chat()`, the POST **is** the LLM call - it takes 10-30 seconds. The semaphore is held the entire time, becoming a bottleneck. Additionally, high latency is **normal** for LLMs, not a congestion signal.

**Q: What is "structural jitter" and why does it matter?**

When multiple processes share a quota and use identical AIMD parameters, they tend to synchronize: all reduce rate on 429, all recover at the same rate, all hit the ceiling together, repeat. Structural jitter adds variation to `penalty_factor` and `recovery_factor` per process (using a deterministic seed based on hostname+pid). This desynchronizes processes, preventing thundering herd effects.

Both `adaptive` and `congestion_controlled` strategies include structural jitter (±20%). The `adaptive` strategy also adds sleep jitter (±20%) when waiting for tokens.

**Q: How do I choose between `adaptive` and `congestion_controlled`?**

| Criterion | Use `adaptive` | Use `congestion_controlled` |
|-----------|---------------|----------------------------|
| Number of processes | 1-4 | 5+ |
| Need preventive backpressure | No | Yes |
| Latency is meaningful signal | No | Yes (RQC) |
| Workflow | Agent::chat() or simple | RQC execute_many() |
| Complexity tolerance | Low | Higher |

**Q: Can I use CongestionControlled with STKAI.configure()?**

No. This strategy is **experimental** and only available via programmatic configuration. You must create the `CongestionControlledHttpClient` manually and pass it to `RemoteQuickCommand`. Make sure to disable global rate limiting (`rate_limit={"enabled": False}`) to avoid double rate limiting.

### Presets (Adaptive Strategy)

Presets provide pre-tuned configurations for the `adaptive` strategy. Instead of manually tuning `penalty_factor`, `recovery_factor`, etc., choose a preset that matches your use case:

```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig

# Conservative: stability over throughput
STKAI.configure(rate_limit=asdict(RateLimitConfig.conservative_preset(max_requests=20)))

# Balanced: sensible middle-ground (recommended for most cases)
STKAI.configure(rate_limit=asdict(RateLimitConfig.balanced_preset(max_requests=50)))

# Optimistic: throughput over stability
STKAI.configure(rate_limit=asdict(RateLimitConfig.optimistic_preset(max_requests=80)))
```

#### Preset Comparison

| Preset | `max_wait_time` | `min_rate_floor` | `penalty_factor` | `recovery_factor` |
|--------|-----------------|------------------|------------------|-------------------|
| `conservative_preset()` | 120s (patient) | 0.05 (5%) | 0.5 (aggressive) | 0.02 (slow) |
| `balanced_preset()` | 30s | 0.1 (10%) | 0.3 (moderate) | 0.05 (medium) |
| `optimistic_preset()` | 5s (fail-fast) | 0.3 (30%) | 0.15 (light) | 0.1 (fast) |

#### When to Use Each Preset

**Conservative** — Stability over throughput

- Critical batch jobs that **cannot fail**
- Many concurrent processes (5+) sharing quota
- Jobs that run overnight and can afford to be slow
- When 429 errors have significant business impact

**Balanced** — Sensible default

- General batch processing
- 2-3 concurrent processes sharing quota
- When you want reasonable throughput with good stability
- **Recommended starting point** for most applications

**Optimistic** — Throughput over stability

- Interactive CLI tools that need fast feedback
- Single process with dedicated quota
- When you have external retry logic or can tolerate failures
- Short-lived scripts where waiting is unacceptable

#### Calculating max_requests

Presets accept `max_requests` and `time_window` as parameters. Calculate based on your environment:

```
max_requests = (API quota) / (number of concurrent processes)
```

**Example:** Your team has a quota of 100 req/min. You run 3 batch jobs concurrently:

```python
# Each process gets ~33 req/min
STKAI.configure(rate_limit=asdict(
    RateLimitConfig.balanced_preset(max_requests=33)
))
```

!!! warning "Be conservative with the division"
    It's better to underestimate than overestimate. If unsure, divide by a higher number. You can always increase later.

### Practical Scenarios

#### Scenario 1: CI/CD Pipeline (Single Process)

A GitHub Actions job that processes code files. Runs alone, predictable workload.

```python
from stkai import STKAI

# Simple token bucket - we know we're the only consumer
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 60,      # Our full quota
        "time_window": 60.0,
        "max_wait_time": 120.0,  # Patient - job can wait
    }
)
```

#### Scenario 2: Multiple Batch Jobs Sharing Quota

Three Python processes running simultaneously, each processing different data. They share a 100 req/min quota.

```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig

# Adaptive with conservative settings - let processes coordinate via 429s
STKAI.configure(rate_limit=asdict(
    RateLimitConfig.conservative_preset(
        max_requests=30,  # 100 / 3 ≈ 33, round down for safety
    )
))
```

#### Scenario 3: Interactive CLI Tool

A developer tool that needs fast feedback. User is waiting for response.

```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig

# Optimistic - fail fast, let user retry manually
STKAI.configure(rate_limit=asdict(
    RateLimitConfig.optimistic_preset(
        max_requests=50,
    )
))
```

#### Scenario 4: Batch Processing with execute_many()

Processing 500 files using `execute_many()` with 8 workers. Note that all workers share the same rate limiter.

```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig, RemoteQuickCommand

STKAI.configure(rate_limit=asdict(
    RateLimitConfig.balanced_preset(max_requests=40)
))

rqc = RemoteQuickCommand(
    slug_name="analyze-code",
    max_workers=8,  # 8 threads, but all share the same rate limiter
)

# The rate limiter ensures we don't exceed 40 req/min
# regardless of how many workers are active
responses = rqc.execute_many(requests)
```

### Important Considerations

#### Rate Limiting Only Applies to POST Requests

The SDK only rate-limits POST requests (which create executions). GET requests (used for polling) are **not** rate-limited:

```
POST /executions → Rate limited (consumes token)
GET /executions/{id} → NOT rate limited (polling is free)
```

This means your effective quota consumption depends on how many **new executions** you create, not on polling frequency.

#### Multiple Processes = Divide the Quota

Rate limiting is **per-process**. If you have 3 processes, each needs its own allocation:

```python
# WRONG: Each process thinks it has full quota
STKAI.configure(rate_limit={"max_requests": 100})  # All 3 processes do this!

# RIGHT: Divide quota among processes
STKAI.configure(rate_limit={"max_requests": 33})   # 100 / 3
```

#### max_wait_time Can Block Your Application

If `max_wait_time` is too high, threads may block for a long time waiting for tokens:

```python
# This can block a thread for up to 5 minutes!
STKAI.configure(rate_limit={"max_wait_time": 300})

# Better: fail faster and let retry logic handle it
STKAI.configure(rate_limit={"max_wait_time": 30})
```

#### Rate Limiter is Per-Instance

Each `RemoteQuickCommand` or `Agent` instance has its own rate limiter (via its `HttpClient`). They don't share state by default:

```python
# These have SEPARATE rate limiters - combined they may exceed quota!
rqc1 = RemoteQuickCommand(slug_name="command-1")
rqc2 = RemoteQuickCommand(slug_name="command-2")
agent = Agent(agent_id="my-agent")
```

**To share a rate limiter**, pass the same `HttpClient` instance:

```python
from stkai import RemoteQuickCommand, Agent, EnvironmentAwareHttpClient

# Create a single HTTP client (rate limiter included via STKAI.configure)
shared_client = EnvironmentAwareHttpClient()

# All instances share the same rate limiter
rqc1 = RemoteQuickCommand(slug_name="command-1", http_client=shared_client)
rqc2 = RemoteQuickCommand(slug_name="command-2", http_client=shared_client)
agent = Agent(agent_id="my-agent", http_client=shared_client)
```

### Global Configuration (Recommended)

The easiest way to enable rate limiting is via `STKAI.configure()`. When enabled, `EnvironmentAwareHttpClient` automatically wraps requests with rate limiting:

```python
from stkai import STKAI, RemoteQuickCommand, Agent

# Enable rate limiting globally
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
    }
)

# All clients now use rate limiting automatically
rqc = RemoteQuickCommand(slug_name="my-command")
agent = Agent(agent_id="my-agent")
```

### Configuration via Code

```python
from stkai import STKAI

# Token Bucket (simple, predictable)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
        "max_wait_time": 60.0,  # Timeout after 60s waiting
    }
)

# Adaptive (dynamic, handles 429)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "adaptive",
        "max_requests": 100,
        "time_window": 60.0,
        "min_rate_floor": 0.1,       # Never below 10%
        "penalty_factor": 0.2,       # Reduce by 20% on 429
        "recovery_factor": 0.05,     # Increase by 5% on success
    }
)

# Unlimited wait time (wait indefinitely for token)
STKAI.configure(rate_limit={"max_wait_time": None})  # or "unlimited"
```

### Configuration via Environment Variables

```bash
STKAI_RATE_LIMIT_ENABLED=true
STKAI_RATE_LIMIT_STRATEGY=adaptive
STKAI_RATE_LIMIT_MAX_REQUESTS=50
STKAI_RATE_LIMIT_TIME_WINDOW=60.0
STKAI_RATE_LIMIT_MAX_WAIT_TIME=unlimited  # or "none", "null"
STKAI_RATE_LIMIT_MIN_RATE_FLOOR=0.1
STKAI_RATE_LIMIT_PENALTY_FACTOR=0.2
STKAI_RATE_LIMIT_RECOVERY_FACTOR=0.05
```

### RateLimitConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable rate limiting |
| `strategy` | `"token_bucket"` \| `"adaptive"` | `"token_bucket"` | Rate limiting algorithm |
| `max_requests` | `int` | `100` | Max requests per time window |
| `time_window` | `float` | `60.0` | Time window in seconds |
| `max_wait_time` | `float \| None` | `30.0` | Max wait for token (None = unlimited) |
| `min_rate_floor` | `float` | `0.1` | (adaptive) Min rate as fraction of max |
| `penalty_factor` | `float` | `0.3` | (adaptive) Rate reduction on 429 |
| `recovery_factor` | `float` | `0.05` | (adaptive) Rate increase on success |

### Manual Configuration

For more control, you can manually create rate-limited clients:

```python
from stkai import TokenBucketRateLimitedHttpClient, EnvironmentAwareHttpClient, RemoteQuickCommand

# Create rate-limited client manually
http_client = TokenBucketRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,
    time_window=60.0,
)

# Use with specific client
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
)
```

### Exception Hierarchy

The SDK provides a clear exception hierarchy for rate limiting errors:

```
RetryableError (base - automatically retried)
├── ClientSideRateLimitError      # Base for client-side rate limit errors
│   └── TokenAcquisitionTimeoutError     # Timeout waiting for token (max_wait_time exceeded)
└── ServerSideRateLimitError      # HTTP 429 from server (contains response for Retry-After)
```

| Exception | Raised By | When |
|-----------|-----------|------|
| `TokenAcquisitionTimeoutError` | `TokenBucketRateLimitedHttpClient`, `AdaptiveRateLimitedHttpClient` | Token wait exceeds `max_wait_time` |
| `ServerSideRateLimitError` | `AdaptiveRateLimitedHttpClient` | Server returns HTTP 429 |
| `requests.HTTPError` | Direct from `requests` | HTTP 429 without Adaptive strategy |

All exceptions inherit from `RetryableError`, which the `Retrying` class automatically retries with exponential backoff.

### Timeout Handling

Both strategies raise `TokenAcquisitionTimeoutError` when a thread waits too long for a token:

```python
from stkai import TokenBucketRateLimitedHttpClient, TokenAcquisitionTimeoutError, StkCLIHttpClient

http_client = TokenBucketRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=10,
    time_window=60.0,
    max_wait_time=30.0,  # Give up after 30 seconds
)

try:
    response = http_client.post(url, data=payload)
except TokenAcquisitionTimeoutError as e:
    print(f"Timeout after {e.waited:.1f}s (max: {e.max_wait_time}s)")
    # Handle timeout: retry later, skip request, or fail gracefully
```

| Value | Behavior |
|-------|----------|
| `60.0` (default) | Wait up to 60 seconds for a token |
| `None` or `"unlimited"` | Wait indefinitely (no timeout) |
| `0.1` | Fail-fast mode (almost immediate timeout) |

!!! tip "Choosing max_wait_time"
    A good rule of thumb is to set `max_wait_time` equal to `time_window`. This ensures at least one full rate limit cycle can complete before timing out.

### Thread Safety

Both rate-limiting strategies are **thread-safe** and work correctly with:

- `execute_many()` concurrent workers
- Multi-threaded applications
- Shared client instances

```python
from stkai import STKAI, RemoteQuickCommand

STKAI.configure(
    rate_limit={"enabled": True, "max_requests": 30}
)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    max_workers=16,  # 16 concurrent workers, still rate-limited
)
```

## Custom HTTP Client

Implement the `HttpClient` interface for custom behavior:

```python
from typing import Any
import requests
from stkai import HttpClient

class MyCustomHttpClient(HttpClient):
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        # Custom GET logic
        return requests.get(url, headers=headers, timeout=timeout)

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        # Custom POST logic
        return requests.post(url, json=data, headers=headers, timeout=timeout)

# Use custom client
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=MyCustomHttpClient(),
)
```

## Decorator Pattern

Rate limiting clients use the decorator pattern - they wrap another client:

```python
from stkai import (
    AdaptiveRateLimitedHttpClient,
    TokenBucketRateLimitedHttpClient,
    StandaloneHttpClient,
    ClientCredentialsAuthProvider,
)

# Build a decorated chain
auth_provider = ClientCredentialsAuthProvider(
    client_id="id",
    client_secret="secret",
)

# Base client with authentication
base_client = StandaloneHttpClient(auth_provider=auth_provider)

# Add fixed rate limiting
rate_limited = TokenBucketRateLimitedHttpClient(
    delegate=base_client,
    max_requests=50,
    time_window=60.0,
)

# Add adaptive rate limiting on top
adaptive_client = AdaptiveRateLimitedHttpClient(
    delegate=rate_limited,  # Wrap the rate-limited client
    max_requests=100,
    time_window=60.0,
)
```

## Testing with Mock Client

Create a mock client for testing:

```python
from unittest.mock import Mock, MagicMock
import requests
from stkai import HttpClient, RemoteQuickCommand

# Create mock
mock_client = Mock(spec=HttpClient)

# Configure POST response
mock_response = MagicMock(spec=requests.Response)
mock_response.status_code = 200
mock_response.json.return_value = {"execution_id": "exec-123"}
mock_response.raise_for_status.return_value = None
mock_client.post.return_value = mock_response

# Configure GET response
get_response = MagicMock(spec=requests.Response)
get_response.status_code = 200
get_response.json.return_value = {
    "progress": {"status": "COMPLETED"},
    "result": {"data": "test"},
}
get_response.raise_for_status.return_value = None
mock_client.get.return_value = get_response

# Use in tests
rqc = RemoteQuickCommand(
    slug_name="test-command",
    http_client=mock_client,
)
```

## Thread Safety

All built-in HTTP clients are thread-safe:

- `EnvironmentAwareHttpClient` - Delegates to thread-safe clients
- `StkCLIHttpClient` - Stateless, safe
- `StandaloneHttpClient` - Auth provider handles token caching
- `TokenBucketRateLimitedHttpClient` - Uses `threading.Lock()`
- `AdaptiveRateLimitedHttpClient` - Uses `threading.Lock()`

Safe to share across threads and with `execute_many()`:

```python
# Thread-safe: shared client with concurrent workers
http_client = TokenBucketRateLimitedHttpClient(...)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
    max_workers=16,  # 16 concurrent threads
)

responses = rqc.execute_many(requests)
```

## Next Steps

- [RQC Rate Limiting](rqc/rate-limiting.md) - Detailed rate limiting examples for RQC
- [Configuration](configuration.md) - Global SDK configuration
- [Getting Started](getting-started.md) - Quick setup guide
