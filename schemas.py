from pydantic import BaseModel
from datetime import datetime, date
from typing import List, Optional

# --- SchoolYear & School Schemas ---
class SchoolYearUpdate(BaseModel):
    name: str

class SchoolYearBase(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class SchoolYearCreate(SchoolYearBase):
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

class FileTaskCreate(BaseModel):
    title: str
    content: str
    deadline: datetime
    school_year_id: int

class FileTask(BaseModel):
    id: int
    title: str
    content: str
    deadline: datetime
    created_at: datetime
    is_submitted: bool = False 
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

# --- DataReport & DataEntry Schemas ---
class DataReportCreate(BaseModel):
    title: str
    deadline: datetime
    school_year_id: int
    template_url: str

class DataReport(BaseModel):
    id: int
    title: str
    deadline: datetime
    created_at: datetime
    is_submitted: bool = False
    sheet_url: Optional[str] = None
    class Config:
        from_attributes = True

class DataEntrySchoolInfo(BaseModel):
    id: int
    name: str
    submitted_at: datetime

class DataReportStatus(BaseModel):
    report: DataReport
    submitted_schools: List[DataEntrySchoolInfo]
    not_submitted_schools: List[School]
    class Config:
        from_attributes = True
