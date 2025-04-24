from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import SREN, SREN_SHNK  # SQLAlchemy models
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema

# Async function to get all SREN records
async def get_all_sren(db: AsyncSession) -> List[SRENSchema]:
    sren_list = []
    # Querying all SREN records asynchronously
    result = await db.execute(select(SREN))
    sren_records = result.scalars().all()

    for sren in sren_records:
        # Querying related SREN_SHNK records asynchronously
        shnk_result = await db.execute(
            select(SREN_SHNK).filter(SREN_SHNK.sren_id == sren.id)
        )
        shnk_records = shnk_result.scalars().all()

        shnk_list = [
            SREN_SHNKSchema(
                sren_shnk_uz=shnk.name,
                sren_shnk_ru=shnk.name,
                sren_designation=shnk.designation
            ) for shnk in shnk_records
        ]
        
        # Creating SRENSchema instance
        sren_schema = SRENSchema(
            sren_name_uz=sren.name,
            sren_name_ru=sren.name,
            sren_designation=sren.designation,
            sren_shnk=shnk_list
        )
        sren_list.append(sren_schema)
    
    return sren_list
