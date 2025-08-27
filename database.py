# database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Tải các biến môi trường từ file .env (nếu có, dùng cho local dev)
load_dotenv()

# Lấy chuỗi kết nối từ biến môi trường "DATABASE_URL"
# Nếu không có, sẽ dùng CSDL SQLite mặc định cho môi trường phát triển
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Nếu dùng PostgreSQL trên Render, chuỗi kết nối sẽ bắt đầu bằng "postgresql://"
# SQLAlchemy sẽ tự động xử lý pool kết nối
engine_args = {"connect_args": {}}
if DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()