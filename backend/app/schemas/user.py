import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    full_name: str


class UserCreate(UserBase):
    password: str
    role: Literal["ADMIN", "ATTORNEY"] = "ATTORNEY"
    max_open_cases: int = 20


class UserRead(UserBase):
    id: uuid.UUID
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    role: str
    max_open_cases: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    email: EmailStr
    password: str
