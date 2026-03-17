import re
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DATASET_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,128}$")
_DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_TIR_BLOB_PATH_PATTERN = re.compile(r"^[A-Za-z0-9/._ -]{1,256}$")


def _validate_session_id(value: str) -> str:
    if not _SESSION_ID_PATTERN.fullmatch(value):
        raise ValueError("session_id contains invalid characters.")
    return value


def _validate_prefix(value: str) -> str:
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


def _validate_doc_id(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if not _DOC_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} contains invalid characters.")
    return value


def _validate_tir_blob_path(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    cleaned = value.strip("/")
    if not cleaned:
        raise ValueError("tir_blob_path cannot be empty.")
    if value.startswith("/"):
        raise ValueError("tir_blob_path cannot be absolute.")
    segments = cleaned.split("/")
    if any(seg in {"", ".", ".."} for seg in segments):
        raise ValueError("tir_blob_path cannot contain traversal segments.")
    if not _TIR_BLOB_PATH_PATTERN.fullmatch(cleaned):
        raise ValueError("tir_blob_path contains invalid characters.")
    return cleaned


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


class FDSCDocument(BaseModel):
    id: str
    index_name: str
    doc_id: str = Field(..., max_length=128)
    doc_namespace: str = Field(default="default", max_length=64)
    source_file: Optional[str] = None
    blob_uri: Optional[str] = None
    chunk_count: int = Field(default=0, ge=0)
    semantic_chunking: bool = False
    ingestion_status: Literal["processing", "indexed", "failed"] = "indexed"
    updated_at: Optional[str] = None

    @field_validator("doc_id")
    @classmethod
    def _validate_doc(cls, value: str) -> str:
        checked = _validate_doc_id(value, "doc_id")
        if checked is None:
            raise ValueError("doc_id is required.")
        return checked

    @field_validator("doc_namespace")
    @classmethod
    def _validate_namespace(cls, value: str) -> str:
        if not _NAMESPACE_PATTERN.fullmatch(value):
            raise ValueError("doc_namespace contains invalid characters.")
        return value

    @model_validator(mode="after")
    def _validate_id(self) -> "FDSCDocument":
        expected = f"{self.index_name}::{self.doc_id}"
        if self.id != expected:
            raise ValueError(f"id must be '{expected}'.")
        return self


class TIR(BaseModel):
    tir_id: str
    tir_blob_path: str = Field(..., max_length=256)
    dataset_prefix: str = Field(..., max_length=128)

    @field_validator("dataset_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        return _validate_prefix(value)

    @field_validator("tir_blob_path")
    @classmethod
    def _path(cls, value: str) -> str:
        checked = _validate_tir_blob_path(value)
        if checked is None:
            raise ValueError("tir_blob_path is required.")
        return checked

    @model_validator(mode="after")
    def _path_in_prefix(self) -> "TIR":
        if not self.tir_blob_path.startswith(f"{self.dataset_prefix}/"):
            raise ValueError("tir_blob_path must be inside dataset_prefix.")
        expected = f"tir::{self.tir_blob_path}"
        if self.tir_id != expected:
            raise ValueError(f"tir_id must be '{expected}'.")
        return self


class ScoreRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    session_token: Optional[str] = Field(default=None, min_length=32, max_length=2048)
    fdsc_index_name: str
    dataset_prefix: str = Field(..., min_length=1, max_length=128)
    fdsc_doc_id: Optional[str] = Field(default=None, max_length=128)
    tir_blob_path: Optional[str] = Field(default=None, max_length=256)

    @field_validator("session_id")
    @classmethod
    def _session(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_session_id(value)

    @field_validator("dataset_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        return _validate_prefix(value)

    @field_validator("fdsc_doc_id")
    @classmethod
    def _doc_id(cls, value: Optional[str]) -> Optional[str]:
        return _validate_doc_id(value, "fdsc_doc_id")

    @field_validator("tir_blob_path")
    @classmethod
    def _path(cls, value: Optional[str]) -> Optional[str]:
        return _validate_tir_blob_path(value)

    @model_validator(mode="after")
    def _ensure_tir_belongs_to_dataset(self) -> "ScoreRequest":
        if self.tir_blob_path and not self.tir_blob_path.startswith(f"{self.dataset_prefix}/"):
            raise ValueError("tir_blob_path must be inside dataset_prefix.")
        return self


TIRScoreRequest = ScoreRequest


class TIRSingleResult(BaseModel):
    tir_id: str
    dataset_prefix: str
    tir_blob_path: str
    rationale: str
    markdown_table: str
    raw_structured: Any
    technical_review: Any
    alignment_review: Any


ScoreResult = TIRSingleResult


class TIRScoreResponse(BaseModel):
    session_id: str
    session_token: str
    results: List[TIRSingleResult]


class SaveEditedRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    session_token: str = Field(..., min_length=32, max_length=2048)
    tir_id: str
    edited_markdown: str

    @field_validator("session_id")
    @classmethod
    def _validate_save_session(cls, value: str) -> str:
        return _validate_session_id(value)
