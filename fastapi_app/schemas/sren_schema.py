from pydantic import BaseModel
from typing import List,Optional

class SREN_SHNKSchema(BaseModel):
    sren_shnk_uz: str
    sren_shnk_ru: str
    sren_designation: str
    sren_pdf_uz: Optional[str] = None
    sren_pdf_ru: Optional[str] = None
    class Config:
        orm_mode = True

class SRENSchema(BaseModel):
    sren_name_uz: str
    sren_name_ru: str
    sren_designation: str
    sren_pdf_uz: Optional[str] = None
    sren_pdf_ru: Optional[str] = None
    order: int  # ✅ Tartib raqami qo‘shildi

    sren_shnk: List[SREN_SHNKSchema] = []

    class Config:
        orm_mode = True