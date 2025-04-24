from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from models import SREN, SREN_SHNK  # SQLAlchemy models
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema

async def get_all_sren(db: AsyncSession) -> List[SRENSchema]:
    sren_list = []

    # Use select() instead of query() for AsyncSession
    result = await db.execute(select(SREN))
    sren_records = result.scalars().all()

    for sren in sren_records:
        # Use select() for related SREN_SHNK records
        shnk_result = await db.execute(select(SREN_SHNK).filter(SREN_SHNK.sren_id == sren.id))
        shnk_records = shnk_result.scalars().all()

        # Create a list of SREN_SHNKSchema
        shnk_list = [
            SREN_SHNKSchema(
                sren_shnk_uz=shnk.name,
                sren_shnk_ru=shnk.name,
                sren_designation=shnk.designation
            ) for shnk in shnk_records
        ]

        # Create the SRENSchema instance for the SREN
        sren_schema = SRENSchema(
            sren_name_uz=sren.name,
            sren_name_ru=sren.name,
            sren_designation=sren.designation,
            sren_shnk=shnk_list
        )
        sren_list.append(sren_schema)

    return sren_list
