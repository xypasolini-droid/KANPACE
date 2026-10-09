"""Stable errors shared by application services and transport adapters."""


class APIError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details
