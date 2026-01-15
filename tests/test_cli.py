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

    def test_returns_none_when_empty_string(self):
        """Should return None when __codebuddy_base_url__ is empty string."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = ""

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            result = StkCLI.get_codebuddy_base_url()
            self.assertIsNone(result)

    def test_returns_none_when_none_value(self):
        """Should return None when __codebuddy_base_url__ is None."""
        mock_oscli = ModuleType("oscli")
        mock_oscli.__codebuddy_base_url__ = None

        with patch.dict(sys.modules, {"oscli": mock_oscli}):
            result = StkCLI.get_codebuddy_base_url()
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
