from pydantic import BaseModel
from typing import List, Optional

class ShnkSchema(BaseModel):
    name_uz: Optional[str]
    name_ru: Optional[str]
    designation: str
    pdf_uz: Optional[str] = None
    pdf_ru: Optional[str] = None
    url: Optional[str] = None

class ShnkGroupSchema(BaseModel):
    title: str
    documents: List[ShnkSchema]

class SubsystemResponse(BaseModel):
    title: str
    groups: List[ShnkGroupSchema]
