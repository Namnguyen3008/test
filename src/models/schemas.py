from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn người dùng")
    history: list[ChatMessage] = Field(default_factory=list, description="Lịch sử hội thoại")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Phản hồi an toàn")
    emergency: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
