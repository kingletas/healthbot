#!/usr/bin/env python3

import pytest

from healthbot.checks.site import validate_checkout


@pytest.fixture(scope="module")
def browser_available():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception:
        pytest.skip("playwright chromium not installed, run: playwright install chromium")


def test_a_page_without_the_storefront_fails_and_leaves_evidence(tmp_path, browser_available):
    # A real headless browser against a page that is not the storefront: the
    # journey must fail cleanly (no exception escaping, no None) and leave
    # the debugging evidence behind.
    page = tmp_path / "not-the-shop.html"
    page.write_text("<html><body><h1>definitely not a storefront</h1></body></html>")

    result = validate_checkout(base_url=page.as_uri(), evidence_dir=str(tmp_path))

    assert result is False
    saved = {p.suffix for p in tmp_path.iterdir() if p.name.startswith("checkout-")}
    assert {".png", ".html", ".zip"} <= saved


def test_an_unreachable_site_is_down_not_an_exception(tmp_path, browser_available):
    result = validate_checkout(base_url="http://127.0.0.1:1/", evidence_dir=str(tmp_path))
    assert result is False
