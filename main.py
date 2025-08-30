# main.py
import io
import os
import openpyxl
import zipfile
from typing import List, Optional, Any, Dict

from fastapi import FastAPI, Depends, HTTPException, status, Header, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

import models, schemas, crud
from database import engine, SessionLocal
from scheduler import check_deadlines_and_send_email

models.Base.metadata.create_all(bind=engine)

def _init_sqlite_hotfix_columns():
    """
    HÀM MỚI: Hotfix cho SQLite để đảm bảo các cột mới thêm trong ORM
    sẽ được tự động tạo trong file CSDL nếu chưa có.
    """
    from database import ensure_sqlite_column, engine as _engine
    
    # Bảng file_tasks
    ensure_sqlite_column(_engine, "file_tasks", "is_locked", "BOOLEAN")

    # Bảng data_reports
    ensure_sqlite_column(_engine, "data_reports", "template_data", "TEXT")
    ensure_sqlite_column(_engine, "data_reports", "is_locked", "BOOLEAN")

    # Bảng data_entries
    ensure_sqlite_column(_engine, "data_entries", "last_edited_by", "VARCHAR")
    ensure_sqlite_column(_engine, "data_entries", "last_edited_at", "DATETIME")

# GỌI NGAY khi import xong, trước khi app phục vụ request
_init_sqlite_hotfix_columns()


app = FastAPI(
    title="Hệ thống Báo cáo Tự động",
    description="API Backend cho hệ thống quản lý và theo dõi báo cáo."
)

