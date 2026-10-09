import uuid

from pydantic import BaseModel


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    tenant_id: uuid.UUID
    tenant_name: str
