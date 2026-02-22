"""Tests for FileUploader and related classes."""

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from stkai import HttpClient
from stkai._config import STKAI
from stkai._file_upload import (
    FileUploader,
    FileUploadOptions,
    FileUploadRequest,
    FileUploadResponse,
    FileUploadStatus,
    FileUploadTargetType,
)


class MockHttpClient(HttpClient):
    """Mock HTTP client for testing."""

    def __init__(self, response_data: dict | None = None, status_code: int = 200):
        self.response_data = response_data or {}
        self.status_code = status_code
        self.calls: list[tuple[str, dict | None, int]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.calls.append((url, None, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = self.response_data
        response.text = str(self.response_data)

        if self.status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                response=response
            )
        else:
            response.raise_for_status.return_value = None

        return response

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.calls.append((url, data, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = self.response_data
        response.text = str(self.response_data)

        if self.status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                response=response
            )
        else:
            response.raise_for_status.return_value = None

        return response


class TestFileUploadRequest(unittest.TestCase):
    """Tests for FileUploadRequest data class."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def _make_file(self, name: str = "document.pdf") -> Path:
        """Create a temporary file and return its path."""
        file = self.tmp_dir / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("test content")
        return file

    def test_creation_with_string_path(self):
        """Should create request with string file path."""
        test_file = self._make_file("document.pdf")
        request = FileUploadRequest(file_path=str(test_file))

        self.assertEqual(request.file_path, str(test_file))
        self.assertEqual(request.file_name, "document.pdf")
        self.assertEqual(request.target_type, FileUploadTargetType.CONTEXT)
        self.assertEqual(request.expiration, 60)
        self.assertIsNotNone(request.id)
        self.assertEqual(request.metadata, {})

    def test_creation_with_path_object(self):
        """Should create request with Path object."""
        test_file = self._make_file("report.pdf")
        request = FileUploadRequest(file_path=test_file)

        self.assertEqual(request.file_path, test_file)
        self.assertEqual(request.file_name, "report.pdf")

    def test_file_name_extracts_from_nested_path(self):
        """Should extract file name from nested path."""
        test_file = self._make_file("a/b/c/data.csv")
        request = FileUploadRequest(file_path=str(test_file))

        self.assertEqual(request.file_name, "data.csv")

    def test_creation_with_custom_fields(self):
        """Should create request with all custom fields."""
        test_file = self._make_file("doc.pdf")
        request = FileUploadRequest(
            file_path=str(test_file),
            target_type=FileUploadTargetType.KNOWLEDGE_SOURCE,
            target_id="my-ks-slug",
            expiration=120,
            id="custom-id",
            metadata={"source": "test"},
        )

        self.assertEqual(request.target_type, FileUploadTargetType.KNOWLEDGE_SOURCE)
        self.assertEqual(request.target_id, "my-ks-slug")
        self.assertEqual(request.expiration, 120)
        self.assertEqual(request.id, "custom-id")
        self.assertEqual(request.metadata, {"source": "test"})

    def test_creation_fails_when_file_path_is_empty(self):
        """Should fail when file_path is empty."""
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path="")

    def test_creation_fails_when_id_is_empty(self):
        """Should fail when id is explicitly empty."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path=str(test_file), id="")

    def test_creation_fails_when_target_type_is_raw_string(self):
        """Should fail when target_type is a raw string instead of FileUploadTargetType."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path=str(test_file), target_type="CONTEXT")  # type: ignore

    def test_creation_fails_when_knowledge_source_without_target_id(self):
        """Should fail when target_type is KNOWLEDGE_SOURCE but target_id is missing."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(
                file_path=str(test_file),
                target_type=FileUploadTargetType.KNOWLEDGE_SOURCE,
            )

    def test_creation_fails_when_knowledge_source_with_empty_target_id(self):
        """Should fail when target_type is KNOWLEDGE_SOURCE but target_id is empty."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(
                file_path=str(test_file),
                target_type=FileUploadTargetType.KNOWLEDGE_SOURCE,
                target_id="",
            )

    def test_creation_fails_when_knowledge_source_with_blank_target_id(self):
        """Should fail when target_type is KNOWLEDGE_SOURCE but target_id is blank."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(
                file_path=str(test_file),
                target_type=FileUploadTargetType.KNOWLEDGE_SOURCE,
                target_id="   ",
            )

    def test_creation_succeeds_when_context_without_target_id(self):
        """Should succeed when target_type is CONTEXT and target_id is not provided."""
        test_file = self._make_file("doc.pdf")
        request = FileUploadRequest(
            file_path=str(test_file),
            target_type=FileUploadTargetType.CONTEXT,
        )
        self.assertIsNone(request.target_id)

    def test_creation_fails_when_expiration_is_zero(self):
        """Should fail when expiration is zero."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path=str(test_file), expiration=0)

    def test_creation_fails_when_expiration_is_negative(self):
        """Should fail when expiration is negative."""
        test_file = self._make_file("doc.pdf")
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path=str(test_file), expiration=-1)

    def test_creation_fails_when_file_does_not_exist(self):
        """Should fail fast when file does not exist."""
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path="/nonexistent/file.pdf")

    def test_creation_fails_when_path_is_a_directory(self):
        """Should fail fast when path is a directory, not a file."""
        with self.assertRaises(AssertionError):
            FileUploadRequest(file_path=str(self.tmp_dir))

    def test_is_frozen(self):
        """Should be immutable."""
        test_file = self._make_file("doc.pdf")
        request = FileUploadRequest(file_path=str(test_file))

        with self.assertRaises(AttributeError):
            request.file_path = "other.pdf"  # type: ignore


class TestFileUploadResponse(unittest.TestCase):
    """Tests for FileUploadResponse data class."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.tmp_dir / "doc.pdf"
        self.test_file.write_text("test content")

    def _make_request(self) -> FileUploadRequest:
        return FileUploadRequest(file_path=str(self.test_file))

    def test_is_success_returns_true(self):
        """Should return True when status is SUCCESS."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.SUCCESS,
            upload_id="upload-123",
        )

        self.assertTrue(response.is_success())
        self.assertFalse(response.is_error())
        self.assertFalse(response.is_timeout())
        self.assertEqual(response.upload_id, "upload-123")

    def test_is_error_returns_true(self):
        """Should return True when status is ERROR."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.ERROR,
            error="Something went wrong",
        )

        self.assertTrue(response.is_error())
        self.assertFalse(response.is_success())
        self.assertFalse(response.is_timeout())

    def test_is_timeout_returns_true(self):
        """Should return True when status is TIMEOUT."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.TIMEOUT,
            error="Request timed out",
        )

        self.assertTrue(response.is_timeout())
        self.assertFalse(response.is_success())
        self.assertFalse(response.is_error())

    def test_raw_response_default_is_none(self):
        """Should have None as default raw_response."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.SUCCESS,
            upload_id="upload-123",
        )

        self.assertIsNone(response.raw_response)

    def test_raw_response_when_provided(self):
        """Should store raw_response when provided."""
        raw = {"id": "upload-123", "url": "https://s3.example.com", "form": {"key": "val"}}
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.SUCCESS,
            upload_id="upload-123",
            raw_response=raw,
        )

        self.assertEqual(response.raw_response, raw)

    def test_error_with_details_returns_details_on_error(self):
        """Should return error details when status is ERROR."""
        raw = {"error": "something"}
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.ERROR,
            error="Upload failed",
            raw_response=raw,
        )

        details = response.error_with_details()

        self.assertEqual(details["status"], FileUploadStatus.ERROR)
        self.assertEqual(details["error_message"], "Upload failed")
        self.assertEqual(details["response_body"], raw)

    def test_error_with_details_returns_empty_dict_on_success(self):
        """Should return empty dict when status is SUCCESS."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.SUCCESS,
            upload_id="upload-123",
        )

        self.assertEqual(response.error_with_details(), {})

    def test_error_with_details_returns_empty_response_body_when_no_raw_response(self):
        """Should return empty dict as response_body when raw_response is None."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.TIMEOUT,
            error="Timed out",
        )

        details = response.error_with_details()

        self.assertEqual(details["response_body"], {})

    def test_creation_fails_when_request_is_none(self):
        """Should fail when request is None."""
        with self.assertRaises(AssertionError):
            FileUploadResponse(request=None, status=FileUploadStatus.SUCCESS)  # type: ignore

    def test_creation_fails_when_status_is_none(self):
        """Should fail when status is None."""
        with self.assertRaises(AssertionError):
            FileUploadResponse(request=self._make_request(), status=None)  # type: ignore

    def test_is_frozen(self):
        """Should be immutable."""
        response = FileUploadResponse(
            request=self._make_request(),
            status=FileUploadStatus.SUCCESS,
            upload_id="upload-123",
        )

        with self.assertRaises(AttributeError):
            response.upload_id = "other"  # type: ignore


