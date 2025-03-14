from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from services.subsystem_service import get_subsystems, filter_subsystems_by_title
from schemas.subsystem_schema import SubsystemResponse
from typing import Dict, List
router = APIRouter(prefix="/subsystems", tags=["Subsystems"])

@router.get("/", response_model=List[SubsystemResponse])
async def read_subsystems(db: AsyncSession = Depends(get_db)):
    return await get_subsystems(db)

@router.get("/filter/", response_model=List[SubsystemResponse])
async def filter_subsystems(title: str, db: AsyncSession = Depends(get_db)):
    return await filter_subsystems_by_title(db, title)
