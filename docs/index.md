# StackSpot AI SDK for Python

An unofficial, opinionated Python SDK for **StackSpot AI** — built to make integration with the platform reliable and straightforward.

!!! warning "Community SDK"
    This is **not** an official StackSpot product. It is a community-driven SDK built to fill gaps we encountered in real-world projects — such as retries, rate limiting, and batch execution — that the platform's API alone doesn't provide out of the box.

## What is StackSpot AI?

[StackSpot AI](https://ai.stackspot.com/) is an AI-powered platform designed to accelerate software development by providing:

- **Remote Quick Commands (RQC)**: Execute AI-powered commands that analyze, transform, and generate code
- **AI Agents**: Interactive AI assistants with context-aware conversations and knowledge sources
- **Knowledge Sources**: Custom knowledge bases that enrich AI responses with your organization's context

!!! tip "Platform Documentation"
    For more information about the StackSpot AI platform, visit the [official documentation](https://ai.stackspot.com/docs).

## About This SDK

The `stkai` SDK provides a clean, Pythonic interface for integrating StackSpot AI services into your applications. It handles:

- **Authentication**: Automatic token management via StackSpot CLI or standalone OAuth2
- **Retry Logic**: Exponential backoff for transient failures
- **Rate Limiting**: Built-in rate limiting to avoid API throttling
- **Type Safety**: Full type annotations for IDE autocompletion and static analysis

## Design Philosophy

This SDK is **opinionated by design**. It is built around four key trade-offs that guide every decision:

| We favor... | Over... | Why |
|-------------|---------|-----|
| **Reliability** | Latency | Built-in retries, rate limiting, and fault tolerance ensure your requests succeed even under adverse conditions |
| **Predictability** | Throughput | Synchronous, blocking API makes debugging straightforward and behavior easy to reason about |
| **Pragmatism** | Flexibility | Simple, direct API with focused extension points (handlers, listeners) rather than overwhelming configuration options |
| **Convention** | Configuration | Sensible defaults and seamless StackSpot CLI integration get you productive in minutes, not hours |

!!! note "What this means for you"
    If you need high-throughput async processing or maximum flexibility, this SDK may not be the best fit.
    But if you value reliability, simplicity, and a great developer experience, you're in the right place.

## Features

| Feature | Description |
|---------|-------------|
| **[Remote Quick Commands](rqc/index.md)** | Execute AI-powered commands with automatic polling, batch processing, and customizable result handlers |
| **[AI Agents](agents/index.md)** | Chat with AI agents with batch execution, conversation context, knowledge sources, and file upload |
| **[Flexible Configuration](configuration.md)** | Configure via code or environment variables with sensible defaults |
| **[Rate Limiting](rqc/rate-limiting.md)** | Built-in rate limiting with Token Bucket and adaptive AIMD algorithms |

## Quick Example

=== "Remote Quick Commands"

    ```python
    from stkai import RemoteQuickCommand, RqcRequest

    # Create a client for your Quick Command
    rqc = RemoteQuickCommand(slug_name="analyze-code")

    # Execute a request
    response = rqc.execute(
        request=RqcRequest(payload={"code": "def hello(): pass"})
    )

    if response.is_completed():
        print(f"Result: {response.result}")
    ```

=== "Agents"

    ```python
    from stkai import Agent, ChatRequest

    # Create an Agent client
    agent = Agent(agent_id="my-assistant")

    # Send a chat message
    response = agent.chat(
        request=ChatRequest(user_prompt="What is SOLID?")
    )

    if response.is_success():
        print(f"Agent: {response.result}")
    ```

## Requirements

- **Python 3.12+**
- **StackSpot CLI** (`oscli`) installed and authenticated, OR
- **Client Credentials** for standalone authentication

## Installation

```bash
pip install stkai
```

For development:

```bash
pip install stkai[dev]
```

## Next Steps

- [Getting Started](getting-started.md) - Installation and basic setup
- [Remote Quick Commands](rqc/index.md) - Learn about RQC
- [Agents](agents/index.md) - Learn about AI Agents
- [Configuration](configuration.md) - Configure the SDK

## License

Apache License 2.0 - see [LICENSE](https://github.com/rafaelpontezup/stkai-sdk-python/blob/main/LICENSE) for details.
