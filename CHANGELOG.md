# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.15] - 2026-02-27

### Added
- **Experimental:** `Agent.chat_stream()` for real-time SSE streaming of Agent responses
- `ChatResponseStream` context manager with `text_stream`, `until_done()`, and `get_final_response()` helpers
- `ChatResponseStreamEvent` and `ChatResponseStreamEventType` for typed stream events (DELTA, DONE, ERROR)
- `result_handler` support in `chat_stream()` (applied after full accumulation, not per chunk)
- `post_stream()` method on all `HttpClient` implementations (CLI, Standalone, RateLimited)
- `UseConversation` integration with streaming (auto-captures `conversation_id`)

### Changed
- `StkCLIHttpClient.post_stream()` now delegates to `post_with_authorization(stream=True)` instead of manual auth header workaround

## [0.4.14] - 2026-02-23

### Added
- `FileUploader` for uploading files to the StackSpot platform (Enterprise only)
- `FileUploader.upload()` and `upload_many()` for single and batch uploads
- `FileUploadRequest` with support for `CONTEXT` and `KNOWLEDGE_SOURCE` target types
- `CHANGELOG.md` with historical entries from v0.2.1 to v0.4.13
- Automated GitHub Releases creation from changelog content in CI pipeline
- Release script now validates and updates `CHANGELOG.md` during release process

### Changed
- `FileUploader` is now a standalone top-level component (previously nested under Agents)

### Fixed
- Include `raw_response` in `FileUploadResponse` even on error

## [0.4.13] - 2026-02-19

### Added
- `UseConversation.with_generated_id()` factory method for pre-generated ULID conversation IDs (useful with `chat_many()`)

## [0.4.12] - 2026-02-18

### Added
- `UseConversation` context manager for automatic multi-turn conversation tracking in Agent

## [0.4.11] - 2026-02-13

### Added
- `Agent.chat_many()` for concurrent batch execution with thread pool

## [0.4.10] - 2026-02-13

### Changed
- Improved RQC and Agent chained result-handlers for better debuggability and troubleshooting

## [0.4.9] - 2026-02-13

### Fixed
- Polling routine safely parses unknown server statuses instead of crashing
- TIMEOUT status documentation and error handling with other kinds of timeouts
- Status transition: `COMPLETED` -> `ERROR`

## [0.4.8] - 2026-02-06

### Changed
- Internal code improvements

## [0.4.7] - 2026-02-06

### Added
- Rate-limiting simulations with discrete-event simulation (SimPy)
- Simulation reference analysis and graphs

## [0.4.6] - 2026-01-30

### Fixed
- Assert message in sanity checks

## [0.4.5] - 2026-01-30

### Added
- Sanity checks on `Agent.chat()`

## [0.4.4] - 2026-01-30

### Changed
- Improved Agent logging

## [0.4.3] - 2026-01-30

### Changed
- Improved RQC code readability and logging
- Added `Jitter` abstraction to simplify rate limiter code

### Fixed
- Use `time.monotonic()` instead of `time.time()` in rate limiters
- Unified AIMD jitter to symmetric +/-20% in rate limiters

## [0.4.2] - 2026-01-29

### Added
- Experimental `CongestionAwareHttpClient` with latency-based concurrency control (Little's Law)
- Jitter in `AdaptiveRateLimitedHttpClient` to prevent thundering herd effects
- Rate-limit presets: `conservative`, `balanced`, `optimistic`

## [0.4.1] - 2026-01-27

### Added
- Rate-limit presets feature (`RateLimitConfig.conservative_preset()`, `balanced_preset()`, `optimistic_preset()`)

## [0.4.0] - 2026-01-26

### Added
- Retry support for `Agent.chat()` with exponential backoff
- `StkCLI` class as public API
- HTTP 408 (Request Timeout) is now retried by default
- Rate-limit exceptions are now retried by default

### Changed
- **Breaking:** Retry config renamed from `backoff_factor` to `initial_delay` for RQC and Agent
- Better error handling and status notifications for RQC and Agent
- Improved exception hierarchy for rate limiting
- Moved `AdaptiveRateLimitedHttpClient` HTTP 429 handling to the `Retrying` layer

## [0.3.0] - 2026-01-16

### Added
- `STKAI.explain()` for debugging configuration (prints values with sources)
- Warning log when auth credentials exist but running in CLI mode

### Changed
- Improved config explain formatting

## [0.2.1] - 2026-01-13

### Added
- Initial release with Remote Quick Commands (RQC) support
- `RemoteQuickCommand` client with `execute()` and `execute_many()`
- `Agent` client for StackSpot AI Agents
- Authentication via StackSpot CLI or client credentials
- `EnvironmentAwareHttpClient` with auto-detection
- Token Bucket and Adaptive (AIMD) rate limiting strategies
- `JsonResultHandler`, `RawResultHandler`, `ChainedResultHandler`
- `FileLoggingListener` for request/response logging
- Global configuration via `STKAI.configure()`
