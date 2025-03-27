from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from database import get_db
from models import Malumotnoma
from schemas.malumot_schema import MalumotnomaSchema

router = APIRouter(prefix="/malumotnoma", tags=["Malumotnoma"])

@router.get("/", response_model=List[MalumotnomaSchema])
async def get_malumotlar(session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(Malumotnoma))
    return result.scalars().all()