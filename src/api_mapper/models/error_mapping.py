from dataclasses import dataclass


@dataclass(frozen=True)
class UpstreamError:
    code: str
    http_status: str
    message: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownstreamError:
    api: str
    endpoint: str
    http_status: str
    code: str | None
    message: str


@dataclass(frozen=True)
class ErrorMapping:
    downstream: DownstreamError
    upstream_status: str
    upstream_code: str | None
    rule: str
    confidence: float
