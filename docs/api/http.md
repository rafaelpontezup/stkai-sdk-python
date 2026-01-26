# HTTP Client API Reference

Complete API reference for HTTP clients.

## Base Interface

::: stkai.HttpClient
    options:
      show_root_heading: true

## Implementations

::: stkai.StkCLIHttpClient
    options:
      show_root_heading: true

::: stkai.StandaloneHttpClient
    options:
      show_root_heading: true

::: stkai.EnvironmentAwareHttpClient
    options:
      show_root_heading: true

## Rate Limiting

::: stkai.RateLimitedHttpClient
    options:
      show_root_heading: true

::: stkai.AdaptiveRateLimitedHttpClient
    options:
      show_root_heading: true

::: stkai.TokenAcquisitionTimeoutError
    options:
      show_root_heading: true

## Authentication

::: stkai.AuthProvider
    options:
      show_root_heading: true

::: stkai.ClientCredentialsAuthProvider
    options:
      show_root_heading: true

::: stkai.AuthenticationError
    options:
      show_root_heading: true

::: stkai.create_standalone_auth
    options:
      show_root_heading: true
