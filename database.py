# database.py
import os
from sqlalchemy import create_engine, text
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

def ensure_sqlite_column(engine, table_name: str, column_name: str, column_type_sql: str = "TEXT") -> None:
    """
    Nếu đang dùng SQLite và bảng `table_name` chưa có cột `column_name`,
    thì tự động ALTER TABLE để thêm cột đó.

    - column_type_sql: để "TEXT" cho các trường JSON khi lưu trên SQLite.
    - Không set DEFAULT/NOT NULL để tránh hạn chế ALTER TABLE của SQLite.
    """
    # Chỉ xử lý với SQLite
    if not str(engine.url).startswith("sqlite"):
        return

    try:
        from sqlalchemy import text  # import cục bộ để hàm tự chứa
        with engine.connect() as conn:
            # Liệt kê các cột đang có
            cols = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            existing = {row[1] for row in cols}  # row[1] là tên cột
            if column_name not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type_sql}"))
                print(f"[DB MIGRATION] + Added column {table_name}.{column_name} ({column_type_sql})")
            else:
                print(f"[DB MIGRATION] = Column {table_name}.{column_name} already exists")
    except Exception as e:
        print(f"[DB MIGRATION] ! Failed to ensure column {table_name}.{column_name}: {e}")
