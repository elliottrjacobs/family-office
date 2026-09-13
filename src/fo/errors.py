class OfficeError(Exception):
    """A safe, public error; never construct its message from a provider payload."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(message)
