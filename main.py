import re
from math import ceil
from fastapi import FastAPI, Request, Form, HTTPException, status, UploadFile, File, Response, Depends
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
MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI chưa được thiết lập!")

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

# ─── Danh sách cố định các Quận/Huyện Hà Nội ────────────────────────────────
district_map = {
    "dong_da": "Quận Đống Đa",
    "hai_ba_trung": "Quận Hai Bà Trưng",
    "cau_giay": "Quận Cầu Giấy",
    "tay_ho": "Quận Tây Hồ",
    "thanh_xuan": "Quận Thanh Xuân",
    "ha_dong": "Quận Hà Đông",
    "hoang_mai": "Quận Hoàng Mai",
    "bac_tu_liem": "Quận Bắc Từ Liêm",
    "nam_tu_liem": "Quận Nam Từ Liêm",
    "ba_dinh": "Quận Ba Đình",
    "hoan_kiem": "Quận Hoàn Kiếm",
    "long_bien": "Quận Long Biên",
}
# Chuyển sang list để duyệt theo thứ tự cố định
district_options: List[Tuple[str, str]] = list(district_map.items())

# ─── Danh sách cố định các LOẠI phòng ──────────────────────────────────────
type_map = {
    "phong_tro": "Phòng trọ",
    "nha_nguyen_can": "Nhà nguyên căn",
    "chung_cu": "Chung cư",
    "biet_thu": "Biệt thự",
}
type_options: List[Tuple[str, str]] = list(type_map.items())

# -------------- SMTP CẤU HÌNH --------------
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


async def send_reset_email(request: Request, to_email: str, token: str):
    """
    Gửi thư đổi mật khẩu, link sẽ là:
      {base_url}/account/reset-password/{token}
    Có hiệu lực 1 giờ.
    """
    base = str(request.base_url).rstrip("/")
    path = request.url_for("reset_password_page", token=token)
    reset_link = f"{base}{path}"

    msg = EmailMessage()
    msg["Subject"] = "QLPT: Đặt lại mật khẩu"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.set_content(f"""Xin chào,

Bạn (hoặc ai đó) đã yêu cầu đặt lại mật khẩu cho tài khoản QLPT của bạn.
Vui lòng nhấp vào đường link bên dưới để đặt lại mật khẩu (hiệu lực 1 giờ):

{reset_link}

Nếu bạn không yêu cầu, vui lòng bỏ qua email này.

Trân trọng,
Đội ngũ QLPT
""")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


async def get_db():
    """
    Mỗi lần có request, ta khởi tạo một client mới trên event‐loop hiện tại,
    và đóng nó khi xong request.
    """
    client = AsyncIOMotorClient(
        MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where(),
    )
    try:
        yield client["hotel_database"]
    finally:
        client.close()


@app.get("/", tags=["listing"])
async def root(
    request: Request,
    page: int = 1,
    district: str | None = None,
    price: str | None = None,
    type: str | None = None,
    db=Depends(get_db),  # <-- inject db ở đây
):
    page_size = 6

    # 1) Build filter
    filt: dict = {}
    if district:
        # Dùng regex để so khớp case‐insensitive
        filt["district"] = re.compile(
            f"^{re.escape(district)}$", re.IGNORECASE)
    if type:
        filt["type"] = type

    price_map = {
        "0-2000000": (0, 2_000_000),
        "2000000-5000000": (2_000_000, 5_000_000),
        "5000000-10000000": (5_000_000, 10_000_000),
        "10000000-": (10_000_000, None),
    }
    if price and price in price_map:
        low, high = price_map[price]
        cond: dict = {}
        if low is not None:
            cond["$gte"] = low
        if high is not None:
            cond["$lte"] = high
        filt["price"] = cond

    # 2) Count & pagination
    total = await db.listings.count_documents(filt)
    pages = ceil(total / page_size) if total else 1
    page = max(1, min(page, pages))

    # 3) Query this page
    cursor = db.listings.find(filt).sort("created_at", -1)
    docs = await cursor.skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    # 4) Render
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "listings": docs,
            "page": page,
            "pages": pages,
            "district": district or "",
            "price": price or "",
            "type": type or "",
            "districts": district_options,
        }
    )

    # return templates.TemplateResponse("test_dumb_index.html", {"request": request})
