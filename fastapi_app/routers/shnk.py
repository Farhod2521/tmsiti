from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from services.shnk_service import get_shnks_by_group, search_in_shnk_pdf
from schemas.shnk_schema import ShnkResponse

router = APIRouter(prefix="/shnks", tags=["SHNK"])

@router.get("/{group_id}", response_model=list[ShnkResponse])
async def get_shnks(group_id: int, db: AsyncSession = Depends(get_db)):
    return await get_shnks_by_group(db, group_id)

@router.get("/search/", response_model=list[ShnkResponse])
async def search_shnk_pdf(search_text: str, db: AsyncSession = Depends(get_db)):
    return await search_in_shnk_pdf(db, search_text)
