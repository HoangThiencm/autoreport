# main.py
import io
import zipfile
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

# --- BẮT ĐẦU PHẦN CẬP NHẬT SCHEDULER ---
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
# --- KẾT THÚC PHẦN CẬP NHẬT SCHEDULER ---

import models, schemas, crud
from database import engine, SessionLocal
from scheduler import check_deadlines_and_send_email

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Hệ thống Báo cáo Tự động",
    description="API Backend cho hệ thống quản lý và theo dõi báo cáo."
)

# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_school_from_api_key(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    db_school = crud.get_school_by_api_key(db, api_key=x_api_key)
    if db_school is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key không hợp lệ.")
    return db_school

# --- Scheduler (ĐÃ CẬP NHẬT CẤU HÌNH) ---
executors = {
    'default': ThreadPoolExecutor(1)  # Chỉ cần 1 luồng cho tác vụ đơn giản này
}
scheduler = BackgroundScheduler(executors=executors, timezone="Asia/Ho_Chi_Minh")

@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(
        check_deadlines_and_send_email,
        'interval',
        seconds=30,
        id="deadline_check_job",
        replace_existing=True,
        misfire_grace_time=60  # Cho phép trễ 60 giây nếu server bị treo tạm thời
    )
    scheduler.start()
    print("Đã khởi động bộ đếm giờ (Scheduler) với cấu hình mới.")


@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()
    print("Đã tắt bộ đếm giờ (Scheduler).")

# --- Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Auto Report API is running correctly."}

# --- Endpoints cho SchoolYear và School ---
@app.post("/school_years/", response_model=schemas.SchoolYear)
def create_new_school_year(school_year: schemas.SchoolYearCreate, db: Session = Depends(get_db)):
    db_school_year = crud.create_school_year(db=db, school_year=school_year)
    if db_school_year is None:
        raise HTTPException(status_code=500, detail="Không thể tạo thư mục trên Google Drive. Vui lòng kiểm tra lại cấu hình Service Account và quyền chia sẻ thư mục.")
    return db_school_year

