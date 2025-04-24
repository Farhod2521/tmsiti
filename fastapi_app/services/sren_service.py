from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from models import SREN, SREN_SHNK  # SQLAlchemy models
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema

async def get_all_sren(db: AsyncSession) -> List[SRENSchema]:
    sren_list = []
    sren_records = await db.execute(db.query(SREN))
    sren_records = sren_records.scalars().all()

    for sren in sren_records:
        shnk_list = [
            SREN_SHNKSchema(
                sren_shnk_uz=shnk.name,
                sren_shnk_ru=shnk.name,
                sren_designation=shnk.designation
            ) for shnk in await db.execute(db.query(SREN_SHNK).filter(SREN_SHNK.sren_id == sren.id)).scalars().all()
        ]
        
        sren_schema = SRENSchema(
            sren_name_uz=sren.name,
            sren_name_ru=sren.name,
            sren_designation=sren.designation,
            sren_shnk=shnk_list
        )
        sren_list.append(sren_schema)

    return sren_list
