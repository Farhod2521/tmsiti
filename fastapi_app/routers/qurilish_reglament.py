from fastapi_app.schemas.qurilish_reglament_schema import QurilishReglamentSchema
from typing import Dict, List
from fastapi import APIRouter, Depends
from database import get_db
from models import QurilishReglament
router = APIRouter(prefix="/reglament", tags=["QM"])


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import Depends
from database import get_db

@router.get("/qurilish/", response_model=List[QurilishReglamentSchema])
async def get_qurilish(session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(QurilishReglament))
    return result.scalars().all()
