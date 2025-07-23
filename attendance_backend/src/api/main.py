from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.models import Base

import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite:///./attendance.db"
)  # Default local SQLite file

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

app = FastAPI(
    title="Employee Attendance Tracker Backend",
    description="FastAPI backend with SQLite and role-based attendance management",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
# PUBLIC_INTERFACE
def on_startup():
    """
    Database initialization logic. Ensures all tables are created for a clean schema.
    """
    Base.metadata.create_all(bind=engine)

@app.get("/", tags=["Health"])
def health_check():
    """
    Health check endpoint.
    """
    return {"message": "Healthy"}
