#!/usr/bin/env python3

import asyncio

from aiohttp import web

import healthbot.checks.pings as pings


async def _serve_and_ping(monkeypatch, statuses: dict, extra_ping_urls: list):
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

    config = {"base_url": base_url, "ping_urls": extra_ping_urls}
    monkeypatch.setattr(pings, "get_config", lambda name: config if name == "site.yml" else {})
    monkeypatch.setattr(pings, "get_cookies", lambda *a, **k: {})
    monkeypatch.setattr(pings, "get_headers", lambda *a, **k: {})

    try:
        return base_url, await pings.work()
    finally:
        await runner.cleanup()


def test_work_returns_url_status_pairs(monkeypatch):
    base_url, results = asyncio.run(
        _serve_and_ping(
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
    assert pings.all_ok([status for _, status in results]) is False


def test_an_unreachable_url_folds_in_instead_of_aborting(monkeypatch):
    # "missing" has no route -> 404; port 1 refuses -> UNREACHABLE. Neither
    # may abort the run.
    base_url, results = asyncio.run(_serve_and_ping(monkeypatch, {"/": 200}, ["missing"]))
    statuses = dict(results)
    assert statuses[base_url] == 200
    assert statuses[f"{base_url}missing"] == 404

    config = {"base_url": "http://127.0.0.1:1/", "ping_urls": []}
    monkeypatch.setattr(pings, "get_config", lambda name: config if name == "site.yml" else {})
    results = asyncio.run(pings.work())
    assert results == [("http://127.0.0.1:1/", pings.UNREACHABLE)]
