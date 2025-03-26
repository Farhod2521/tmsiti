from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import subsystem, shnk, shnkgroup

app = FastAPI(title="FastAPI SHNK API", version="1.0")

# CORS middleware qo'shish
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Barcha domenlarga ruxsat
    allow_credentials=True,
    allow_methods=["*"],  # Barcha HTTP metodlarga ruxsat
    allow_headers=["*"],  # Barcha HTTP headerlarga ruxsat
)

app.include_router(subsystem.router)
app.include_router(shnk.router)
# app.include_router(shnkgroup.router)

@app.get("/")
def root():
    return {"message": "Welcome to SHNK API"}
