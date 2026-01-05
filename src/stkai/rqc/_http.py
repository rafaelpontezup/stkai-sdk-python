"""
HTTP client implementations for Remote Quick Command.

This module contains concrete implementations of RqcHttpClient
for making authorized HTTP requests to the StackSpot AI API.
"""

import random
from typing import Any, override

import requests

from stkai.rqc._remote_quick_command import RqcHttpClient


class StkCLIRqcHttpClient(RqcHttpClient):
    """HTTP client implementation using StackSpot CLI for authorization."""

    @override
    def get_with_authorization(self, execution_id: str, timeout: int | None = 30) -> requests.Response:
        assert execution_id, "Execution ID can not be empty."
        assert timeout, "Timeout can not be empty."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import get_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        nocache_param = random.randint(0, 1000000)
        url = f"{codebuddy_base_url}/v1/quick-commands/callback/{execution_id}?nocache={nocache_param}"
        headers = {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        response: requests.Response = get_with_authorization(url=url, timeout=timeout, headers=headers)
        return response

    @override
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int | None = 20) -> requests.Response:
        assert slug_name, "RQC slug-name can not be empty."
        assert timeout, "Timeout can not be empty."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import post_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        url = f"{codebuddy_base_url}/v1/quick-commands/create-execution/{slug_name}"

        response: requests.Response = post_with_authorization(url=url, body=data, timeout=timeout)
        return response