class TestFileUploadOptions(unittest.TestCase):
    """Tests for FileUploadOptions data class."""

    def test_default_values_are_none(self):
        """Should have None as default values (to be filled from config)."""
        options = FileUploadOptions()

        self.assertIsNone(options.request_timeout)
        self.assertIsNone(options.transfer_timeout)
        self.assertIsNone(options.retry_max_retries)
        self.assertIsNone(options.retry_initial_delay)
        self.assertIsNone(options.max_workers)

    def test_custom_values(self):
        """Should accept custom values."""
        options = FileUploadOptions(
            request_timeout=15,
            transfer_timeout=60,
            retry_max_retries=5,
            retry_initial_delay=1.0,
            max_workers=4,
        )

        self.assertEqual(options.request_timeout, 15)
        self.assertEqual(options.transfer_timeout, 60)
        self.assertEqual(options.retry_max_retries, 5)
        self.assertEqual(options.retry_initial_delay, 1.0)
        self.assertEqual(options.max_workers, 4)

    def test_with_defaults_from_fills_none_values(self):
        """Should fill None values from FileUploadConfig fields."""
        cfg = STKAI.config.file_upload

        options = FileUploadOptions()
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.request_timeout, cfg.request_timeout)
        self.assertEqual(resolved.transfer_timeout, cfg.transfer_timeout)
        self.assertEqual(resolved.retry_max_retries, cfg.retry_max_retries)
        self.assertEqual(resolved.retry_initial_delay, cfg.retry_initial_delay)
        self.assertEqual(resolved.max_workers, cfg.max_workers)

    def test_with_defaults_from_preserves_user_values(self):
        """Should preserve user-provided values and only fill None values."""
        cfg = STKAI.config.file_upload

        options = FileUploadOptions(request_timeout=999, transfer_timeout=888)
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.request_timeout, 999)
        self.assertEqual(resolved.transfer_timeout, 888)
        # Filled from config
        self.assertEqual(resolved.retry_max_retries, cfg.retry_max_retries)

    def test_is_frozen(self):
        """Should be immutable."""
        options = FileUploadOptions()

        with self.assertRaises(AttributeError):
            options.request_timeout = 10  # type: ignore


