import fitz  # PyMuPDF
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Shnk

import re
async def get_shnks_by_group(db: AsyncSession, group_id: int):
    result = await db.execute(select(Shnk).filter(Shnk.shnkgroup_id == group_id))
    return result.scalars().all()

import os
import difflib
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Asosiy loyiha papkasi
PDF_DIR = r"D:\FASTAPI\tmsiti\media" # PDF fayllar joylashgan papka
from sqlalchemy.orm import selectinload
async def search_in_shnk_pdf(db: AsyncSession, search_text: str):
    result = await db.execute(
        select(Shnk)
        .options(selectinload(Shnk.shnkgroup))
        .order_by(Shnk.shnkgroup_id, Shnk.order)  # 🔥 MUHIM
    )
    shnks = result.scalars().all()
    
    search_text = search_text.lower()  # Qidirilayotgan matnni kichik harfga o'tkazamiz
    matched_shnks = []

    for shnk in shnks:
        if not shnk.pdf:
            print(f"⚠️ PDF maydoni bo‘sh (ID {shnk.id})")
            continue  

        pdf_path = os.path.join(PDF_DIR, shnk.pdf)
        if not os.path.exists(pdf_path):
            print(f"❌ PDF fayli topilmadi yoki yo‘q: {pdf_path}")
            continue

        try:
            with fitz.open(pdf_path) as pdf:
                pages_with_text = []

                for page_num in range(len(pdf)):
                    page_text = pdf[page_num].get_text("text").replace("\n", " ").strip().lower()

                    # O'zgartirilgan qidiruv: aniq qidiruv + o'xshash so'zlarni topish
                    if search_text in page_text or difflib.get_close_matches(search_text, page_text.split(), n=1, cutoff=0.7):
                        pages_with_text.append(page_num + 1)


                if pages_with_text:
                    matched_shnks.append({
                        "id": shnk.id,
                        "name": shnk.name,
                        "designation": shnk.designation,
                        "pdf": shnk.pdf,
                        "pages": pages_with_text
                    })

        except Exception as e:
            print(f"❌ PDF-ni o‘qishda xatolik (ID {shnk.id}): {e}")

    return matched_shnks