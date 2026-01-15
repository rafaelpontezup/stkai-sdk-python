# RQC API Reference

Complete API reference for Remote Quick Commands.

## Main Classes

::: stkai.rqc.RemoteQuickCommand
    options:
      show_root_heading: true
      members:
        - execute
        - execute_many

## Data Models

::: stkai.rqc.RqcRequest
    options:
      show_root_heading: true

::: stkai.rqc.RqcResponse
    options:
      show_root_heading: true

::: stkai.rqc.RqcExecutionStatus
    options:
      show_root_heading: true

## Configuration Options

::: stkai.rqc.RqcOptions
    options:
      show_root_heading: true

::: stkai.rqc.CreateExecutionOptions
    options:
      show_root_heading: true

::: stkai.rqc.GetResultOptions
    options:
      show_root_heading: true

## Result Handlers

::: stkai.rqc.RqcResultHandler
    options:
      show_root_heading: true

::: stkai.rqc.RqcResultContext
    options:
      show_root_heading: true

::: stkai.rqc.JsonResultHandler
    options:
      show_root_heading: true

::: stkai.rqc.RawResultHandler
    options:
      show_root_heading: true

::: stkai.rqc.ChainedResultHandler
    options:
      show_root_heading: true

## Event Listeners

::: stkai.rqc.RqcEventListener
    options:
      show_root_heading: true

::: stkai.rqc.RqcPhasedEventListener
    options:
      show_root_heading: true

::: stkai.rqc.FileLoggingListener
    options:
      show_root_heading: true

## Errors

::: stkai.rqc.MaxRetriesExceededError
    options:
      show_root_heading: true

::: stkai.rqc.RqcResultHandlerError
    options:
      show_root_heading: true

::: stkai.rqc.ExecutionIdIsMissingError
    options:
      show_root_heading: true
