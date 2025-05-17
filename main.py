import re
from math import ceil
from fastapi import FastAPI, Request, Form, HTTPException, status, UploadFile, File, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
# from account.routers import account_router
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
import os
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import smtplib
from email.message import EmailMessage
from passlib.context import CryptContext
import certifi
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import uvicorn

load_dotenv()

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="hotel_service")

# Thay bằng serve trực tiếp từ thư mục static/ ở project root
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static",
)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# globals để endpoint sử dụng
SECRET_KEY = os.getenv("SECRET_KEY")
mongo_client: AsyncIOMotorClient | None = None
db = None  # sẽ gán vào startup
MONGODB_URI = os.getenv("MONGODB_URI")


@app.on_event("startup")
def on_startup():
    global mongo_client, db, MONGODB_URI

    # 1) Sync client dùng để "ping" ngay lúc startup
    sync = MongoClient(
        MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5_000,
    )
    sync.admin.command("ping")  # nếu ko connect được sẽ crash ngay

    # 2) Async client khởi tạo trong đúng event‐loop đang mở
    mongo_client = AsyncIOMotorClient(
        MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where(),
    )
    db = mongo_client["hotel_database"]


@app.on_event("shutdown")
def on_shutdown():
    global mongo_client
    if mongo_client:
        mongo_client.close()
        
        
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="session",
    max_age=14 * 24 * 60 * 60,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})




