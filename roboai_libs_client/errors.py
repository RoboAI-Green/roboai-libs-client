class RoboAILIBSClientError(Exception):
    """Base exception for client-side errors."""


class RoboAILIBSAPIError(RoboAILIBSClientError):
    """Raised when the RoboAI LIBS API returns an error response."""

    def __init__(self, status_code: int, message: str, *, response_text: str | None = None):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(f"RoboAI LIBS API error {status_code}: {message}")
