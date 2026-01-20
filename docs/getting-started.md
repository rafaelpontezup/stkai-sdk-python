# Getting Started

This guide will help you install and configure the StackSpot AI SDK for Python.

## Installation

Install the SDK using pip:

```bash
pip install stkai
```

For development (includes testing and linting tools):

```bash
pip install stkai[dev]
```

## Requirements

- **Python 3.12+**
- One of the following authentication methods:
    - **StackSpot CLI** (`oscli`) installed and authenticated (recommended)
    - **Client Credentials** for standalone authentication

## Authentication

The SDK supports two authentication modes:

### Option 1: StackSpot CLI (Recommended)

If you have the [StackSpot CLI](https://docs.stackspot.com/docs/stk-cli/installation/) installed and authenticated, the SDK will automatically use it for authentication:

```bash
# Install StackSpot CLI
curl -fsSL https://stk.stackspot.com/install.sh | bash

# Authenticate
stk login
```

Then simply use the SDK:

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="my-quick-command")
response = rqc.execute(RqcRequest(payload={"input": "data"}))
```

### Option 2: Standalone Authentication

For environments without StackSpot CLI (CI/CD, serverless, containers), use client credentials:

```python
from stkai import STKAI, RemoteQuickCommand, RqcRequest

# Configure authentication
STKAI.configure(
    auth={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
    }
)

# Use the SDK
rqc = RemoteQuickCommand(slug_name="my-quick-command")
response = rqc.execute(RqcRequest(payload={"input": "data"}))
```

Or via environment variables:

```bash
export STKAI_AUTH_CLIENT_ID="your-client-id"
export STKAI_AUTH_CLIENT_SECRET="your-client-secret"
```

## Quick Start Examples

### Remote Quick Commands

Execute an AI-powered Quick Command:

```python
from stkai import RemoteQuickCommand, RqcRequest

# Create a client
rqc = RemoteQuickCommand(slug_name="analyze-code")

# Execute a single request
response = rqc.execute(
    request=RqcRequest(
        payload={"code": "def hello(): print('world')"},
        id="my-request-id",  # Optional: auto-generated if not provided
    )
)

# Check the result
if response.is_completed():
    print(f"Analysis: {response.result}")
else:
    print(f"Error: {response.error_with_details()}")
```

### AI Agents

Chat with an AI Agent:

```python
from stkai import Agent, ChatRequest

# Create an Agent client
agent = Agent(agent_id="my-assistant")

# Send a message
response = agent.chat(
    request=ChatRequest(user_prompt="Explain dependency injection")
)

# Check the response
if response.is_success():
    print(f"Agent: {response.raw_result}")
    if response.tokens:
        print(f"Tokens used: {response.tokens.total}")
else:
    print(f"Error: {response.error}")
```

## Batch Processing

Process multiple requests concurrently:

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="analyze-code")

# Prepare multiple requests
files = [
    {"name": "main.py", "code": "..."},
    {"name": "utils.py", "code": "..."},
    {"name": "models.py", "code": "..."},
]

requests = [
    RqcRequest(payload=f, id=f["name"])
    for f in files
]

# Execute all concurrently
responses = rqc.execute_many(requests)

# Process results
for resp in responses:
    if resp.is_completed():
        print(f"{resp.request.id}: {resp.result}")
```

## Next Steps

- [Remote Quick Commands](rqc/index.md) - Deep dive into RQC features
- [Agents](agents/index.md) - Learn about AI Agents
- [Configuration](configuration.md) - Advanced configuration options
- [Rate Limiting](rqc/rate-limiting.md) - Handle API rate limits
