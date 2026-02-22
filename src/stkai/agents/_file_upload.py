"""
File upload support for StackSpot AI Agents.

This module provides a client for uploading files to be used as context
during agent chat conversations. The upload is a two-step process:
1. POST to Data Integration API to get S3 pre-signed credentials + upload_id
2. POST file to S3 using the pre-signed form data

Note: File uploading via API is only available for Enterprise accounts.

Example:
    >>> from stkai.agents import AgentFileUploader, FileUploadRequest
    >>> uploader = AgentFileUploader()
    >>> response = uploader.upload(FileUploadRequest(file_path="doc.pdf"))
    >>> if response.is_success():
    ...     print(response.upload_id)
"""

import logging
import mimetypes
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import requests

from stkai._config import AgentConfig
from stkai._http import HttpClient
from stkai._retry import Retrying

logger = logging.getLogger(__name__)


class FileUploadStatus(StrEnum):
    """
    Status of a file upload response.

    Attributes:
        SUCCESS: File uploaded successfully.
        ERROR: Client-side error (HTTP error, network issue, file not found).
        TIMEOUT: Any timeout, client or server-side.
    """
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"

    @classmethod
    def from_exception(cls, exc: Exception) -> "FileUploadStatus":
        """
        Determine the appropriate status for an exception.

        Args:
            exc: The exception that occurred during the upload.

        Returns:
            TIMEOUT for timeout exceptions, ERROR for all others.
        """
        from stkai._utils import is_timeout_exception
        return cls.TIMEOUT if is_timeout_exception(exc) else cls.ERROR


@dataclass(frozen=True)
class FileUploadRequest:
    """
    Represents a file upload request.

    Attributes:
        file_path: Path to the file to upload.
        target_type: Upload target type (default: "CONTEXT").
        expiration: Expiration in minutes for the uploaded file (default: 60).
        id: Unique identifier for this request. Auto-generated as UUID if not provided.
        metadata: Optional dictionary for storing custom metadata.

    Example:
        >>> request = FileUploadRequest(file_path="document.pdf")
        >>> request = FileUploadRequest(file_path=Path("/tmp/doc.pdf"), expiration=120)
    """
    file_path: str | Path
    target_type: str = "CONTEXT"
    expiration: int = 60
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.id, "Request ID cannot be empty."
        assert self.file_path, "File path cannot be empty."
        assert self.target_type, "Target type cannot be empty."
        assert self.expiration is not None, "Target type cannot be None."
        assert self.expiration > 0, "Expiration must be greater than 0."

        file_path = Path(self.file_path)
        assert file_path.exists(), f"File path not found: {file_path}"
        assert file_path.is_file(), f"File path is not a file: {file_path}"

    @property
    def file_name(self) -> str:
        """Extract file name from the file path."""
        return Path(self.file_path).name

    def to_api_payload(self) -> dict[str, Any]:
        """Converts the request to the API payload format for the pre-signed form endpoint."""
        return {
            "file_name": self.file_name,
            "target_type": self.target_type,
            "expiration": self.expiration,
        }


@dataclass(frozen=True)
class FileUploadResponse:
    """
    Represents a response from a file upload operation.

    Attributes:
        request: The original request that generated this response.
        status: The status of the response (SUCCESS, ERROR, TIMEOUT).
        upload_id: The upload ID returned by the API on success.
        error: Error message if the upload failed.
        raw_response: Raw API response from Step 1 (pre-signed form request).

    Example:
        >>> if response.is_success():
        ...     print(response.upload_id)
        ... else:
        ...     print(f"Error: {response.error}")
    """
    request: FileUploadRequest
    status: FileUploadStatus
    upload_id: str | None = None
    error: str | None = None
    raw_response: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        assert self.request, "Request cannot be empty."
        assert self.status, "Status cannot be empty."

    def is_success(self) -> bool:
        """Returns True if the upload was successful."""
        return self.status == FileUploadStatus.SUCCESS

    def is_error(self) -> bool:
        """Returns True if there was an error."""
        return self.status == FileUploadStatus.ERROR

    def is_timeout(self) -> bool:
        """Returns True if the upload timed out."""
        return self.status == FileUploadStatus.TIMEOUT

    def error_with_details(self) -> dict[str, Any]:
        """Returns a dictionary with error details for non-success responses."""
        if self.is_success():
            return {}

        return {
            "status": self.status,
            "error_message": self.error,
            "response_body": self.raw_response or {},
        }


