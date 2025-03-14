from pydantic import BaseModel
from typing import Optional
class ShnkResponse(BaseModel):
    id: int
    name_uz: Optional[str]   # Default qiymat qo‘shish
    name_ru: Optional[str]   # Default qiymat qo‘shish
    designation: Optional[str] = None
    pdf_uz: Optional[str] = None
    pdf_ru: Optional[str] = None
    url: Optional[str] = None
    pages: list
    @classmethod
    def from_orm(cls, obj):
        return cls(
            id=obj.id,
            name=obj.name or "No Title",  # Shu usul orqali `None` muammosini oldini olamiz
            designation=obj.designation,
            file_url_uz=obj.pdf_uz,
            file_url_ru=obj.pdf_ru,
            url = obj.url
     
        )
    class Config:
        orm_mode = True