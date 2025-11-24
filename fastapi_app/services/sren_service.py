from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from models import SREN, SREN_SHNK  # SQLAlchemy models
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema


async def get_all_sren(db: AsyncSession) -> List[SRENSchema]:
    sren_list = []

    # ✅ order bo‘yicha tartib
    result = await db.execute(select(SREN).order_by(SREN.order.asc()))
    sren_records = result.scalars().all()

    for sren in sren_records:
        shnk_result = await db.execute(
            select(SREN_SHNK).filter(SREN_SHNK.sren_id == sren.id)
        )
        shnk_records = shnk_result.scalars().all()

        shnk_list = [
            SREN_SHNKSchema(
                sren_shnk_uz=shnk.name_uz,
                sren_shnk_ru=shnk.name_ru,
                sren_designation=shnk.designation
            ) for shnk in shnk_records
        ]

        sren_schema = SRENSchema(
            sren_name_uz=sren.name_uz,
            sren_name_ru=sren.name_ru,
            sren_pdf_uz=sren.pdf_uz,
            sren_pdf_ru=sren.pdf_ru,
            sren_designation=sren.designation,
            order=sren.order,  # ✅ Tartib raqami API’da chiqadi
            sren_shnk=shnk_list
        )
        sren_list.append(sren_schema)

    return sren_list