#!/usr/bin/env python3


class NotificationMessage:
    def __iter__(self):
        yield self.__dict__
