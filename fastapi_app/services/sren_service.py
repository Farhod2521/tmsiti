from typing import List
from models import SREN, SREN_SHNK  # Django modeli ishlatilmoqda
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema

def get_all_sren() -> List[SRENSchema]:
    sren_list = []
    for sren in SREN.objects.all():
        shnk_list = SREN_SHNKSchema.from_orm_list(
            [
                SREN_SHNKSchema(
                    sren_shnk_uz=shnk.name,
                    sren_shnk_ru=shnk.name,
                    sren_designation=shnk.designation
                ) for shnk in SREN_SHNK.objects.filter(sren=sren)
            ]
        )
        sren_schema = SRENSchema(
            sren_name_uz=sren.name,
            sren_name_ru=sren.name,
            sren_designation=sren.designation,
            sren_shnk=shnk_list
        )
        sren_list.append(sren_schema)
    return sren_list
