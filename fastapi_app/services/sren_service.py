from typing import List
from sqlalchemy.orm import Session
from fastapi import Depends
from models import SREN, SREN_SHNK  # SQLAlchemy models
from schemas.sren_schema import SRENSchema, SREN_SHNKSchema
from database import get_db  # Dependency to get DB session

def get_all_sren(db: Session) -> List[SRENSchema]:
    sren_list = []
    # Querying all SREN records
    sren_records = db.query(SREN).all()

    for sren in sren_records:
        # Querying related SREN_SHNK records
        shnk_list = [
            SREN_SHNKSchema(
                sren_shnk_uz=shnk.name,
                sren_shnk_ru=shnk.name,
                sren_designation=shnk.designation
            ) for shnk in db.query(SREN_SHNK).filter(SREN_SHNK.sren_id == sren.id).all()
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
