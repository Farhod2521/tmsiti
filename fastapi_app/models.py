from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Subsystem(Base):
    __tablename__ = "subsystems"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), index=True)

    groups = relationship("ShnkGroup", back_populates="subsystem")

class ShnkGroup(Base):
    __tablename__ = "shnk_groups"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), index=True)
    subsystem_id = Column(Integer, ForeignKey("subsystems.id"), index=True)

    subsystem = relationship("Subsystem", back_populates="groups")
    shnks = relationship("Shnk", back_populates="shnkgroup")  

class Shnk(Base):
    __tablename__ = "shnks"

    id = Column(Integer, primary_key=True, index=True)
    name_uz = Column(String(500), nullable=False)
    name_ru = Column(String(500), nullable=False)
    designation = Column(String(255), nullable=True)
    pdf_uz = Column(String(255), nullable=True)  
    pdf_ru = Column(String(255), nullable=True) 
    url = Column(String(500), nullable=False)

    shnkgroup_id = Column(Integer, ForeignKey("shnk_groups.id"), nullable=False)

    # ShnkGroup bilan bog‘lanish
    shnkgroup = relationship("ShnkGroup", back_populates="shnks")



class QurilishReglament(Base):
    __tablename__ = "qurilish_reglaament"

    id = Column(Integer, primary_key=True, index=True)
    group = Column(String(500), nullable=False)
    name = Column(String(500), nullable=False, index=True)
    designation = Column(String(100), nullable=False, index=True)
    pdf_uz = Column(String(500), nullable=True)
    pdf_ru = Column(String(500), nullable=True)