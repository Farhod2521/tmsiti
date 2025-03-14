from fastapi import FastAPI
from routers import subsystem, shnk, shnkgroup

app = FastAPI(title="FastAPI SHNK API", version="1.0")

app.include_router(subsystem.router)
app.include_router(shnk.router)
#app.include_router(shnkgroup.router)

@app.get("/")
def root():
    return {"message": "Welcome to SHNK API"}
