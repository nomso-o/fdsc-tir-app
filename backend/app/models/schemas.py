from typing import List, Optional, Any
from pydantic import BaseModel


class Citation(BaseModel):
    source_id: Optional[str] = None
    page: Optional[int] = None
    blob_uri: Optional[str] = None
    snippet: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    fdsc_index_name: str


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]


class TIRScoreRequest(BaseModel):
    session_id: str
    fdsc_index_name: str
    dataset_prefix: str


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
    session_id: str
    tir_id: str
    edited_markdown: str