class TestFileUploader(unittest.TestCase):
    """Tests for FileUploader client."""

    def test_init_with_defaults(self):
        """Should initialize with default values from config."""
        uploader = FileUploader()

        self.assertIsNotNone(uploader.options)
        self.assertIsNotNone(uploader.http_client)
        self.assertEqual(uploader.base_url, STKAI.config.file_upload.base_url.rstrip("/"))

    def test_init_with_custom_base_url(self):
        """Should use custom base_url when provided."""
        uploader = FileUploader(
            base_url="https://custom.api.com/",
            http_client=MockHttpClient(),
        )

        self.assertEqual(uploader.base_url, "https://custom.api.com")

    def test_init_with_custom_options(self):
        """Should use custom options when provided."""
        options = FileUploadOptions(request_timeout=15)
        uploader = FileUploader(options=options, http_client=MockHttpClient())

        self.assertEqual(uploader.options.request_timeout, 15)

    def test_init_with_custom_http_client(self):
        """Should use custom HTTP client when provided."""
        mock_client = MockHttpClient()
        uploader = FileUploader(http_client=mock_client)

        self.assertEqual(uploader.http_client, mock_client)

    @patch("stkai._file_upload.requests.post")
    def test_upload_success(self, mock_s3_post: MagicMock, tmp_path=None):
        """Should upload file successfully through both steps."""
        if tmp_path is None:
            import tempfile
            tmp_dir = Path(tempfile.mkdtemp())
        else:
            tmp_dir = tmp_path

        # Create a temporary file
        test_file = tmp_dir / "test.pdf"
        test_file.write_text("test content")

        # Step 1: Mock authenticated API call
        mock_api_client = MockHttpClient(
            response_data={
                "id": "upload-abc-123",
                "url": "https://s3.amazonaws.com/bucket",
                "form": {"key": "uploads/test.pdf", "AWSAccessKeyId": "AKIA..."},
            }
        )

        # Step 2: Mock S3 upload
        mock_s3_response = MagicMock(spec=requests.Response)
        mock_s3_response.status_code = 204
        mock_s3_response.raise_for_status.return_value = None
        mock_s3_post.return_value = mock_s3_response

        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_api_client, options=options)

        response = uploader.upload(FileUploadRequest(file_path=str(test_file)))

        self.assertTrue(response.is_success())
        self.assertEqual(response.upload_id, "upload-abc-123")
        self.assertIsNotNone(response.raw_response)
        self.assertEqual(response.raw_response["id"], "upload-abc-123")
        self.assertEqual(response.raw_response["url"], "https://s3.amazonaws.com/bucket")

        # Verify Step 1 payload
        _, payload, _ = mock_api_client.calls[0]
        self.assertEqual(payload["file_name"], "test.pdf")
        self.assertEqual(payload["target_type"], "CONTEXT")
        self.assertEqual(payload["expiration"], 60)

        # Verify Step 1 URL
        url, _, _ = mock_api_client.calls[0]
        self.assertIn("/v2/file-upload/form", url)

        # Verify Step 2 was called with S3 URL and form fields
        mock_s3_post.assert_called_once()
        s3_call_args = mock_s3_post.call_args
        self.assertEqual(s3_call_args[0][0], "https://s3.amazonaws.com/bucket")
        self.assertEqual(s3_call_args[1]["data"], {"key": "uploads/test.pdf", "AWSAccessKeyId": "AKIA..."})

    @patch("stkai._file_upload.requests.post")
    def test_upload_form_request_payload(self, mock_s3_post: MagicMock):
        """Should send correct payload for Step 1."""
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        test_file = tmp_dir / "report.csv"
        test_file.write_text("data")

        mock_api_client = MockHttpClient(
            response_data={
                "id": "upload-id",
                "url": "https://s3.example.com",
                "form": {"key": "val"},
            }
        )

        mock_s3_response = MagicMock(spec=requests.Response)
        mock_s3_response.status_code = 204
        mock_s3_response.raise_for_status.return_value = None
        mock_s3_post.return_value = mock_s3_response

        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_api_client, options=options)

        request = FileUploadRequest(
            file_path=str(test_file),
            target_type=FileUploadTargetType.KNOWLEDGE_SOURCE,
            target_id="my-ks-slug",
            expiration=120,
        )
        uploader.upload(request)

        _, payload, _ = mock_api_client.calls[0]
        self.assertEqual(payload["file_name"], "report.csv")
        self.assertEqual(payload["target_type"], "KNOWLEDGE_SOURCE")
        self.assertEqual(payload["target_id"], "my-ks-slug")
        self.assertEqual(payload["expiration"], 120)

    def test_upload_file_deleted_between_creation_and_upload(self):
        """Should return error when file is deleted after request creation."""
        tmp_dir = Path(tempfile.mkdtemp())
        test_file = tmp_dir / "test.pdf"
        test_file.write_text("test content")

        mock_client = MockHttpClient()
        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_client, options=options)

        request = FileUploadRequest(file_path=str(test_file))
        test_file.unlink()  # delete file after request creation

        response = uploader.upload(request)

        self.assertTrue(response.is_error())
        self.assertIn("File not found", response.error)
        # Should not have made any HTTP calls
        self.assertEqual(len(mock_client.calls), 0)

    def test_upload_step1_http_error(self):
        """Should return error when Step 1 fails with HTTP error."""
        mock_client = MockHttpClient(
            response_data={"error": "Unauthorized"},
            status_code=401,
        )
        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_client, options=options)

        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        test_file = tmp_dir / "test.pdf"
        test_file.write_text("test content")

        response = uploader.upload(FileUploadRequest(file_path=str(test_file)))

        self.assertTrue(response.is_error())
        self.assertIn("HTTP error 401", response.error)
        self.assertIsNone(response.raw_response)

    @patch("stkai._file_upload.requests.post")
    def test_upload_step2_http_error(self, mock_s3_post: MagicMock):
        """Should return error when Step 2 (S3 upload) fails."""
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        test_file = tmp_dir / "test.pdf"
        test_file.write_text("test content")

        mock_api_client = MockHttpClient(
            response_data={
                "id": "upload-id",
                "url": "https://s3.example.com",
                "form": {"key": "val"},
            }
        )

        # S3 returns 403
        mock_s3_response = MagicMock(spec=requests.Response)
        mock_s3_response.status_code = 403
        mock_s3_response.text = "Forbidden"
        http_error = requests.HTTPError(response=mock_s3_response)
        mock_s3_response.raise_for_status.side_effect = http_error
        mock_s3_post.return_value = mock_s3_response

        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_api_client, options=options)

        response = uploader.upload(FileUploadRequest(file_path=str(test_file)))

        self.assertTrue(response.is_error())
        self.assertIn("File upload failed", response.error)
        self.assertIsNotNone(response.raw_response)
        self.assertEqual(response.raw_response["id"], "upload-id")

    @patch("stkai._file_upload.requests.post")
    def test_upload_many_returns_responses_in_order(self, mock_s3_post: MagicMock):
        """Should return responses in the same order as requests."""
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())

        files = []
        for i in range(3):
            test_file = tmp_dir / f"file{i}.pdf"
            test_file.write_text(f"content {i}")
            files.append(test_file)

        mock_api_client = MockHttpClient(
            response_data={
                "id": "upload-id",
                "url": "https://s3.example.com",
                "form": {"key": "val"},
            }
        )

        mock_s3_response = MagicMock(spec=requests.Response)
        mock_s3_response.status_code = 204
        mock_s3_response.raise_for_status.return_value = None
        mock_s3_post.return_value = mock_s3_response

        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_api_client, options=options)

        request_list = [
            FileUploadRequest(file_path=str(f), id=f"req-{i}")
            for i, f in enumerate(files)
        ]
        responses = uploader.upload_many(request_list)

        self.assertEqual(len(responses), 3)
        for req, resp in zip(request_list, responses, strict=True):
            self.assertIs(resp.request, req)

    def test_upload_many_empty_list(self):
        """Should return empty list for empty request list."""
        uploader = FileUploader(http_client=MockHttpClient())

        responses = uploader.upload_many([])

        self.assertEqual(responses, [])

    @patch("stkai._file_upload.requests.post")
    def test_upload_many_handles_individual_failures(self, mock_s3_post: MagicMock):
        """Should handle individual failures without affecting other uploads."""
        tmp_dir = Path(tempfile.mkdtemp())

        real_file = tmp_dir / "real.pdf"
        real_file.write_text("content")

        doomed_file = tmp_dir / "doomed.pdf"
        doomed_file.write_text("will be deleted")

        mock_api_client = MockHttpClient(
            response_data={
                "id": "upload-id",
                "url": "https://s3.example.com",
                "form": {"key": "val"},
            }
        )

        mock_s3_response = MagicMock(spec=requests.Response)
        mock_s3_response.status_code = 204
        mock_s3_response.raise_for_status.return_value = None
        mock_s3_post.return_value = mock_s3_response

        options = FileUploadOptions(retry_max_retries=0)
        uploader = FileUploader(http_client=mock_api_client, options=options)

        request_list = [
            FileUploadRequest(file_path=str(real_file)),
            FileUploadRequest(file_path=str(doomed_file)),
        ]
        doomed_file.unlink()  # delete file after request creation

        responses = uploader.upload_many(request_list)

        self.assertEqual(len(responses), 2)
        # At least one should succeed and one should fail
        statuses = {r.status for r in responses}
        self.assertIn(FileUploadStatus.ERROR, statuses)

    def test_upload_uses_custom_timeout(self):
        """Should use timeout from options for Step 1."""
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        test_file = tmp_dir / "test.pdf"
        test_file.write_text("content")

        mock_client = MockHttpClient(
            response_data={
                "id": "upload-id",
                "url": "https://s3.example.com",
                "form": {"key": "val"},
            }
        )

        options = FileUploadOptions(request_timeout=15, retry_max_retries=0)
        uploader = FileUploader(http_client=mock_client, options=options)

        # Will fail at S3 step (not mocked), but Step 1 should use our timeout
        with patch("stkai._file_upload.requests.post") as mock_s3:
            mock_s3_resp = MagicMock(spec=requests.Response)
            mock_s3_resp.status_code = 204
            mock_s3_resp.raise_for_status.return_value = None
            mock_s3.return_value = mock_s3_resp

            uploader.upload(FileUploadRequest(file_path=str(test_file)))

        _, _, timeout = mock_client.calls[0]
        self.assertEqual(timeout, 15)


