"""
StackSpot CLI (oscli) integration.

This module provides an abstraction layer for interacting with the StackSpot CLI,
allowing the SDK to detect CLI mode and retrieve CLI-specific configuration.
"""

from __future__ import annotations


class StkCLI:
    """
    Abstraction for StackSpot CLI (oscli) integration.

    Provides methods to:
    - Check if running in CLI mode (oscli available)
    - Retrieve CLI-specific configuration values

    Example:
        >>> if StkCLI.is_available():
        ...     base_url = StkCLI.get_codebuddy_base_url()
    """

    @staticmethod
    def is_available() -> bool:
        """
        Check if StackSpot CLI (oscli) is available.

        Returns:
            True if oscli can be imported (CLI mode), False otherwise.
        """
        try:
            import oscli  # noqa: F401

            return True
        except ImportError:
            return False

    @staticmethod
    def get_codebuddy_base_url() -> str | None:
        """
        Get CodeBuddy base URL from CLI if available.

        Returns:
            The CLI's __codebuddy_base_url__ if oscli is installed
            and the attribute exists, None otherwise.
        """
        try:
            from oscli import __codebuddy_base_url__

            assert __codebuddy_base_url__, \
                "🌀 Sanity check | __codebuddy_base_url__ must not be empty. This oscli version seems to be broken."
            assert isinstance(__codebuddy_base_url__, str), \
                "🌀 Sanity check | __codebuddy_base_url__ must be a string. This oscli version seems to be broken."

            return __codebuddy_base_url__ if __codebuddy_base_url__ else None
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def get_inference_app_base_url() -> str | None:
        """
        Get Inference-App base URL from CLI if available.

        Returns:
            The CLI's Inference-App base URL if oscli is installed
            and the attribute exists, None otherwise.
        """
        codebuddy_base_url = StkCLI.get_codebuddy_base_url()
        if codebuddy_base_url:
            return codebuddy_base_url.replace("genai-code-buddy-api", "genai-inference-app")
        return None
