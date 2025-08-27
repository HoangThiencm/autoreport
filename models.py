# models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Date
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from database import Base

class SchoolYear(Base):
    __tablename__ = "school_years"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    is_active = Column(Boolean, default=True)
    drive_folder_id = Column(String, unique=True, nullable=True)

def generate_uuid():
    return str(uuid.uuid4())

class School(Base):
    __tablename__ = "schools"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    api_key = Column(String, unique=True, index=True, default=generate_uuid)
    
    file_submissions = relationship("FileSubmission", back_populates="school", cascade="all, delete-orphan")
    data_entries = relationship("DataEntry", back_populates="school", cascade="all, delete-orphan")

class FileTask(Base):
    __tablename__ = "file_tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    content = Column(String)
    deadline = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_notification_sent = Column(Boolean, default=False)
    
    school_year_id = Column(Integer, ForeignKey("school_years.id"))
    school_year = relationship("SchoolYear")
    
    submissions = relationship("FileSubmission", back_populates="task")

class FileSubmission(Base):
    __tablename__ = "file_submissions"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("file_tasks.id"))
    school_id = Column(Integer, ForeignKey("schools.id"))
    file_url = Column(String, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    
    task = relationship("FileTask", back_populates="submissions")
    school = relationship("School", back_populates="file_submissions")

class DataReport(Base):
    __tablename__ = "data_reports"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    deadline = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    template_url = Column(String, nullable=False)
    # THÊM MỚI: Cột để theo dõi việc gửi email thông báo
    is_notification_sent = Column(Boolean, default=False)
    
    school_year_id = Column(Integer, ForeignKey("school_years.id"))
    school_year = relationship("SchoolYear")
    
    entries = relationship("DataEntry", back_populates="report")

class DataEntry(Base):
    __tablename__ = "data_entries"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("data_reports.id"))
    school_id = Column(Integer, ForeignKey("schools.id"))
    
    sheet_url = Column(String, nullable=False)
    submitted_at = Column(DateTime, nullable=True) 
    
    report = relationship("DataReport", back_populates="entries")
    school = relationship("School", back_populates="data_entries")
