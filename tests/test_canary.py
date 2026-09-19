#!/usr/bin/env python3

import asyncio

from aiohttp import ClientError

from healthbot.checks.canary import UNREACHABLE, all_ok, check_url


def test_all_ok_when_every_url_answers_200():
    assert all_ok([200, 200, 200]) is True


def test_any_non_200_fails():
    assert all_ok([200, 500, 200]) is False
    assert all_ok([200, UNREACHABLE]) is False


def test_empty_result_is_a_failure_not_a_crash():
    # Regression: set(queue).pop() raised KeyError on the all-requests-failed
    # case this check exists for.
    assert all_ok([]) is False


class _RaisingSession:
    def get(self, url):
        raise ClientError("connection refused")


class _TimeoutSession:
    def get(self, url):
        raise TimeoutError("timed out")


def test_unreachable_url_folds_into_the_result():
    # Regression: ClientError (DNS failure, connection refused, the site being
    # down) used to escape and abort the whole run.
    assert asyncio.run(check_url(_RaisingSession(), "https://x")) == UNREACHABLE
    assert asyncio.run(check_url(_TimeoutSession(), "https://x")) == UNREACHABLE