@dataclass(frozen=True)
class FileUploadOptions:
    """
    Configuration options for the AgentFileUploader client.

    Fields set to None will use values from global config (STKAI.config.agent).

    Attributes:
        request_timeout: HTTP timeout for Step 1 (get pre-signed form).
        transfer_timeout: HTTP timeout for Step 2 (file transfer to S3).
        retry_max_retries: Maximum retry attempts for transient failures.
        retry_initial_delay: Initial delay for first retry (exponential backoff).
        max_workers: Maximum threads for upload_many().

    Example:
        >>> options = FileUploadOptions(request_timeout=15, transfer_timeout=60)
        >>> uploader = AgentFileUploader(options=options)
    """
    request_timeout: int | None = None
    transfer_timeout: int | None = None
    retry_max_retries: int | None = None
    retry_initial_delay: float | None = None
    max_workers: int | None = None

    def with_defaults_from(self, cfg: AgentConfig) -> "FileUploadOptions":
        """
        Returns a new FileUploadOptions with None values filled from config.

        Reads from the dedicated cfg.file_upload_* fields.

        Args:
            cfg: The AgentConfig to use for default values.

        Returns:
            A new FileUploadOptions with all fields resolved (no None values).
        """
        return FileUploadOptions(
            request_timeout=self.request_timeout if self.request_timeout is not None else cfg.file_upload_request_timeout,
            transfer_timeout=self.transfer_timeout if self.transfer_timeout is not None else cfg.file_upload_transfer_timeout,
            retry_max_retries=self.retry_max_retries if self.retry_max_retries is not None else cfg.file_upload_retry_max_retries,
            retry_initial_delay=self.retry_initial_delay if self.retry_initial_delay is not None else cfg.file_upload_retry_initial_delay,
            max_workers=self.max_workers if self.max_workers is not None else cfg.file_upload_max_workers,
        )


