# Calibre-Web Open Library author provider

A drop-in replacement for Calibre-Web's `cps/services/goodreads_support.py` that fetches author biographies and photos from Open Library without a Goodreads API key. It preserves the functions Calibre-Web calls: `connect(key=None, enabled=True)`, `get_author_info(author_name)`, and `get_other_books(author_info, library_books=None)`.

`get_author_info` returns an object with the author-page fields Calibre-Web currently reads: `name`, `image_url`, `safe_about`, and `link`. The object also keeps compatibility fields `about`, `books`, `gid`, `birth_date`, `death_date`, and `_timestamp`. `get_other_books` returns an empty list, so the Open Library author provider does not populate Calibre-Web's Goodreads-specific “More by” section.

## Matching and data

The provider requests Open Library author search results, keeps records whose primary or alternate name exactly matches the requested author after Unicode normalization and case folding, and selects the matching result with the highest `work_count`. Similar-name hits are excluded. A tie for the highest count, or no exact name match, returns `None`. This handles Liu Cixin, whose record is named `刘慈欣`; the search for “Liu Cixin” returns three results, and the correct record (`OL7044246A`) has the highest work count (123). Biographies are escaped as text because Calibre-Web renders `safe_about` as trusted HTML. Photo URLs use Open Library's author covers endpoint when the record has a photo ID.

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

The default test suite mocks Open Library responses and verifies the compatibility surface, exact primary/alternate-name filtering with highest-work-count selection, Liu Cixin's alternate-name result, failure behavior, and empty “More by” results without network access.

To query the 20-author library list live and print a Markdown table with the selected record, dates, biography, and photo check, run:

```sh
RUN_LIVE_AUTHOR_LOOKUP=1 uv run pytest -m live -s
```

The live test is skipped by default so normal test runs remain offline. Lookups without a selected record appear as `No result / API error` for review.
