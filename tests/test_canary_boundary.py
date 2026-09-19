#!/usr/bin/env python3

import asyncio

import pytest
from aiohttp import web

import healthbot.checks.canary as canary
from healthbot.errors import ConfigurationError


async def _serve_and_sweep(monkeypatch, statuses: dict, extra_canary_urls: list):
    """
    A real aiohttp server on a random local port. No mocking library, the
    actual client stack end to end.
    """
    app = web.Application()
    for route, status in statuses.items():

        def handler(request, status=status):
            return web.Response(status=status)

        app.router.add_get(route, handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}/"

    config = {"base_url": base_url, "canary_urls": extra_canary_urls}
    monkeypatch.setattr(canary, "get_config", lambda name: config if name == "site.yml" else {})
    monkeypatch.setattr(canary, "get_cookies", lambda *a, **k: {})
    monkeypatch.setattr(canary, "get_headers", lambda *a, **k: {})

    try:
        return base_url, await canary.work()
    finally:
        await runner.cleanup()


def test_work_returns_url_status_pairs(monkeypatch):
    base_url, results = asyncio.run(
        _serve_and_sweep(
            monkeypatch,
            {"/": 200, "/checkout": 200, "/cart": 503},
            ["checkout", "cart"],
        )
    )
    assert dict(results) == {
        base_url: 200,
        f"{base_url}checkout": 200,
        f"{base_url}cart": 503,
    }
    assert canary.all_ok([status for _, status in results]) is False


def test_an_unreachable_url_folds_in_instead_of_aborting(monkeypatch):
    # "missing" has no route -> 404; port 1 refuses -> UNREACHABLE. Neither
    # may abort the run.
    base_url, results = asyncio.run(_serve_and_sweep(monkeypatch, {"/": 200}, ["missing"]))
    statuses = dict(results)
    assert statuses[base_url] == 200
    assert statuses[f"{base_url}missing"] == 404

    config = {"base_url": "http://127.0.0.1:1/", "canary_urls": []}
    monkeypatch.setattr(canary, "get_config", lambda name: config if name == "site.yml" else {})
    results = asyncio.run(canary.work())
    assert results == [("http://127.0.0.1:1/", canary.UNREACHABLE)]


def test_a_base_url_without_a_trailing_slash_still_reaches_the_paths(monkeypatch):
    # Without the slash the sweep asked for https://store.example.comcheckout,
    # which answers nothing and pages.
    config = {"base_url": "http://127.0.0.1:1", "canary_urls": ["checkout"]}
    monkeypatch.setattr(canary, "get_config", lambda name: config if name == "site.yml" else {})
    monkeypatch.setattr(canary, "get_cookies", lambda *a, **k: {})
    monkeypatch.setattr(canary, "get_headers", lambda *a, **k: {})

    urls = [url for url, _ in asyncio.run(canary.work())]

    assert urls == ["http://127.0.0.1:1/", "http://127.0.0.1:1/checkout"]


def test_a_missing_canary_urls_says_what_to_add(monkeypatch):
    monkeypatch.setattr(canary, "get_config", lambda name: {"base_url": "http://127.0.0.1:1/"})
    monkeypatch.setattr(canary, "get_cookies", lambda *a, **k: {})
    monkeypatch.setattr(canary, "get_headers", lambda *a, **k: {})

    with pytest.raises(ConfigurationError) as err:
        asyncio.run(canary.work())

    assert "canary_urls" in str(err.value)