class AgentFileUploader:
    """
    Client for uploading files to be used as context in StackSpot AI Agent chats.

    The upload is a two-step process:
    1. Request pre-signed S3 credentials from the Data Integration API (authenticated)
    2. Upload the file to S3 using the pre-signed form (unauthenticated)

    Note: File uploading via API is only available for Enterprise accounts.

    Example:
        >>> from stkai.agents import AgentFileUploader, FileUploadRequest
        >>> uploader = AgentFileUploader()
        >>> response = uploader.upload(FileUploadRequest(file_path="doc.pdf"))
        >>> if response.is_success():
        ...     print(response.upload_id)

    Attributes:
        base_url: The base URL for the Data Integration API.
        options: Configuration options for the client.
        http_client: HTTP client for authenticated API calls.
    """

    def __init__(
        self,
        base_url: str | None = None,
        options: FileUploadOptions | None = None,
        http_client: HttpClient | None = None,
    ):
        """
        Initialize the AgentFileUploader client.

        Args:
            base_url: Base URL for the Data Integration API.
                If None, uses global config (STKAI.config.agent.file_upload_base_url).
            options: Configuration options for the client.
                If None, uses defaults from global config.
            http_client: Custom HTTP client for authenticated API calls (Step 1).
                If None, uses EnvironmentAwareHttpClient (auto-detects CLI or standalone).
        """
        from stkai._config import STKAI
        cfg = STKAI.config.agent

        resolved_options = (options or FileUploadOptions()).with_defaults_from(cfg)

        if base_url is None:
            base_url = cfg.file_upload_base_url

        if not http_client:
            from stkai._http import EnvironmentAwareHttpClient
            http_client = EnvironmentAwareHttpClient()

        assert base_url, "FileUploader base_url cannot be empty."
        assert http_client is not None, "FileUploader http_client cannot be None."
        assert resolved_options.max_workers is not None, "Thread-pool max_workers can not be empty."
        assert resolved_options.max_workers > 0, "Thread-pool max_workers must be greater than 0."

        self.base_url = base_url.rstrip("/")
        self.options = resolved_options
        self.max_workers = resolved_options.max_workers
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.http_client: HttpClient = http_client

    def upload(self, request: FileUploadRequest) -> FileUploadResponse:
        """
        Upload a file and wait for the response (blocking).

        Args:
            request: The file upload request.

        Returns:
            FileUploadResponse with the upload_id or error information.

        Example:
            >>> response = uploader.upload(FileUploadRequest(file_path="doc.pdf"))
            >>> if response.is_success():
            ...     print(response.upload_id)
        """
        logger.info(f"{request.id[:26]:<26} | FileUpload | 📤 Starting file upload.")
        logger.info(f"{request.id[:26]:<26} | FileUpload |    ├ base_url={self.base_url}")
        logger.info(f"{request.id[:26]:<26} | FileUpload |    └ file_name='{request.file_name}'")

        response = self._do_upload(request)

        logger.info(f"{request.id[:26]:<26} | FileUpload | 📤 File upload finished.")
        logger.info(f"{request.id[:26]:<26} | FileUpload |    ├ with status = {response.status}")
        if response.is_success():
            logger.info(f"{request.id[:26]:<26} | FileUpload |    └ with upload_id = {response.upload_id}")
        else:
            logger.info(f"{request.id[:26]:<26} | FileUpload |    └ with error message = \"{response.error}\"")

        assert response.request is request, \
            "🌀 Sanity check | Unexpected mismatch: response does not reference its corresponding request."
        return response

    def upload_many(self, request_list: list[FileUploadRequest]) -> list[FileUploadResponse]:
        """
        Upload multiple files concurrently, wait for all responses (blocking),
        and return them in the same order as `request_list`.

        Args:
            request_list: List of FileUploadRequest objects to upload.

        Returns:
            List[FileUploadResponse]: One response per request, in the same order.

        Example:
            >>> responses = uploader.upload_many([
            ...     FileUploadRequest(file_path="doc1.pdf"),
            ...     FileUploadRequest(file_path="doc2.pdf"),
            ... ])
            >>> upload_ids = [r.upload_id for r in responses if r.is_success()]
        """
        if not request_list:
            return []

        logger.info(
            f"{'FileUpload-Batch'[:26]:<26} | FileUpload | "
            f"📤 Starting batch upload of {len(request_list)} files."
        )
        logger.info(f"{'FileUpload-Batch'[:26]:<26} | FileUpload |    ├ base_url={self.base_url}")
        logger.info(f"{'FileUpload-Batch'[:26]:<26} | FileUpload |    └ max_concurrent={self.max_workers}")

        future_to_index = {
            self.executor.submit(self._do_upload, req): idx
            for idx, req in enumerate(request_list)
        }

        responses_map: dict[int, FileUploadResponse] = {}

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            correlated_request = request_list[idx]
            try:
                responses_map[idx] = future.result()
            except Exception as e:
                logger.error(
                    f"{correlated_request.id[:26]:<26} | FileUpload | ❌ Upload failed in batch(seq={idx}). {e}",
                    exc_info=logger.isEnabledFor(logging.DEBUG)
                )
                responses_map[idx] = FileUploadResponse(
                    request=correlated_request,
                    status=FileUploadStatus.ERROR,
                    error=str(e),
                )

        responses = [responses_map[i] for i in range(len(request_list))]

        assert len(responses) == len(request_list), (
            f"🌀 Sanity check | Unexpected mismatch: responses(size={len(responses)}) is different from requests(size={len(request_list)})."
        )
        assert all(resp.request is req for req, resp in zip(request_list, responses, strict=True)), (
            "🌀 Sanity check | Unexpected mismatch: some responses do not reference their corresponding requests."
        )

        logger.info(
            f"{'FileUpload-Batch'[:26]:<26} | FileUpload | 📤 Batch upload finished."
        )

        from collections import Counter
        totals_per_status = Counter(r.status for r in responses)
        items = totals_per_status.items()
        for idx_s, (status, total) in enumerate(items):
            icon = "└" if idx_s == (len(items) - 1) else "├"
            logger.info(f"{'FileUpload-Batch'[:26]:<26} | FileUpload |    {icon} total with status {status:<7} = {total}")

        return responses

    def _do_upload(self, request: FileUploadRequest) -> FileUploadResponse:
        """
        Internal method that executes the full upload workflow.

        Always returns a FileUploadResponse (never raises exceptions).

        Args:
            request: The file upload request.

        Returns:
            FileUploadResponse with the upload_id or error information.
        """
        assert request, "🌀 Sanity check | FileUploadRequest can not be None."
        assert request.id, "🌀 Sanity check | FileUploadRequest ID can not be None."

        assert self.options.request_timeout is not None, \
            "🌀 Sanity check | request_timeout must be set after with_defaults_from()"
        assert self.options.transfer_timeout is not None, \
            "🌀 Sanity check | transfer_timeout must be set after with_defaults_from()"
        assert self.options.retry_max_retries is not None, \
            "🌀 Sanity check | retry_max_retries must be set after with_defaults_from()"
        assert self.options.retry_initial_delay is not None, \
            "🌀 Sanity check | retry_initial_delay must be set after with_defaults_from()"

        form_data: dict[str, Any] | None = None

        try:
            # Validate file exists before making API calls
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            if not file_path.is_file():
                raise ValueError(f"Path is not a file: {file_path}")

            # Step 1: Generate pre-signed upload form
            form_data = self._generate_presigned_form(request)
            upload_id = form_data["id"]
            s3_url = form_data["url"]
            s3_form_fields = form_data["form"]

            # Step 2: Upload file to S3
            self._upload_file_to_s3(request, s3_url, s3_form_fields)

            logger.info(
                f"{request.id[:26]:<26} | FileUpload | "
                f"✅ File uploaded successfully (upload_id={upload_id})"
            )

            return FileUploadResponse(
                request=request,
                status=FileUploadStatus.SUCCESS,
                upload_id=upload_id,
                raw_response=form_data,
            )

        except Exception as e:
            error_status = FileUploadStatus.from_exception(e)
            error_msg = f"File upload failed: {e}"
            if isinstance(e, requests.HTTPError) and e.response is not None:
                error_msg = f"File upload failed due to an HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(
                f"{request.id[:26]:<26} | FileUpload | ❌ {error_msg}",
                exc_info=logger.isEnabledFor(logging.DEBUG)
            )
            return FileUploadResponse(
                request=request,
                status=error_status,
                error=error_msg,
                raw_response=form_data,
            )

    def _generate_presigned_form(self, request: FileUploadRequest) -> dict[str, Any]:
        """
        Step 1: Request pre-signed S3 upload form from the Data Integration API.

        Args:
            request: The file upload request.

        Returns:
            Dict with 'id', 'url', and 'form' keys from the API response.

        Raises:
            requests.HTTPError: On non-2xx response.
            MaxRetriesExceededError: When retries are exhausted.
        """
        assert self.options.request_timeout is not None
        assert self.options.retry_max_retries is not None
        assert self.options.retry_initial_delay is not None

        for attempt in Retrying(
            max_retries=self.options.retry_max_retries,
            initial_delay=self.options.retry_initial_delay,
            logger_prefix=f"{request.id[:26]:<26} | FileUpload",
        ):
            with attempt:
                logger.info(
                    f"{request.id[:26]:<26} | FileUpload | "
                    f"Step 1: Generating presigned upload form (attempt {attempt.attempt_number}/{attempt.max_attempts})..."
                )

                url = f"{self.base_url}/v2/file-upload/form"
                http_response = self.http_client.post(
                    url=url,
                    data=request.to_api_payload(),
                    timeout=self.options.request_timeout,
                )
                assert isinstance(http_response, requests.Response), \
                    f"🌀 Sanity check | Object returned by `post` method is not an instance of `requests.Response`. ({http_response.__class__})"

                http_response.raise_for_status()
                response_data: dict[str, Any] = http_response.json()

                assert "id" in response_data, f"🌀 Sanity check | API response missing 'id' field. Response: {response_data}"
                assert "url" in response_data, f"🌀 Sanity check | API response missing 'url' field. Response: {response_data}"
                assert "form" in response_data, f"🌀 Sanity check | API response missing 'form' field. Response: {response_data}"

                logger.info(
                    f"{request.id[:26]:<26} | FileUpload | "
                    f"Step 1: Presigned upload form received (upload_id={response_data['id']})"
                )
                return response_data

        raise RuntimeError(
            "Unexpected error while getting upload form: "
            "reached end of `_generate_presigned_form` method without returning a response."
        )

    def _upload_file_to_s3(
        self,
        request: FileUploadRequest,
        s3_url: str,
        form_fields: dict[str, str],
    ) -> None:
        """
        Step 2: Upload file to S3 using the pre-signed form data.

        Uses raw requests.post() since this is an unauthenticated multipart upload.

        Args:
            request: The file upload request.
            s3_url: The S3 pre-signed URL.
            form_fields: The form fields for the multipart upload.

        Raises:
            requests.HTTPError: On non-2xx response from S3.
            MaxRetriesExceededError: When retries are exhausted.
        """
        assert self.options.transfer_timeout is not None
        assert self.options.retry_max_retries is not None
        assert self.options.retry_initial_delay is not None

        for attempt in Retrying(
            max_retries=self.options.retry_max_retries,
            initial_delay=self.options.retry_initial_delay,
            logger_prefix=f"{request.id[:26]:<26} | FileUpload",
        ):
            with attempt:
                logger.info(
                    f"{request.id[:26]:<26} | FileUpload | "
                    f"Step 2: Uploading file to S3 (attempt {attempt.attempt_number}/{attempt.max_attempts})..."
                )

                file_path = Path(request.file_path)
                content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

                with file_path.open("rb") as f:
                    http_response = requests.post(
                        s3_url,
                        data=form_fields,
                        files={"file": (request.file_name, f, content_type)},
                        timeout=self.options.transfer_timeout,
                    )

                http_response.raise_for_status()

                logger.debug(
                    f"{request.id[:26]:<26} | FileUpload | "
                    f"Step 2: S3 response: status={http_response.status_code}\n{http_response.text}"
                )
                logger.info(
                    f"{request.id[:26]:<26} | FileUpload | "
                    f"Step 2: File uploaded to S3 successfully"
                )
                return

        raise RuntimeError(
            "Unexpected error while uploading to S3: "
            "reached end of `_upload_file_to_s3` method without returning."
        )
