from pydantic import BaseModel
from typing import Optional

class MalumotnomaSchema(BaseModel):
    id: int
    name: str
    designation: str
    pdf_uz: Optional[str] = None
    pdf_ru: Optional[str] = None

    class Config:
        from_attributes = True 