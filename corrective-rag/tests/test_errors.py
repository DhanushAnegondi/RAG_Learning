"""classify() on the exception shapes the providers actually produce."""

import httpx
import pytest
import requests
from pydantic import BaseModel, ValidationError

from crag.errors import ParseError, PermanentError, TransientError, classify, status_of


class Schema(BaseModel):
    relevant: bool


def _validation_error():
    try:
        Schema.model_validate({"relevant": "not-a-bool-at-all"})
    except ValidationError as e:
        return e


@pytest.mark.parametrize(
    "exc, expected",
    [
        # langchain-nvidia-ai-endpoints raises a bare Exception with "[status] title"
        (Exception("[429] Too Many Requests\nrate limit"), TransientError),
        (Exception("[500] Internal Server Error"), TransientError),
        (Exception("[503] Service Unavailable"), TransientError),
        (Exception("[401] Unauthorized\nInvalid key"), PermanentError),
        (Exception("[400] Bad Request"), PermanentError),
        (Exception("[403] Forbidden"), PermanentError),
        (Exception("[404] Not Found\nmodel x"), PermanentError),
        (TimeoutError("timed out"), TransientError),
        (ConnectionError("reset"), TransientError),
        (requests.exceptions.ConnectTimeout("t"), TransientError),
        (requests.exceptions.ConnectionError("c"), TransientError),
        (httpx.ReadTimeout("slow"), TransientError),
        (httpx.ConnectError("nope"), TransientError),
        (_validation_error(), ParseError),
        (ValueError("could not parse JSON"), ParseError),
        (RuntimeError("something unknown"), TransientError),
    ],
)
def test_classify(exc, expected):
    assert classify(exc) is expected


def test_classify_http_error_with_response_status():
    resp = requests.Response()
    resp.status_code = 429
    assert classify(requests.HTTPError("boom", response=resp)) is TransientError
    resp.status_code = 401
    assert classify(requests.HTTPError("boom", response=resp)) is PermanentError


def test_httpx_status_error():
    req = httpx.Request("POST", "https://x")
    exc = httpx.HTTPStatusError("bad", request=req, response=httpx.Response(502, request=req))
    assert status_of(exc) == 502 and classify(exc) is TransientError


def test_404_is_model_specific():
    assert PermanentError("x", status=404).model_specific
    assert not PermanentError("x", status=401).model_specific


def test_already_classified_passthrough():
    assert classify(ParseError("x")) is ParseError


def test_status_out_of_range_ignored():
    assert status_of(Exception("[999] weird")) is None
    assert status_of(Exception("[099] weird")) is None
