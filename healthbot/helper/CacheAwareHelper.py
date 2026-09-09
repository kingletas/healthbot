#!/usr/bin/env python3

# Standard imports
import json
import re
from datetime import timedelta
from hashlib import sha256

# Third party imports
import redis

# Local imports
from healthbot import __app_name__


class CacheAwareHelper:
    def __init__(self, host="localhost", port=6379, db=0, duration=60) -> None:
        self.cache = redis.Redis(host=host, port=port, db=db)
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

        key = self.prepare_key(key)
        value = json.dumps(value, indent=2).encode("utf-8")

        return self.cache.setex(key, timedelta(minutes=duration), bytes(value))

    def get(self, key):
        key = self.prepare_key(key)
        value = self.cache.get(key)
        if value is not None:
            value = json.loads(value)
        return value

    def delete(self, key):
        return self.remove(key)

    def remove(self, key):
        key = self.prepare_key(key)
        self.cache.delete("list", key)

        return self.cache.delete(key)

    def flushall(self):
        return self.cache.flushall()

    def flush(self):
        return self.cache.flushdb()
