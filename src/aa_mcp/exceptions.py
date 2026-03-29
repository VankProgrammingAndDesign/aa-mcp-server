class AuthenticationError(Exception):
    """Raised when authentication fails or a refreshed token is rejected."""


class ControlRoomError(Exception):
    """Raised when the Control Room API returns a 4xx or 5xx response."""

    def __init__(self, status_code: int, message: str, response_body: str = "") -> None:
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"HTTP {status_code}: {message}")


class NetworkError(Exception):
    """Raised when a connection or timeout error prevents reaching the Control Room."""