@app.post("/admin/upload-attachment", response_model=Dict[str, str])
async def upload_attachment(file: UploadFile = File(...)):
    """
    Nhận file từ admin_app, tải lên Google Drive và trả về URL.
    """
    if not file:
        raise HTTPException(status_code=400, detail="Không có file nào được tải lên.")
    
    try:
        file_content = await file.read()
        file_url = crud.upload_attachment_to_drive(file.filename, file_content)
        
        if not file_url:
            raise HTTPException(status_code=500, detail="Không thể tải file lên Google Drive.")
            
        return {"file_url": file_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi server khi xử lý file: {e}")
# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_school_from_api_key(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    """Dependency để xác thực API Key của các trường học (client_app)."""
    db_school = crud.get_school_by_api_key(db, api_key=x_api_key)
    if db_school is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key không hợp lệ.")
    return db_school

# --- Scheduler ---
executors = {'default': ThreadPoolExecutor(1)}
scheduler = BackgroundScheduler(executors=executors, timezone="Asia/Ho_Chi_Minh")

@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(check_deadlines_and_send_email, 'interval', hours=1, id="deadline_check_job", replace_existing=True, misfire_grace_time=60)
    scheduler.start()
    print("Đã khởi động bộ đếm giờ (Scheduler).")

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()
    print("Đã tắt bộ đếm giờ (Scheduler).")

@app.get("/")
def read_root():
    return {"message": "Auto Report API is running correctly."}

# --- SchoolYear Endpoints ---
@app.post("/school_years/", response_model=schemas.SchoolYear)
def create_new_school_year(school_year: schemas.SchoolYearCreate, db: Session = Depends(get_db)):
    db_school_year = crud.create_school_year(db=db, school_year=school_year)
    if db_school_year is None:
        raise HTTPException(status_code=500, detail="Không thể tạo thư mục trên Google Drive.")
    return db_school_year

@app.get("/school_years/", response_model=List[schemas.SchoolYear])
def read_school_years(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_school_years(db, skip=skip, limit=limit)

@app.put("/school_years/{school_year_id}", response_model=schemas.SchoolYear)
def update_school_year_by_id(school_year_id: int, school_year: schemas.SchoolYearUpdate, db: Session = Depends(get_db)):
    db_school_year = crud.update_school_year(db, school_year_id=school_year_id, school_year_update=school_year)
    if db_school_year is None:
        raise HTTPException(status_code=404, detail="Năm học không tồn tại.")
    return db_school_year

@app.delete("/school_years/{school_year_id}")
def delete_school_year_by_id(school_year_id: int, db: Session = Depends(get_db)):
    deleted_school_year = crud.delete_school_year(db, school_year_id=school_year_id)
    if not deleted_school_year:
        raise HTTPException(status_code=404, detail="Năm học không tồn tại.")
    return {"message": "Đã xóa năm học thành công."}

# --- School Endpoints ---
@app.post("/schools/", response_model=schemas.School)
def create_new_school(school: schemas.SchoolCreate, db: Session = Depends(get_db)):
    db_school = crud.create_school(db=db, school=school)
    if db_school is None:
        raise HTTPException(status_code=400, detail="Tên trường có thể đã tồn tại.")
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

# --- FileTask & FileSubmission Endpoints ---
@app.post("/file-tasks/", response_model=schemas.FileTask)
def create_new_file_task(payload: Dict[str, Any], db: Session = Depends(get_db)):
    base_task = schemas.FileTaskCreate(
        title=payload["title"],
        content=payload["content"],
        deadline=payload["deadline"],
        school_year_id=payload["school_year_id"],
        attachment_url=payload.get("attachment_url") # <-- THÊM DÒNG NÀY
    )
    target_school_ids = payload.get("target_school_ids", [])
    return crud.create_file_task_with_targets(db=db, task=base_task, target_school_ids=target_school_ids)


@app.get("/file-tasks/{task_id}/upload-folder")
def get_upload_folder_for_task(
    task_id: int, user_email: Optional[str] = None, db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    folder_id = crud.get_or_create_file_submission_folder(db, task_id=task_id, school_id=current_school.id, user_email=user_email)
    if not folder_id:
        raise HTTPException(status_code=404, detail="Không thể tạo thư mục nộp bài.")
    return {"folder_id": folder_id}

@app.get("/file-tasks/", response_model=List[schemas.FileTask])
def read_file_tasks(
    school_year_id: Optional[int] = None, skip: int = 0, limit: int = 100, 
    db: Session = Depends(get_db), x_api_key: Optional[str] = Header(None)
):
    current_school_id = None
    if x_api_key:
        current_school = crud.get_school_by_api_key(db, api_key=x_api_key)
        if not current_school: raise HTTPException(status_code=401, detail="API Key không hợp lệ.")
        current_school_id = current_school.id
    
    tasks_from_db, reminded_task_ids = crud.get_file_tasks(db, school_year_id=school_year_id, current_school_id=current_school_id, skip=skip, limit=limit)
    response_tasks = []
    
    submitted_task_ids = set()
    if current_school_id:
        submitted_task_ids = crud.get_submitted_file_task_ids_for_school(db, school_id=current_school_id)
    
    for task in tasks_from_db:
        task_dict = {c.name: getattr(task, c.name) for c in task.__table__.columns}
        task_dict['is_locked'] = task_dict.get('is_locked') or False
        task_dict['is_submitted'] = task.id in submitted_task_ids
        task_dict['is_reminded'] = task.id in reminded_task_ids
        response_tasks.append(schemas.FileTask(**task_dict))
    return response_tasks

@app.get("/file-tasks/{task_id}/status", response_model=schemas.FileTaskStatus)
def read_file_task_status(task_id: int, db: Session = Depends(get_db)):
    status_data = crud.get_file_task_status(db, task_id=task_id)
    if status_data is None: 
        raise HTTPException(status_code=404, detail="Yêu cầu không tồn tại.")
    # SỬA LỖI: Đảm bảo is_locked không bao giờ là None trước khi trả về
    if status_data['task'].is_locked is None:
        status_data['task'].is_locked = False
    return status_data

@app.put("/file-tasks/{task_id}", response_model=schemas.FileTask)
def update_file_task_by_id(task_id: int, task: schemas.FileTaskUpdate, db: Session = Depends(get_db)):
    db_task = crud.update_file_task(db, task_id=task_id, task_update=task)
    if db_task is None: raise HTTPException(status_code=404, detail="Yêu cầu không tồn tại.")
    return db_task

@app.delete("/file-tasks/{task_id}")
def delete_file_task_by_id(task_id: int, db: Session = Depends(get_db)):
    deleted_task = crud.delete_file_task(db, task_id=task_id)
    if not deleted_task: raise HTTPException(status_code=404, detail="Yêu cầu không tồn tại.")
    return {"message": "Đã xóa yêu cầu thành công."}

@app.get("/file-tasks/{task_id}/download-all")
def download_all_submissions_for_task(task_id: int, db: Session = Depends(get_db)):
    submissions = crud.get_submissions_for_file_task(db, task_id=task_id)
    if not submissions: raise HTTPException(status_code=404, detail="Không có file nào được nộp.")
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

# --- ENDPOINTS CHO BÁO CÁO NHẬP LIỆU ---
@app.post("/data-reports/", response_model=schemas.DataReport)
def create_new_data_report(payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        base = schemas.DataReportCreate(
            title=payload["title"],
            deadline=payload["deadline"],
            school_year_id=payload["school_year_id"],
            columns_schema=[schemas.ColumnDefinition(**c) for c in payload["columns_schema"]],
            template_data=payload.get("template_data"),
            attachment_url=payload.get("attachment_url") # <-- THÊM DÒNG NÀY
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Dữ liệu không hợp lệ: {e}")

    target_school_ids = payload.get("target_school_ids")
    db_report = crud.create_data_report(db=db, report=base, target_school_ids=target_school_ids)
    if not db_report:
        raise HTTPException(status_code=400, detail="Không thể tạo báo cáo nhập liệu.")
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
        report_dict = {
            "id": report.id,
            "title": report.title,
            "deadline": report.deadline,
            "created_at": report.created_at,
            "columns_schema": report.columns_schema,
            "template_data": report.template_data,
            "is_locked": getattr(report, 'is_locked', False) or False,
            "is_submitted": False,
            "is_reminded": False
        }

        if current_school_id:
            report_dict['is_reminded'] = report.id in reminded_report_ids
            entry = crud.get_data_entry_for_school(db, report_id=report.id, school_id=current_school_id)
            report_dict['is_submitted'] = (entry and entry.submitted_at is not None)
        
        response_reports.append(schemas.DataReport(**report_dict))
        
    return response_reports

@app.get("/data-reports/{report_id}/schema", response_model=Dict[str, Any])
def get_data_report_schema(report_id: int, db: Session = Depends(get_db)):
    report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Báo cáo không tồn tại.")
    return {"columns_schema": report.columns_schema}

@app.get("/data-reports/{report_id}/my-submission", response_model=schemas.DataSubmissionCreate)
def get_my_data_submission(
    report_id: int, db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    submission = crud.get_data_submission_for_school(db, report_id=report_id, school_id=current_school.id)
    if submission is None:
         raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo tương ứng cho trường của bạn.")
    return submission

@app.post("/data-reports/{report_id}/submit", status_code=status.HTTP_200_OK)
def submit_data_for_report(
    report_id: int, submission: schemas.DataSubmissionCreate, db: Session = Depends(get_db),
    current_school: models.School = Depends(get_school_from_api_key)
):
    entry = crud.create_or_update_data_submission(db, report_id=report_id, school_id=current_school.id, submission_data=submission.data)
    if not entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo tương ứng cho trường của bạn.")
    return {"message": "Đã lưu dữ liệu thành công."}

@app.get("/data-reports/{report_id}/status", response_model=schemas.DataReportStatus)
def read_data_report_status(report_id: int, db: Session = Depends(get_db)):
    status_data = crud.get_data_report_status(db, report_id=report_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail="Báo cáo nhập liệu không tồn tại.")
    # SỬA LỖI: Đảm bảo is_locked không bao giờ là None trước khi trả về
    if status_data['report'].is_locked is None:
        status_data['report'].is_locked = False
    return status_data

@app.get("/data-reports/{report_id}/export-excel")
def export_data_report_to_excel(report_id: int, db: Session = Depends(get_db)):
    report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Báo cáo không tồn tại.")

    submissions = crud.get_all_data_submissions_for_report(db, report_id=report_id)
    if not submissions:
        raise HTTPException(status_code=404, detail="Chưa có trường nào nộp dữ liệu cho báo cáo này.")

    output = io.BytesIO()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    
    headers = [col['title'] for col in report.columns_schema]
    sheet.append(headers)
    
    column_keys = [col['name'] for col in report.columns_schema]

    for item in submissions:
        row = [item.get(key, "") for key in column_keys]
        sheet.append(row)

    workbook.save(output)
    output.seek(0)
    
    response_headers = {
        'Content-Disposition': f'attachment; filename="bao_cao_tong_hop_{report_id}.xlsx"'
    }
    return StreamingResponse(output, headers=response_headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.get("/data-reports/{report_id}/submission/{school_id}", response_model=Dict[str, Any])
def get_submission_for_school_admin(report_id: int, school_id: int, db: Session = Depends(get_db)):
    submission = crud.get_data_submission_for_school(db, report_id=report_id, school_id=school_id)
    if submission is None:
        return {"data": []}
    return submission

@app.delete("/data-reports/{report_id}", status_code=status.HTTP_200_OK)
def delete_data_report_by_id(report_id: int, db: Session = Depends(get_db)):
    deleted_report = crud.delete_data_report(db, report_id=report_id)
    if not deleted_report:
        raise HTTPException(status_code=404, detail="Báo cáo nhập liệu không tồn tại.")
    return {"message": "Đã xóa báo cáo thành công."}

@app.put("/data-reports/{report_id}", response_model=schemas.DataReport)
def update_data_report_by_id(report_id: int, report: schemas.DataReportUpdate, db: Session = Depends(get_db)):
    db_report = crud.update_data_report(db, report_id=report_id, report_update=report)
    if db_report is None:
        raise HTTPException(status_code=404, detail="Báo cáo không tồn tại.")
    return db_report
    
@app.get("/admin/dashboard-stats", response_model=schemas.DashboardStats)
def get_dashboard_statistics(db: Session = Depends(get_db)):
    return crud.get_dashboard_stats(db)

@app.put("/admin/data-submissions/{report_id}/{school_id}", status_code=status.HTTP_200_OK)
def update_school_submission_by_admin(
    report_id: int, 
    school_id: int, 
    submission: schemas.AdminDataSubmissionUpdate, 
    db: Session = Depends(get_db)
):
    updated_entry = crud.update_data_submission_by_admin(
        db, report_id=report_id, school_id=school_id, submission_update=submission
    )
    if not updated_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi nộp bài của trường này.")
    return {"message": "Đã cập nhật dữ liệu thành công."}
    
@app.post("/admin/remind/{task_type}/{task_id}", status_code=status.HTTP_200_OK)
def send_reminders(task_type: str, task_id: int, db: Session = Depends(get_db)):
    if task_type not in ["file", "data"]:
        raise HTTPException(status_code=400, detail="Loại công việc không hợp lệ.")
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

