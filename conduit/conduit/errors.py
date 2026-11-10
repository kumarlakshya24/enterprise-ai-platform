"""Errors the API turns into HTTP status codes."""


class ConduitError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class RedactorError(ConduitError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status=503)


class EmbedderError(ConduitError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status=503)
