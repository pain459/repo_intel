import io
from email.message import Message
from types import TracebackType
from typing import Self
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from repo_intel.runtime.http import HttpState, UrllibJsonHttpClient


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


def test_json_http_client_returns_valid_payload_with_bounded_get() -> None:
    calls: list[tuple[str, str, float]] = []

    def opener(request: Request, *, timeout: float) -> FakeResponse:
        calls.append((request.full_url, request.get_method(), timeout))
        return FakeResponse(b'{"models": [{"name": "nomic-embed-text:latest"}]}')

    result = UrllibJsonHttpClient(open_fn=opener).get(
        "http://127.0.0.1:11434/api/tags",
        timeout_seconds=2,
    )

    assert result.state is HttpState.OK
    assert result.status_code == 200
    assert result.payload == {"models": [{"name": "nomic-embed-text:latest"}]}
    assert calls == [("http://127.0.0.1:11434/api/tags", "GET", 2)]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (URLError(ConnectionRefusedError("private endpoint")), HttpState.UNREACHABLE),
        (TimeoutError("private timeout"), HttpState.TIMEOUT),
        (URLError(TimeoutError("wrapped private timeout")), HttpState.TIMEOUT),
    ],
)
def test_json_http_client_categorizes_network_failures_without_leaking(
    error: BaseException,
    expected: HttpState,
) -> None:
    def opener(request: Request, *, timeout: float) -> FakeResponse:
        del request, timeout
        raise error

    result = UrllibJsonHttpClient(open_fn=opener).get(
        "http://127.0.0.1:6333/healthz",
        timeout_seconds=2,
    )

    assert result.state is expected
    assert result.status_code is None
    assert "private" not in repr(result)


def test_json_http_client_categorizes_http_error() -> None:
    def opener(request: Request, *, timeout: float) -> FakeResponse:
        del timeout
        raise HTTPError(
            request.full_url,
            503,
            "private reason",
            Message(),
            io.BytesIO(b"secret"),
        )

    result = UrllibJsonHttpClient(open_fn=opener).get(
        "http://127.0.0.1:6333/healthz",
        timeout_seconds=2,
    )

    assert result.state is HttpState.HTTP_ERROR
    assert result.status_code == 503
    assert result.payload is None
    assert "secret" not in repr(result)


def test_json_http_client_rejects_invalid_json_without_leaking_body() -> None:
    client = UrllibJsonHttpClient(open_fn=lambda request, timeout: FakeResponse(b"secret-body"))

    result = client.get("http://127.0.0.1:6333/healthz", timeout_seconds=2)

    assert result.state is HttpState.INVALID_JSON
    assert result.status_code == 200
    assert result.payload is None
    assert "secret-body" not in repr(result)


def test_json_http_client_rejects_responses_larger_than_one_mebibyte() -> None:
    oversized = b"x" * (1_048_576 + 1)

    def open_fn(request: Request, *, timeout: float) -> FakeResponse:
        del request, timeout
        return FakeResponse(oversized)

    result = UrllibJsonHttpClient(open_fn=open_fn).get(
        "http://127.0.0.1:11434/api/tags",
        timeout_seconds=2,
    )

    assert result.state is HttpState.TOO_LARGE
    assert result.status_code == 200
    assert result.payload is None
