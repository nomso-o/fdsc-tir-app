import re
from typing import List, Optional, Any
from pydantic import BaseModel, Field, field_validator

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DATASET_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,128}$")


def _validate_session_id(value: str) -> str:
    if not _SESSION_ID_PATTERN.fullmatch(value):
        raise ValueError("session_id contains invalid characters.")
    return value


class Citation(BaseModel):
    source_id: Optional[str] = None
    page: Optional[int] = None
    blob_uri: Optional[str] = None
    snippet: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(..., min_length=1, max_length=64)
    fdsc_index_name: str

    @field_validator("session_id")
    @classmethod
    def _validate_session(cls, value: str) -> str:
        return _validate_session_id(value)


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]


class TIRScoreRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    fdsc_index_name: str
    dataset_prefix: str = Field(..., min_length=1, max_length=128)

    @field_validator("session_id")
    @classmethod
    def _session(cls, value: str) -> str:
        return _validate_session_id(value)

    @field_validator("dataset_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        cleaned = value.strip("/")
        if not cleaned:
            raise ValueError("dataset_prefix cannot be empty.")
        if value.startswith("/"):
            raise ValueError("dataset_prefix cannot be absolute.")
        segments = cleaned.split("/")
        if any(seg in {"", ".", ".."} for seg in segments):
            raise ValueError("dataset_prefix cannot contain traversal segments.")
        if not _DATASET_PREFIX_PATTERN.fullmatch(cleaned):
            raise ValueError("dataset_prefix contains invalid characters.")
        return cleaned


class TIRSingleResult(BaseModel):
    tir_blob_path: str
    rationale: str
    markdown_table: str
    raw_structured: Any
    technical_review: Any
    alignment_review: Any


class TIRScoreResponse(BaseModel):
    session_id: str
    results: List[TIRSingleResult]


class SaveEditedRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    tir_id: str
    edited_markdown: str

    @field_validator("session_id")
    @classmethod
    def _validate_save_session(cls, value: str) -> str:
        return _validate_session_id(value)
