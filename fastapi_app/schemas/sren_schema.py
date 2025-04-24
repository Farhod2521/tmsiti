from pydantic import BaseModel
from typing import List

class SREN_SHNKSchema(BaseModel):
    sren_shnk_uz: str
    sren_shnk_ru: str
    sren_designation: str

    class Config:
        orm_mode = True

class SRENSchema(BaseModel):
    sren_name_uz: str
    sren_name_ru: str
    sren_designation: str
    sren_shnk: List[SREN_SHNKSchema] = []

    class Config:
        orm_mode = True
