from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = "mysql+aiomysql://tmsiti_user:tmsiti_1234@localhost/tmsiti"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()  # <-- Bu qatorni qo‘shing

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
