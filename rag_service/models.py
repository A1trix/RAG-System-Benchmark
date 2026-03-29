from typing import Any, List, Optional

from pydantic import BaseModel, Field


class RAGDecision(BaseModel):
    """Structured output for RAG single-call agent decision."""
    needs_retrieval: bool = Field(description="Whether document retrieval is needed")
    retrieval_query: Optional[str] = Field(default=None, description="Optimized search query if retrieval needed")
    direct_answer: Optional[str] = Field(default=None, description="Direct answer if no retrieval needed")
    confidence: float = Field(ge=0, le=1, description="Confidence in the decision")


class IngestRequest(BaseModel):
    file_id: str
    title: Optional[str] = None
    url: Optional[str] = None
    type: Optional[str] = Field(default=None, description="mime or short type e.g. pdf,csv,docx,text")
    content: Optional[str] = Field(default=None, description="inline text content")
    path: Optional[str] = Field(default=None, description="server-side path if file already present")
    doc_schema: Optional[List[str]] = Field(default=None, alias="schema")
    rows: Optional[List[dict[str, Any]]] = None


class IngestResponse(BaseModel):
    status: str
    file_id: str
    job_id: Optional[str] = None


class DeleteRequest(BaseModel):
    file_id: str


class DeleteResponse(BaseModel):
    status: str
    file_id: str
    job_id: Optional[str] = None


class QueryRequest(BaseModel):
    chatInput: str
    sessionId: Optional[str] = None
    top_k: Optional[int] = None
    prompt_id: Optional[str] = None
    request_meta: Optional[dict[str, Any]] = None
    request_id: Optional[str] = None
    enqueued_at: Optional[str] = None
    queue_wait_ms: Optional[int] = None
    stream: Optional[bool] = Field(default=False, description="Enable SSE streaming for reduced TTFB")


class ContextChunk(BaseModel):
    file_id: str
    title: Optional[str]
    text: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    # Token usage metrics for correlation analysis (per-successful-request)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