@app.get("/school_years/", response_model=List[schemas.SchoolYear])
def read_school_years(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_school_years(db, skip=skip, limit=limit)

@app.post("/schools/", response_model=schemas.School)
def create_new_school(school: schemas.SchoolCreate, db: Session = Depends(get_db)):
    db_school = crud.create_school(db=db, school=school)
    if db_school is None:
        raise HTTPException(status_code=400, detail="Không thể tạo trường. Tên trường có thể đã tồn tại.")
    return db_school

@app.get("/schools/", response_model=List[schemas.School])
def read_schools(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_schools(db, skip=skip, limit=limit)

@app.get("/schools/me", response_model=schemas.School)
def read_school_me(current_school: models.School = Depends(get_school_from_api_key)):
    return current_school

@app.delete("/schools/{school_id}")
def delete_school_by_id(school_id: int, db: Session = Depends(get_db)):
    deleted_school = crud.delete_school(db, school_id=school_id)
    if not deleted_school:
        raise HTTPException(status_code=404, detail="Trường không tồn tại.")
    return {"message": "Đã xóa trường thành công."}

# --- Endpoints cho Báo cáo Nộp File ---
@app.post("/file-tasks/", response_model=schemas.FileTask)
def create_new_file_task(task: schemas.FileTaskCreate, db: Session = Depends(get_db)):
    return crud.create_file_task(db=db, task=task)

@app.get("/file-tasks/{task_id}/upload-folder")
def get_upload_folder_for_task(
    task_id: int, 
    db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    folder_id = crud.get_or_create_file_submission_folder(db, task_id=task_id, school_id=current_school.id)
    if not folder_id:
        raise HTTPException(status_code=404, detail="Không thể tìm hoặc tạo thư mục nộp bài. Vui lòng kiểm tra lại thông tin Năm học của yêu cầu này.")
    return {"folder_id": folder_id}

@app.get("/file-tasks/", response_model=List[schemas.FileTask])
def read_file_tasks(
    school_year_id: Optional[int] = None, skip: int = 0, limit: int = 100, 
    db: Session = Depends(get_db), x_api_key: Optional[str] = Header(None) 
):
    current_school_id = None
    if x_api_key:
        current_school = crud.get_school_by_api_key(db, api_key=x_api_key)
        if not current_school:
            raise HTTPException(status_code=401, detail="API Key không hợp lệ.")
        current_school_id = current_school.id

    tasks_from_db, reminded_task_ids = crud.get_file_tasks(db, school_year_id=school_year_id, current_school_id=current_school_id, skip=skip, limit=limit)
    response_tasks = []
    
    submitted_task_ids = set()
    if current_school_id:
        submitted_task_ids = crud.get_submitted_file_task_ids_for_school(db, school_id=current_school_id)
    
    for task in tasks_from_db:
        task_schema = schemas.FileTask.from_orm(task)
        task_schema.is_submitted = task.id in submitted_task_ids
        task_schema.is_reminded = task.id in reminded_task_ids
        response_tasks.append(task_schema)
    return response_tasks

@app.get("/file-tasks/{task_id}/status", response_model=schemas.FileTaskStatus)
def read_file_task_status(task_id: int, db: Session = Depends(get_db)):
    status_data = crud.get_file_task_status(db, task_id=task_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail="Yêu cầu nộp file không tồn tại.")
    return status_data

@app.get("/file-tasks/{task_id}/download-all")
def download_all_submissions_for_task(task_id: int, db: Session = Depends(get_db)):
    submissions = crud.get_submissions_for_file_task(db, task_id=task_id)
    if not submissions:
        raise HTTPException(status_code=404, detail="Không có file nào được nộp.")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for submission in submissions:
            file_id = crud.extract_drive_file_id_from_url(submission.file_url)
            if not file_id: continue
            file_content, file_name = crud.download_file_from_drive(file_id)
            if file_content and file_name:
                zip_file_name = f"{submission.school.name} - {file_name}"
                zip_file.writestr(zip_file_name, file_content)
    zip_buffer.seek(0)
    return StreamingResponse(zip_buffer, media_type="application/zip", 
                             headers={"Content-Disposition": f"attachment; filename=task_{task_id}_submissions.zip"})

@app.post("/file-submissions/", response_model=schemas.FileSubmission)
def create_new_file_submission(
    submission: schemas.FileSubmissionCreate, db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    return crud.create_file_submission(db=db, submission=submission, school_id=current_school.id)

@app.post("/data-reports/", response_model=schemas.DataReport)
def create_new_data_report(report: schemas.DataReportCreate, db: Session = Depends(get_db)):
    db_report, error_message = crud.create_data_report(db=db, report=report)
    if error_message:
        raise HTTPException(status_code=400, detail=error_message)
    return db_report

@app.get("/data-reports/", response_model=List[schemas.DataReport])
def read_data_reports(
    school_year_id: Optional[int] = None, skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db), x_api_key: Optional[str] = Header(None)
):
    current_school_id = None
    if x_api_key:
        current_school = crud.get_school_by_api_key(db, api_key=x_api_key)
        if not current_school:
            raise HTTPException(status_code=401, detail="API Key không hợp lệ.")
        current_school_id = current_school.id

    reports_from_db, reminded_report_ids = crud.get_data_reports(db, school_year_id=school_year_id, current_school_id=current_school_id, skip=skip, limit=limit)
    response_reports = []

    for report in reports_from_db:
        report_schema = schemas.DataReport.from_orm(report)
        report_schema.is_reminded = report.id in reminded_report_ids
        if current_school_id:
            entry = crud.get_data_entry_for_school(db, report_id=report.id, school_id=current_school_id)
            if entry:
                report_schema.sheet_url = entry.sheet_url
                report_schema.is_submitted = entry.submitted_at is not None
        response_reports.append(report_schema)
        
    return response_reports

@app.get("/data-reports/{report_id}/status", response_model=schemas.DataReportStatus)
def read_data_report_status(report_id: int, db: Session = Depends(get_db)):
    status_data = crud.get_data_report_status(db, report_id=report_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail="Báo cáo nhập liệu không tồn tại.")
    return status_data

@app.post("/data-reports/{report_id}/complete", status_code=status.HTTP_200_OK)
def mark_report_as_complete(
    report_id: int, db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    entry = crud.mark_data_report_as_complete(db, report_id=report_id, school_id=current_school.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo hoặc đã được xác nhận trước đó.")
    return {"message": "Đã đánh dấu báo cáo là hoàn thành."}

@app.post("/admin/remind/{task_type}/{task_id}", status_code=status.HTTP_200_OK)
def send_reminders(task_type: str, task_id: int, db: Session = Depends(get_db)):
    if task_type not in ["file", "data"]:
        raise HTTPException(status_code=400, detail="Loại công việc không hợp lệ. Chỉ chấp nhận 'file' hoặc 'data'.")
    
    success, message = crud.create_reminders_for_task(db, task_type, task_id)
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
        
    return {"message": message}

class ResetPayload(BaseModel):
    password: str

RESET_PASSWORD = "admin" 

@app.post("/admin/reset-database", status_code=status.HTTP_200_OK)
def handle_reset_database(payload: ResetPayload, db: Session = Depends(get_db)):
    if payload.password != RESET_PASSWORD:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Mật khẩu không chính xác.")
    
    success, message = crud.reset_database(db)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)
        
    return {"message": message}