"""
The one exception type for a problem the operator can fix.

Anything raised as ConfigurationError is reported as its own message and
nothing else: no traceback, no exception class name. The message has to name
the thing that is wrong and the next action, because it is the whole of what
the reader gets.
"""


class ConfigurationError(Exception):
    """A missing or wrong setting, stated as what to do about it."""
