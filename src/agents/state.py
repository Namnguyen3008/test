from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """State schema cho LangGraph agent.

    Mỗi node đọc và ghi vào state này.
    total=False cho phép tất cả fields là optional.
    """

    query: str
    latest_query: str
    history: list[dict[str, str]]
    context: str
    response: str
    emergency: bool
    retrieval_records: list[dict[str, object]]
    retrieval_mode: str
    allowed_specialty_ids: list[str]
    valid_source_ids: list[str]
    model_output: str
    error: str
    metadata: dict
