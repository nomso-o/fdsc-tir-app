from typing import Any, Dict, Optional


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "bad_request",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}

    def to_detail(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "message": self.message,
            "code": self.code,
        }
        if self.details:
            payload["details"] = self.details
        return payload
