from schemas.qurilish_reglament import QurilishReglamentSchema
from typing import Dict, List
from fastapi import APIRouter, Depends

from models import QurilishReglament
router = APIRouter(prefix="/reglament", tags=["QM"])


@router.get("/qurilish/", response_model=List[QurilishReglamentSchema])
async def get_qurilish():
    return await QurilishReglament.all()