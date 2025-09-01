# schemas.py
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import List, Optional, Any, Dict

# --- SchoolYear & School Schemas ---
class SchoolYearBase(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class SchoolYearCreate(SchoolYearBase):
    pass

class SchoolYearUpdate(SchoolYearBase):
    pass

class SchoolYear(SchoolYearBase):
    id: int
    is_active: bool
    drive_folder_id: Optional[str] = None
    class Config:
        from_attributes = True

class SchoolCreate(BaseModel):
    name: str

class School(BaseModel):
    id: int
    name: str
    api_key: str
    class Config:
        from_attributes = True

# --- FileTask & FileSubmission Schemas ---
class FileSubmissionBase(BaseModel):
    file_url: str

class FileSubmissionCreate(FileSubmissionBase):
    task_id: int

class FileSubmission(FileSubmissionBase):
    id: int
    school_id: int
    task_id: int
    submitted_at: datetime
    class Config:
        from_attributes = True

class FileTaskBase(BaseModel):
    title: str
    content: str
    deadline: datetime
    school_year_id: int
    attachment_url: Optional[str] = None

class FileTaskCreate(FileTaskBase):
    pass

class FileTaskUpdate(BaseModel): 
    title: Optional[str] = None
    content: Optional[str] = None
    deadline: Optional[datetime] = None
    school_year_id: Optional[int] = None
    is_locked: Optional[bool] = None
    attachment_url: Optional[str] = None

class FileTask(FileTaskBase):
    id: int
    created_at: datetime
    is_locked: bool
    is_submitted: bool = False 
    is_reminded: bool = False
    class Config:
        from_attributes = True

class SubmittedSchoolInfo(BaseModel):
    id: int
    name: str
    file_url: str
    submitted_at: datetime

class FileTaskStatus(BaseModel):
    task: FileTask
    submitted_schools: List[SubmittedSchoolInfo]
    not_submitted_schools: List[School]
    class Config:
        from_attributes = True

# --- DataReport & DataEntry Schemas (MODIFIED) ---

# Schema cho một cột trong bảng
class ColumnDefinition(BaseModel):
    name: str
    title: str
    dtype: str
    required: bool = False
    enum: Optional[List[str]] = None

class DataReportCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: datetime
    school_year_id: int
    columns_schema: List[ColumnDefinition]
    template_data: Optional[List[Dict[str, Any]]] = None
    attachment_url: Optional[str] = None

class DataReport(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    deadline: datetime
    created_at: datetime
    columns_schema: List[ColumnDefinition]
    template_data: Optional[List[Dict[str, Any]]] = None
    attachment_url: Optional[str] = None
    is_locked: bool
    is_submitted: bool = False
    is_reminded: bool = False
    class Config:
        from_attributes = True
       
# Schema để client gửi dữ liệu lên
class DataSubmissionCreate(BaseModel):
    data: List[Dict[str, Any]]

# Schema cho thông tin các trường đã nộp
class DataEntrySchoolInfo(BaseModel):
    id: int
    name: str
    submitted_at: datetime

# Schema cho trang thái tổng quan của báo cáo
class DataReportStatus(BaseModel):
    report: DataReport
    submitted_schools: List[DataEntrySchoolInfo]
    not_submitted_schools: List[School]
    class Config:
        from_attributes = True
        
class DataReportUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    columns_schema: Optional[List[ColumnDefinition]] = None
    template_data: Optional[List[Dict[str, Any]]] = None
    is_locked: Optional[bool] = None
    attachment_url: Optional[str] = None
    
class AdminDataSubmissionUpdate(BaseModel): 
    data: List[Dict[str, Any]]

class DashboardStats(BaseModel):
    overdue_file_tasks: int
    overdue_data_reports: int
    total_schools: int
    active_school_year_name: Optional[str] = "Chưa có"

class SchoolComplianceEntry(BaseModel):
    id: int
    name: str
    # các nhiệm vụ/báo cáo được giao trong kỳ
    assigned_count: int
    # nộp đúng hạn count (submitted_at <= deadline)
    ontime_count: int
    # nộp trễ hạn count (submitted_at > deadline)
    late_count: int
    # không nộp count
    missing_count: int

class ComplianceSummary(BaseModel):
    period_label: str
    kind: str  # "file" | "data" | "both"
    # 3 nhóm theo yêu cầu:
    ontime: List[SchoolComplianceEntry]
    late: List[SchoolComplianceEntry]
    missing: List[SchoolComplianceEntry]