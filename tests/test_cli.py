"""Tests for StkCLI abstraction."""

import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from stkai._cli import StkCLI


class TestStkCLIIsAvailable(unittest.TestCase):
    """Tests for StkCLI.is_available() method."""

    def test_returns_true_when_oscli_installed(self):
        """Should return True when oscli can be imported."""
        mock_oscli = ModuleType("oscli")

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            self.assertTrue(StkCLI.is_available())

    def test_returns_false_when_oscli_not_installed(self):
        """Should return False when oscli import fails."""
        # Ensure oscli is not in sys.modules
        with patch.dict(sys.modules, {"oscli": None}):
            # Remove from sys.modules to force ImportError
            sys.modules.pop("oscli", None)

        # Now test without oscli
        self.assertFalse(StkCLI.is_available())


class TestStkCLIGetCodebuddyBaseUrl(unittest.TestCase):
    """Tests for StkCLI.get_codebuddy_base_url() method."""

    def test_returns_url_when_available(self):
        """Should return CLI's __codebuddy_base_url__ when available."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = "https://cli-provided.example.com"

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            result = StkCLI.get_codebuddy_base_url()
            self.assertEqual(result, "https://cli-provided.example.com")

    def test_returns_none_when_oscli_not_installed(self):
        """Should return None when oscli is not installed."""
        # Ensure oscli is not in sys.modules
        with patch.dict(sys.modules, {"oscli": None}):
            sys.modules.pop("oscli", None)

        result = StkCLI.get_codebuddy_base_url()
        self.assertIsNone(result)

    def test_returns_none_when_attribute_missing(self):
        """Should return None when __codebuddy_base_url__ attribute is missing."""
        mock_oscli = ModuleType("oscli")
        # Don't set __codebuddy_base_url__ attribute

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            result = StkCLI.get_codebuddy_base_url()
            self.assertIsNone(result)

    def test_raises_assertion_error_when_empty_string(self):
        """Should raise AssertionError when __codebuddy_base_url__ is empty string (fail fast)."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = ""

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            with self.assertRaises(AssertionError) as ctx:
                StkCLI.get_codebuddy_base_url()
            self.assertIn("must not be empty", str(ctx.exception))

    def test_raises_assertion_error_when_none_value(self):
        """Should raise AssertionError when __codebuddy_base_url__ is None (fail fast)."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = None

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            with self.assertRaises(AssertionError) as ctx:
                StkCLI.get_codebuddy_base_url()
            self.assertIn("must not be empty", str(ctx.exception))

    def test_raises_assertion_error_when_not_a_string(self):
        """Should raise AssertionError when __codebuddy_base_url__ is not a string (fail fast)."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = 12345  # Not a string

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            with self.assertRaises(AssertionError) as ctx:
                StkCLI.get_codebuddy_base_url()
            self.assertIn("must be a string", str(ctx.exception))


class TestStkCLIGetInferenceAppBaseUrl(unittest.TestCase):
    """Tests for StkCLI.get_inference_app_base_url() method."""

    @patch.object(StkCLI, "get_codebuddy_base_url")
    def test_returns_transformed_url_when_available(self, mock_get_codebuddy):
        """Should return codebuddy URL with genai-inference-app replacement."""
        mock_get_codebuddy.return_value = "https://genai-code-buddy-api.stackspot.com"

        result = StkCLI.get_inference_app_base_url()

        self.assertEqual(result, "https://genai-inference-app.stackspot.com")
        mock_get_codebuddy.assert_called_once()

    @patch.object(StkCLI, "get_codebuddy_base_url")
    def test_replaces_genai_code_buddy_api_in_url(self, mock_get_codebuddy):
        """Should replace genai-code-buddy-api with genai-inference-app."""
        mock_get_codebuddy.return_value = "https://genai-code-buddy-api.example.com/api"

        result = StkCLI.get_inference_app_base_url()

        self.assertEqual(result, "https://genai-inference-app.example.com/api")

    @patch.object(StkCLI, "get_codebuddy_base_url")
    def test_returns_original_url_when_pattern_not_found(self, mock_get_codebuddy):
        """Should return original URL if genai-code-buddy-api is not in the URL."""
        mock_get_codebuddy.return_value = "https://custom-api.example.com"

        result = StkCLI.get_inference_app_base_url()

        self.assertEqual(result, "https://custom-api.example.com")

    @patch.object(StkCLI, "get_codebuddy_base_url")
    def test_returns_none_when_codebuddy_url_is_none(self, mock_get_codebuddy):
        """Should return None when get_codebuddy_base_url returns None."""
        mock_get_codebuddy.return_value = None

        result = StkCLI.get_inference_app_base_url()

        self.assertIsNone(result)
        mock_get_codebuddy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
