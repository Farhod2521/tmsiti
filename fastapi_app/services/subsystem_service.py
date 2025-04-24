from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Subsystem, ShnkGroup, Shnk
from schemas.subsystem_schema import SubsystemResponse, ShnkGroupSchema, ShnkSchema

async def get_subsystems(db: AsyncSession):
    result = await db.execute(
        select(Subsystem).options(selectinload(Subsystem.groups).selectinload(ShnkGroup.shnks))
    )
    subsystems = result.scalars().all()

    return [
        SubsystemResponse(
            title=subsystem.title,
            groups=[
                ShnkGroupSchema(
                    title=group.title,
                    documents=[
                        ShnkSchema(
                            name_uz=shnk.name_uz,
                            name_ru=shnk.name_ru,
                            designation=shnk.designation,
                            pdf_uz=shnk.pdf_uz,
                            pdf_ru=shnk.pdf_ru,
                            url=shnk.url
                        ) for shnk in group.shnks
                    ]
                ) for group in subsystem.groups
            ]
        ) for subsystem in subsystems
    ]

async def filter_subsystems_by_title(db: AsyncSession, title: str):
    result = await db.execute(
        select(Subsystem).where(Subsystem.title.ilike(f"%{title}%")).options(
            selectinload(Subsystem.groups).selectinload(ShnkGroup.shnks)
        )
    )
    subsystems = result.scalars().all()
    return await get_subsystems(db)
