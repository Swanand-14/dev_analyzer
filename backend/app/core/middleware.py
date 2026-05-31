from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
 
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
]
 
 
def add_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
        ],
    )
 