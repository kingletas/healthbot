#!/usr/bin/env python3

"""
The Redis-backed cache, which is a cache and never a dependency.

Every reader here has a source of truth behind it — a packaged YAML file,
Parameter Store, the EC2 API — so a Redis that is down or slow costs a
round trip and nothing else. It used to cost the run: the client carried no
timeout, so a hung Redis hung a five-minute batch job that already sets
REQUEST_TIMEOUT_SECONDS precisely so a hung origin cannot stack runs.
"""

# Standard imports
import json
import re
from datetime import timedelta
from hashlib import sha256

# Third party imports
import redis

# Local imports
from healthbot import __app_name__
from healthbot.api.logs import logger

# Long enough for a loaded local Redis, short enough that five of them cannot
# outlast the timer's own interval.
CONNECT_TIMEOUT_SECONDS: float = 2.0
OPERATION_TIMEOUT_SECONDS: float = 3.0


class CacheAwareHelper:
    def __init__(
        self,
        host="localhost",
        port=6379,
        db=0,
        duration=60,
        socket_timeout: float = OPERATION_TIMEOUT_SECONDS,
        socket_connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        self.cache = redis.Redis(
            host=host,
            port=port,
            db=db,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
        )
        self.prefix = __app_name__
        self.write_permissions = "wb"
        self.read_permissions = "r"
        self.duration = duration

    def save(self, key, value):
        return self.set(key, value)

    def prepare_key(self, key) -> str:
        key = re.sub("[^0-9a-zA-Z]+", "_", key).encode("utf-8")
        key = self.prefix + "_" + sha256(key).hexdigest()
        return key.lower()

    def set(self, key, value, duration: int = 0):

        if duration == 0:
            duration = self.duration

        prepared = self.prepare_key(key)
        value = json.dumps(value, indent=2).encode("utf-8")

        try:
            return self.cache.setex(prepared, timedelta(minutes=duration), bytes(value))
        except redis.RedisError as err:
            # Failing to cache is not failing. The next reader pays for a
            # fetch it would otherwise have skipped.
            logger.warning(f"cache write failed for {key!r}, continuing uncached: {err!r}")
            return None

    def get(self, key):
        prepared = self.prepare_key(key)
        try:
            value = self.cache.get(prepared)
        except redis.RedisError as err:
            # A miss, not an error: every caller has a source of truth to
            # fall back to, and taking the run down would be worse than slow.
            logger.warning(f"cache read failed for {key!r}, treating as a miss: {err!r}")
            return None

        if value is not None:
            value = json.loads(value)
        return value

    def delete(self, key):
        return self.remove(key)

    def remove(self, key):
        prepared = self.prepare_key(key)
        try:
            self.cache.delete("list", prepared)
            return self.cache.delete(prepared)
        except redis.RedisError as err:
            logger.warning(f"cache delete failed for {key!r}: {err!r}")
            return None

    def flushall(self):
        return self.cache.flushall()

    def flush(self):
        return self.cache.flushdb()
