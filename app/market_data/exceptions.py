"""Storage-layer exceptions for market data infrastructure."""


class StorageError(Exception):
    """Base exception for market data storage operations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(StorageError):
    """Raised when OHLCV data fails validation before persistence."""

    def __init__(self, message: str, *, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


class RepositoryError(StorageError):
    """Raised when a repository read/write/delete operation fails."""

    pass


class ProviderError(StorageError):
    """Raised when the external market data provider fails."""

    pass
