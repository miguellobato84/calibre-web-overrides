"""Opt-in live lookup and Markdown report for the library's author list."""

from __future__ import annotations

import os

import pytest

from calibre_web_overrides.goodreads_support import connect, get_author_info

AUTHORS = (
    "Fernando Aramburu",
    "Isaac Asimov",
    "Agustina María Bazterrica",
    "Roberto Bolaño",
    "Ray Bradbury",
    "Pierce Brown",
    "Liu Cixin",
    "Blake Crouch",
    "Joan Didion",
    "Matt Dinniman",
    "Elena Ferrante",
    "Jacqueline Harpman",
    "Frank Herbert",
    "Kazuo Ishiguro",
    "Hilary Mantel",
    "Cormac McCarthy",
    "Haruki Murakami",
    "Gabriel García Márquez",
    "Brandon Sanderson",
    "Andy Weir",
)


def _cell(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).replace("|", "\\|")


@pytest.mark.live
def test_query_all_library_authors_and_print_markdown_table() -> None:
    if os.environ.get("RUN_LIVE_AUTHOR_LOOKUP") != "1":
        pytest.skip("set RUN_LIVE_AUTHOR_LOOKUP=1 to query Open Library")

    connect()
    rows = []
    for name in AUTHORS:
        author = get_author_info(name)
        if author is None:
            rows.append((name, "No result / API error", "", "", "", "", "No"))
            continue
        rows.append((
            name,
            "Found",
            f"[{author.gid}]({author.link})" if author.gid else "",
            author.birth_date or "",
            author.death_date or "",
            _cell(author.about),
            "Yes" if author.image_url else "No",
        ))

    headers = ("Requested author", "Status", "Open Library record", "Born", "Died", "Biography", "Photo?")
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print("| " + " | ".join(_cell(value) for value in row) + " |")

    assert len(rows) == len(AUTHORS)
