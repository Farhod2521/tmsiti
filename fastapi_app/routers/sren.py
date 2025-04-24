from fastapi import APIRouter
from services.sren_service import get_all_sren
from schemas.sren_schema import SRENSchema
from typing import List

router = APIRouter(
    prefix="/sren",
    tags=["SREN"]
)

@router.get("/", response_model=List[SRENSchema])
def list_sren():
    return get_all_sren()
