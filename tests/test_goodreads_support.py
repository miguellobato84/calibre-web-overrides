"""Contract and matching tests for the drop-in author provider."""

from __future__ import annotations

import requests

from calibre_web_overrides import goodreads_support as provider


def setup_function() -> None:
    provider.connect(enabled=True)
    provider._cache.clear()
    provider._last_request_at = 0.0


def response(payload: dict) -> requests.Response:
    result = requests.Response()
    result.status_code = 200
    result._content = __import__("json").dumps(payload).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def test_public_interface_is_calibre_web_compatible() -> None:
    assert callable(provider.connect)
    assert callable(provider.get_author_info)
    assert callable(provider.get_other_books)
    provider.connect(key=None, enabled=True)
    assert provider.get_other_books(None) == []


def test_unique_exact_match_returns_template_fields(monkeypatch) -> None:
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/search/authors.json"):
            return response({"docs": [{"key": "/authors/OL123A", "name": "Isaac Asimov"}]})
        return response({
            "name": "Isaac Asimov",
            "bio": {"value": "A <script>alert('x')</script> biography."},
            "photos": [456],
            "birth_date": "1920-01-02",
        })

    monkeypatch.setattr(provider.requests, "get", fake_get)
    author = provider.get_author_info("Isaac Asimov")

    assert author is not None
    assert author.name == "Isaac Asimov"
    assert author.link == "https://openlibrary.org/authors/OL123A"
    assert author.gid == "OL123A"
    assert author.image_url == "https://covers.openlibrary.org/a/id/456-M.jpg?default=false"
    assert author.safe_about == "A &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; biography."
    assert author.books == []
    assert calls[0][1]["headers"]["User-Agent"].startswith("CalibreWebOpenLibraryAuthorProvider/")
    assert calls[0][1]["timeout"] > 0


def test_ambiguous_and_missing_exact_matches_return_none(monkeypatch) -> None:
    monkeypatch.setattr(provider, "_get_json", lambda path, params=None: {
        "docs": [
            {"key": "/authors/OL10A", "name": "Same Name"},
            {"key": "/authors/OL11A", "name": "Same Name"},
            {"key": "/authors/OL12A", "name": "Same Name Jr."},
        ]
    })
    assert provider.get_author_info("Same Name") is None

    monkeypatch.setattr(provider, "_get_json", lambda path, params=None: {"docs": [
        {"key": "/authors/OL12A", "name": "Similar Name"},
    ]})
    assert provider.get_author_info("Same Name") is None


def test_liu_cixin_uses_owner_supplied_record_id(monkeypatch) -> None:
    paths = []

    def fake_get_json(path, params=None):
        paths.append(path)
        return {"name": "刘慈欣", "bio": "Chinese science fiction writer", "photos": []}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    author = provider.get_author_info("Liu Cixin")
    assert paths == ["/authors/OL7044246A.json"]
    assert author is not None
    assert author.name == "Liu Cixin"
    assert author.link == "https://openlibrary.org/authors/OL7044246A"
    assert author.image_url is None


def test_provider_ignores_legacy_key_and_enabled_arguments(monkeypatch) -> None:
    def fake_get_json(path, params=None):
        if path.startswith("/search/"):
            return {"docs": [{"key": "/authors/OL123A", "name": "Isaac Asimov"}]}
        return {"name": "Isaac Asimov"}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    provider.connect(key=None, enabled=False)
    author = provider.get_author_info("Isaac Asimov")
    assert author is not None
    assert author.name == "Isaac Asimov"


def test_request_errors_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(provider, "_get_json", lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("offline")))
    assert provider.get_author_info("Isaac Asimov") is None


def test_profile_without_bio_or_photo_still_has_compatible_fields(monkeypatch) -> None:
    def fake_get_json(path, params=None):
        if path.startswith("/search/"):
            return {"docs": [{"key": "/authors/OL123A", "name": "No Media Author"}]}
        return {"name": "No Media Author"}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    author = provider.get_author_info("No Media Author")
    assert author is not None
    assert author.image_url is None
    assert author.safe_about is None
    assert author.about is None
