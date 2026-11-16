"""Download and unzip behavior, with a fake HTTP session (no network)."""

import zipfile

import pytest
import requests

from cinebridge.ingest import IngestError, download, extract_movielens


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: bytes = b"",
        length: int | None = None,
        headers: dict | None = None,
    ):
        self.status_code = status
        self._body = body
        n = len(body) if length is None else length
        self.headers = {"Content-Length": str(n)} if headers is None else headers

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self) -> None:
        pass


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_download_writes_file_and_sets_timeout(tmp_path):
    session = FakeSession(FakeResponse(200, b"abcdef"))
    dest = tmp_path / "raw" / "file.bin"
    out = download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert out == dest
    assert dest.read_bytes() == b"abcdef"
    assert session.calls[0]["timeout"] > 0
    assert session.calls[0]["stream"] is True


def test_download_skips_existing_file_without_a_request(tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"already here")
    session = FakeSession()
    download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert session.calls == []
    assert dest.read_bytes() == b"already here"


def test_download_retries_server_error_then_succeeds(tmp_path):
    slept: list[float] = []
    session = FakeSession(FakeResponse(503), FakeResponse(429), FakeResponse(200, b"ok"))
    dest = tmp_path / "file.bin"
    download("https://example.test/f", dest, session=session, sleep=slept.append)
    assert dest.read_bytes() == b"ok"
    assert len(session.calls) == 3
    assert slept == [1.0, 2.0]


def test_download_retries_connection_error(tmp_path):
    session = FakeSession(requests.ConnectionError("reset"), FakeResponse(200, b"ok"))
    dest = tmp_path / "file.bin"
    download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert dest.read_bytes() == b"ok"


def test_download_client_error_fails_fast(tmp_path):
    session = FakeSession(FakeResponse(404), FakeResponse(200, b"never"))
    dest = tmp_path / "file.bin"
    with pytest.raises(IngestError, match="404"):
        download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert len(session.calls) == 1
    assert not dest.exists()


def test_download_truncated_body_is_not_kept(tmp_path):
    cut = FakeResponse(200, b"abc", length=10)
    session = FakeSession(cut, cut, cut)
    dest = tmp_path / "file.bin"
    with pytest.raises(IngestError, match="3 attempts"):
        download("https://example.test/f", dest, session=session, retries=3, sleep=lambda s: None)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_without_a_content_length_header_keeps_the_file(tmp_path):
    session = FakeSession(FakeResponse(200, b"abc", headers={}))
    dest = tmp_path / "file.bin"
    download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert dest.read_bytes() == b"abc"
    assert len(session.calls) == 1


def test_download_of_an_encoded_body_skips_the_length_check(tmp_path):
    """requests decodes gzip, so the bytes written differ from Content-Length (compressed)."""
    resp = FakeResponse(200, b"abcdef", headers={"Content-Length": "3", "Content-Encoding": "gzip"})
    session = FakeSession(resp)
    dest = tmp_path / "file.bin"
    download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert dest.read_bytes() == b"abcdef"
    assert len(session.calls) == 1


def test_download_gives_up_after_the_last_attempt_without_a_final_wait(tmp_path):
    slept: list[float] = []
    session = FakeSession(FakeResponse(503), FakeResponse(503), FakeResponse(503))
    with pytest.raises(IngestError, match="HTTP 503"):
        download(
            "https://example.test/f",
            tmp_path / "file.bin",
            session=session,
            retries=3,
            sleep=slept.append,
        )
    assert slept == [1.0, 2.0]  # waits between attempts only, none after the third
    assert list(tmp_path.iterdir()) == []


def test_download_cut_off_mid_stream_leaves_no_part_file(tmp_path):
    class Drops(FakeResponse):
        def iter_content(self, chunk_size: int):
            yield b"ab"
            raise requests.ConnectionError("reset")

    session = FakeSession(Drops(200, b"abcd"), FakeResponse(200, b"abcd"))
    dest = tmp_path / "file.bin"
    download("https://example.test/f", dest, session=session, sleep=lambda s: None)
    assert dest.read_bytes() == b"abcd"
    assert [p.name for p in tmp_path.iterdir()] == ["file.bin"]


def test_download_cut_off_on_every_attempt_leaves_nothing_behind(tmp_path):
    class Drops(FakeResponse):
        def iter_content(self, chunk_size: int):
            yield b"ab"
            raise requests.ConnectionError("reset")

    session = FakeSession(Drops(200), Drops(200))
    with pytest.raises(IngestError, match="ConnectionError"):
        download(
            "https://example.test/f",
            tmp_path / "file.bin",
            session=session,
            retries=2,
            sleep=lambda s: None,
        )
    assert list(tmp_path.iterdir()) == []


def test_extract_movielens_takes_only_ratings_and_links(tmp_path):
    zpath = tmp_path / "ml.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ml-32m/ratings.csv", "userId,movieId,rating,timestamp\n1,2,4.0,10\n")
        z.writestr("ml-32m/links.csv", "movieId,imdbId,tmdbId\n2,0000002,20\n")
        z.writestr("ml-32m/tags.csv", "x\n")
        z.writestr("../evil/ratings.csv.txt", "x\n")
    out = extract_movielens(zpath, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["links.csv", "ratings.csv"]
    assert out["ratings"].read_text(encoding="utf-8").startswith("userId,movieId")
    assert out["links"].name == "links.csv"


def test_extract_movielens_keeps_the_first_of_a_repeated_member(tmp_path):
    zpath = tmp_path / "ml.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ml-32m/ratings.csv", "FIRST\n")
        z.writestr("other/ratings.csv", "SECOND\n")
        z.writestr("ml-32m/links.csv", "movieId,imdbId,tmdbId\n")
    out = extract_movielens(zpath, tmp_path / "out")
    assert out["ratings"].read_text(encoding="utf-8") == "FIRST\n"


def test_extract_movielens_missing_member_raises(tmp_path):
    zpath = tmp_path / "ml.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ml-32m/ratings.csv", "userId,movieId,rating,timestamp\n")
    with pytest.raises(IngestError, match="links.csv"):
        extract_movielens(zpath, tmp_path / "out")
