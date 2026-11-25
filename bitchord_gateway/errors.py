"""소스 호출 실패와 요청 옵션 오류를 통일된 예외로 정의한다."""

from __future__ import annotations


class SourceError(Exception):
    """어댑터가 던지는 유일한 예외. 오케스트레이터는 이것만 보고 재시도/폴백을 결정한다."""

    # kind: timeout | network | http_error | rate_limited | parse | not_configured | internal
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


class PlanError(ValueError):
    """클라이언트 요청 옵션 또는 서명 토큰이 잘못된 경우 (HTTP 400으로 변환)."""
