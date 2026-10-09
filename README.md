# Calibre-Web Open Library author provider

A drop-in replacement for Calibre-Web's `cps/services/goodreads_support.py` that fetches author biographies and photos from Open Library without a Goodreads API key. It preserves the functions Calibre-Web calls: `connect(key=None, enabled=True)`, `get_author_info(author_name)`, and `get_other_books(author_info, library_books=None)`.

`get_author_info` returns an object with the author-page fields Calibre-Web currently reads: `name`, `image_url`, `safe_about`, and `link`. The object also keeps compatibility fields `about`, `books`, `gid`, and `_timestamp`. `get_other_books` returns an empty list, so the Open Library author provider does not populate Calibre-Web's Goodreads-specific “More by” section.

## Matching and data

The provider requests Open Library author search results and accepts only one exact match after Unicode normalization and case folding. Missing and ambiguous matches return `None`; it does not choose the first search result. Liu Cixin uses the Open Library ID supplied for this library (`OL7044246A`), where the record is listed under the Chinese name. Biographies are escaped as text because Calibre-Web renders `safe_about` as trusted HTML. Photo URLs use Open Library's author covers endpoint when the record has a photo ID.

Requests identify this provider with a User-Agent, are throttled to at most one per second per Python process, have a timeout, and are cached in memory for 23 hours. A request/API failure returns `None` and is logged.

## Drop-in use

Replace the deployed Calibre-Web file `cps/services/goodreads_support.py` with `src/calibre_web_overrides/goodreads_support.py`. Calibre-Web must have `requests` installed (it is one of Calibre-Web's existing runtime dependencies). The module always enables Open Library lookups: `connect` accepts the legacy `key` and `enabled` parameters but ignores both. Calibre-Web’s existing web handler separately checks `config_use_goodreads` before it calls any author provider, so that application setting must still be on for author pages to request profile data.

This repository only provides the replacement Python module. It does not modify a Docker image or mount configuration.

## Development

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
```

Tests mock Open Library responses and verify the compatibility surface, exact-match safety, Liu Cixin's supplied record ID, failure behavior, and empty “More by” results without depending on live network availability.