class TestFileUploadStatus(unittest.TestCase):
    """Tests for FileUploadStatus enum."""

    def test_values(self):
        """Should have expected values."""
        self.assertEqual(FileUploadStatus.SUCCESS, "SUCCESS")
        self.assertEqual(FileUploadStatus.ERROR, "ERROR")
        self.assertEqual(FileUploadStatus.TIMEOUT, "TIMEOUT")

    def test_from_exception_timeout(self):
        """Should return TIMEOUT for timeout exceptions."""
        status = FileUploadStatus.from_exception(requests.Timeout())
        self.assertEqual(status, FileUploadStatus.TIMEOUT)

    def test_from_exception_error(self):
        """Should return ERROR for non-timeout exceptions."""
        status = FileUploadStatus.from_exception(ValueError("some error"))
        self.assertEqual(status, FileUploadStatus.ERROR)


class TestFileUploadConfigEnvVars(unittest.TestCase):
    """Tests for file upload config env vars."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_BASE_URL": "https://custom.api.com"})
    def test_file_upload_base_url_env_var(self):
        """Should read base_url from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.base_url, "https://custom.api.com")

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_REQUEST_TIMEOUT": "15"})
    def test_file_upload_request_timeout_env_var(self):
        """Should read request_timeout from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.request_timeout, 15)

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_TRANSFER_TIMEOUT": "60"})
    def test_file_upload_transfer_timeout_env_var(self):
        """Should read transfer_timeout from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.transfer_timeout, 60)

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_RETRY_MAX_RETRIES": "5"})
    def test_file_upload_retry_max_retries_env_var(self):
        """Should read retry_max_retries from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.retry_max_retries, 5)

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_RETRY_INITIAL_DELAY": "1.0"})
    def test_file_upload_retry_initial_delay_env_var(self):
        """Should read retry_initial_delay from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.retry_initial_delay, 1.0)

    @patch.dict(os.environ, {"STKAI_FILE_UPLOAD_MAX_WORKERS": "4"})
    def test_file_upload_max_workers_env_var(self):
        """Should read max_workers from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.file_upload.max_workers, 4)


if __name__ == "__main__":
    unittest.main()
