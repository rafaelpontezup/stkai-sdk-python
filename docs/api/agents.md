# Agents API Reference

Complete API reference for AI Agents.

## Main Classes

::: stkai.agents.Agent
    options:
      show_root_heading: true
      members:
        - chat
        - chat_many

## Data Models

::: stkai.agents.ChatRequest
    options:
      show_root_heading: true

::: stkai.agents.ChatResponse
    options:
      show_root_heading: true

::: stkai.agents.ChatStatus
    options:
      show_root_heading: true

::: stkai.agents.ChatTokenUsage
    options:
      show_root_heading: true

## Conversation

::: stkai.agents.UseConversation
    options:
      show_root_heading: true
      members:
        - with_generated_id

::: stkai.agents.ConversationContext
    options:
      show_root_heading: true
      members:
        - conversation_id
        - has_conversation_id
        - enrich
        - update_if_absent

## File Upload

::: stkai.FileUploader
    options:
      show_root_heading: true
      members:
        - upload
        - upload_many

::: stkai.FileUploadRequest
    options:
      show_root_heading: true

::: stkai.FileUploadResponse
    options:
      show_root_heading: true

::: stkai.FileUploadStatus
    options:
      show_root_heading: true

::: stkai.FileUploadOptions
    options:
      show_root_heading: true

## Configuration

::: stkai.agents.AgentOptions
    options:
      show_root_heading: true
