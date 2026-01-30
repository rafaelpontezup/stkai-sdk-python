# stkai

[![PyPI](https://img.shields.io/pypi/v/stkai.svg)](https://pypi.org/project/stkai/)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Python SDK for [StackSpot AI](https://ai.stackspot.com/) - Execute Remote Quick Commands (RQCs) and interact with AI Agents.

## Design Principles

This SDK prioritizes:

- **Reliability over latency** — Built-in retries, rate limiting, and fault tolerance mechanisms
- **Predictability over throughput** — Synchronous, blocking API for straightforward debugging and reasoning
- **Pragmatism over flexibility** — Simple, direct API with well-designed extension points
- **Convention over configuration** — Sensible defaults and seamless StackSpot CLI integration

## Installation

Install from [PyPI](https://pypi.org/project/stkai/):

```bash
pip install stkai
```

## Requirements

- Python 3.12+
- [StackSpot CLI](https://docs.stackspot.com/docs/stk-cli/installation/) installed and authenticated, or client credentials for standalone auth

## Quick Start

### Remote Quick Commands

Execute LLM-powered quick commands with automatic polling and retries:

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="my-quick-command")
response = rqc.execute(
    request=RqcRequest(payload={"code": "def hello(): pass"})
)

if response.is_completed():
    print(response.result)
else:
    print(response.error_with_details())
```

### AI Agents

Chat with StackSpot AI Agents for conversational AI capabilities:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-agent-slug")
response = agent.chat(
    request=ChatRequest(user_prompt="What is SOLID?")
)

if response.is_success():
    print(response.result)
else:
    print(response.error_with_details())
```

### Remote Quick Commands | Batch Processing

Process multiple requests concurrently with thread pool execution:

```python
responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in files]
)

completed = [r for r in responses if r.is_completed()]
```

## Features

| Feature | Description | Docs |
|---------|-------------|------|
| **Remote Quick Commands** | Execute AI commands with polling and retries | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/) |
| **AI Agents** | Chat with agents, conversations, knowledge sources | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/agents/) |
| **Batch Execution** | Process multiple requests concurrently | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/usage/#batch-execution) |
| **Result Handlers** | Customize response processing | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/handlers/) |
| **Event Listeners** | Monitor execution lifecycle | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/listeners/) |
| **Rate Limiting** | Token Bucket and adaptive AIMD algorithms | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/rate-limiting/) |
| **Configuration** | Global config via code or environment variables | [Guide](https://rafaelpontezup.github.io/stkai-sdk-python/configuration/) |

## Documentation

Full documentation available at: **https://rafaelpontezup.github.io/stkai-sdk-python/**

- [Getting Started](https://rafaelpontezup.github.io/stkai-sdk-python/getting-started/)
- [RQC Guide](https://rafaelpontezup.github.io/stkai-sdk-python/rqc/)
- [Agents Guide](https://rafaelpontezup.github.io/stkai-sdk-python/agents/)
- [Configuration](https://rafaelpontezup.github.io/stkai-sdk-python/configuration/)
- [API Reference](https://rafaelpontezup.github.io/stkai-sdk-python/api/rqc/)

## Development

```bash
# Clone and setup
git clone https://github.com/rafaelpontezup/stkai-sdk.git
cd stkai-sdk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src --cov-report=term-missing

# Lint and type check
ruff check src tests
mypy src

# Build docs locally
pip install -e ".[docs]"
mkdocs serve
```

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
