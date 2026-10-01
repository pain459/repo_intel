"""Bounded JSON HTTP probes for local services."""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_MAX_RESPONSE_BYTES = 1_048_576


class HttpState(StrEnum):
    """Transport and decoding outcomes used by diagnostics."""

    OK = "ok"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    TOO_LARGE = "too_large"


@dataclass(frozen=True, slots=True)
class JsonResponse:
    """Sanitized result of a bounded JSON GET request."""

    state: HttpState
    status_code: int | None
    payload: object | None = field(repr=False)


class JsonHttpClient(Protocol):
    def get(self, url: str, *, timeout_seconds: float) -> JsonResponse: ...


class _ResponseStream(Protocol):
    status: int

    def read(self, amount: int) -> bytes: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> object: ...


class _OpenFunction(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> _ResponseStream: ...


class UrllibJsonHttpClient:
    """JSON GET client with fixed memory and disclosure bounds."""

    def __init__(self, *, open_fn: _OpenFunction | None = None) -> None:
        self._open = cast("_OpenFunction", urlopen) if open_fn is None else open_fn

    def get(self, url: str, *, timeout_seconds: float) -> JsonResponse:
        request = Request(url, method="GET")
        try:
            with self._open(request, timeout=timeout_seconds) as response:
                status = response.status
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            return JsonResponse(HttpState.HTTP_ERROR, error.code, None)
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                return JsonResponse(HttpState.TIMEOUT, None, None)
            return JsonResponse(HttpState.UNREACHABLE, None, None)
        except TimeoutError:
            return JsonResponse(HttpState.TIMEOUT, None, None)
        except OSError:
            return JsonResponse(HttpState.UNREACHABLE, None, None)

        if not 200 <= status < 300:
            return JsonResponse(HttpState.HTTP_ERROR, status, None)
        if len(body) > _MAX_RESPONSE_BYTES:
            return JsonResponse(HttpState.TOO_LARGE, status, None)

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse(HttpState.INVALID_JSON, status, None)
        return JsonResponse(HttpState.OK, status, payload)


__all__ = ["HttpState", "JsonHttpClient", "JsonResponse", "UrllibJsonHttpClient"]
