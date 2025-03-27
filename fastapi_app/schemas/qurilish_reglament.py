from pydantic import BaseModel
from typing import List, Optional, Dict



class QurilishReglamentSchema(BaseModel):
    id: int
    group: str
    name: str
    designation: str
    pdf_uz: Optional[str]
    pdf_ru: Optional[str]

    class Config:
        from_attributes = True