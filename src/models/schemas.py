from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn người dùng")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Phản hồi an toàn")
    emergency: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
