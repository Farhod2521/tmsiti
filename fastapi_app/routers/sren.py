from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db  # Dependency to get DB session
from  services.sren_service import get_all_sren
router = APIRouter()

@router.get("/sren")
async def list_sren(db: AsyncSession = Depends(get_db)):
    return await get_all_sren(db)