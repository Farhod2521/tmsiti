from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
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
    shnks = relationship(
        "Shnk",
        back_populates="shnkgroup",
        order_by="Shnk.order"   # ✅ FAQAT SHNK ORDER
    )

class Shnk(Base):
    __tablename__ = "shnks"

    id = Column(Integer, primary_key=True, index=True)
    name_uz = Column(String(500), nullable=False)
    name_ru = Column(String(500), nullable=False)
    designation = Column(String(255), nullable=True)
    pdf_uz = Column(String(255), nullable=True)  
    pdf_ru = Column(String(255), nullable=True) 
    url = Column(String(500), nullable=False)
    order = Column(Integer, default=0, index=True)
    status = Column(Boolean, default=True, nullable=False, index=True)  # 🔥 MUHIM
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



class Malumotnoma(Base):
    __tablename__ = "Malumotnoma"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False)
    designation = Column(String(100), nullable=False)
    pdf_uz = Column(String, nullable=True)  # Fayl URL sifatida saqlanadi
    pdf_ru = Column(String, nullable=True)


class SREN(Base):
    __tablename__ = "sren"

    id = Column(Integer, primary_key=True, index=True)
    name_uz = Column(String(500), index=True)
    name_ru = Column(String(500), index=True)
    designation = Column(String(100), index=True)
    pdf_uz = Column(String, nullable=True)  # PDF fayl nomi yoki yo'li
    pdf_ru = Column(String, nullable=True)  # PDF fayl nomi yoki yo'li
    order = Column(Integer, index=True)
    sren_shnk = relationship("SREN_SHNK", back_populates="sren", cascade="all, delete-orphan")

class SREN_SHNK(Base):
    __tablename__ = "sren_shnk"

    id = Column(Integer, primary_key=True, index=True)
    sren_id = Column(Integer, ForeignKey("sren.id"))
    name_uz = Column(String(500), index=True)
    name_ru = Column(String(500), index=True)
    pdf_uz = Column(String, nullable=True)  # PDF fayl nomi yoki yo'li
    pdf_ru = Column(String, nullable=True)  # PDF fayl nomi yoki yo'li
    designation = Column(String(100), index=True)

    sren = relationship("SREN", back_populates="sren_shnk")