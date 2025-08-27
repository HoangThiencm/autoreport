# crud.py
import os.path
import re
import io
from sqlalchemy.orm import Session, joinedload
from unidecode import unidecode
from typing import Optional, Set, List, Tuple
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
import gspread

import models, schemas

ROOT_DRIVE_FOLDER_ID = "1htQOiPyDqkrQxtEEQfHOoJizz9rzQr-L"

SERVER_SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/spreadsheets'
]

SERVICE_ACCOUNT_FILE = 'service_account.json'

def _get_google_service(service_name: str, version: str):
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"Không tìm thấy file khóa dịch vụ trên server: '{SERVICE_ACCOUNT_FILE}'")
    
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SERVER_SCOPES)
        service = build(service_name, version, credentials=creds)
        return service, creds
    except Exception as e:
        raise

def _share_folder_with_user(service, folder_id: str, user_email: str):
    try:
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': user_email
        }
        service.permissions().create(
            fileId=folder_id,
            body=permission,
            fields='id'
        ).execute()
        print(f"Successfully shared folder {folder_id} with {user_email}")
        return True
    except HttpError as e:
        # If permission already exists, it might raise an error. We can often ignore it.
        if e.resp.status == 403:
             print(f"Could not share folder {folder_id} with {user_email}. Maybe permission already exists? Error: {e}")
             return True # Assume it's okay
        print(f"An error occurred while sharing folder: {e}")
        return False

def _get_or_create_folder(service, name: str, parent_id: str):
    try:
        folder_name_ascii = unidecode(name)
        query = f"name='{folder_name_ascii}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        response = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
        folders = response.get('files', [])
        
        if folders:
            return folders[0].get('id')
        
        folder_metadata = {'name': folder_name_ascii, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')
    except HttpError as e:
        return None

def extract_drive_file_id_from_url(url: str) -> Optional[str]:
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match: return match.group(1)
    return None

def download_file_from_drive(file_id: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        service, _ = _get_google_service('drive', 'v3')
        file_metadata = service.files().get(fileId=file_id, fields='name').execute()
        file_name = file_metadata.get('name')
        request = service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        file_buffer.seek(0)
        return file_buffer.read(), file_name
    except HttpError as error:
        print(f"Lỗi khi tải file từ Google Drive: {error}")
        return None, None

def get_school_by_api_key(db: Session, api_key: str):
    return db.query(models.School).filter(models.School.api_key == api_key).first()

def get_school_years(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.SchoolYear).order_by(models.SchoolYear.start_date.desc()).offset(skip).limit(limit).all()

def create_school_year(db: Session, school_year: schemas.SchoolYearCreate):
    try:
        drive_service, _ = _get_google_service('drive', 'v3')
        folder_id = _get_or_create_folder(drive_service, school_year.name, ROOT_DRIVE_FOLDER_ID)
        
        if not folder_id:
            return None
        
        db_school_year = models.SchoolYear(**school_year.dict(), drive_folder_id=folder_id)
        db.add(db_school_year)
        db.commit()
        db.refresh(db_school_year)
        return db_school_year
    except Exception as e:
        db.rollback()
        return None

def delete_school_year(db: Session, school_year_id: int):
    db_school_year = db.query(models.SchoolYear).filter(models.SchoolYear.id == school_year_id).first()
    if db_school_year:
        db.delete(db_school_year)
        db.commit()
    return db_school_year

def update_school_year(db: Session, school_year_id: int, school_year_update: schemas.SchoolYearUpdate):
    db_school_year = db.query(models.SchoolYear).filter(models.SchoolYear.id == school_year_id).first()
    if db_school_year:
        update_data = school_year_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_school_year, key, value)
        db.commit()
        db.refresh(db_school_year)
    return db_school_year

def get_schools(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.School).order_by(models.School.name).offset(skip).limit(limit).all()

def create_school(db: Session, school: schemas.SchoolCreate):
    db_school = models.School(name=school.name)
    db.add(db_school)
    try:
        db.commit()
        db.refresh(db_school)
    except IntegrityError:
        db.rollback()
        return None
    return db_school

def delete_school(db: Session, school_id: int):
    db_school = db.query(models.School).filter(models.School.id == school_id).first()
    if db_school:
        db.delete(db_school)
        db.commit()
    return db_school

def get_or_create_file_submission_folder(db: Session, task_id: int, school_id: int, user_email: str) -> Optional[str]:
    task = db.query(models.FileTask).options(joinedload(models.FileTask.school_year)).filter(models.FileTask.id == task_id).first()
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not task or not school or not task.school_year or not task.school_year.drive_folder_id:
        return None
    drive_service, _ = _get_google_service('drive', 'v3')
    school_folder_id = _get_or_create_folder(drive_service, school.name, task.school_year.drive_folder_id)
    if not school_folder_id:
        return None
    month_name = f"Thang {datetime.now().strftime('%m-%Y')}"
    monthly_folder_id = _get_or_create_folder(drive_service, month_name, school_folder_id)
    
    # Share the final folder with the user
    if monthly_folder_id and user_email:
        _share_folder_with_user(drive_service, monthly_folder_id, user_email)

    return monthly_folder_id

def get_file_tasks(db: Session, school_year_id: Optional[int] = None, current_school_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    query = db.query(models.FileTask)
    if school_year_id:
        query = query.filter(models.FileTask.school_year_id == school_year_id)
    
    reminded_task_ids = set()
    if current_school_id:
        reminders = db.query(models.TaskReminder.task_id).filter(
            models.TaskReminder.school_id == current_school_id,
            models.TaskReminder.task_type == "file"
        ).all()
        reminded_task_ids = {r.task_id for r in reminders}

    return query.order_by(models.FileTask.deadline.desc()).offset(skip).limit(limit).all(), reminded_task_ids

def create_file_task(db: Session, task: schemas.FileTaskCreate):
    db_task = models.FileTask(**task.dict())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

def delete_file_task(db: Session, task_id: int):
    db_task = db.query(models.FileTask).filter(models.FileTask.id == task_id).first()
    if db_task:
        db.delete(db_task)
        db.commit()
    return db_task

def update_file_task(db: Session, task_id: int, task_update: schemas.FileTaskUpdate):
    db_task = db.query(models.FileTask).filter(models.FileTask.id == task_id).first()
    if db_task:
        update_data = task_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_task, key, value)
        db.commit()
        db.refresh(db_task)
    return db_task

def get_file_task_by_id(db: Session, task_id: int):
    return db.query(models.FileTask).filter(models.FileTask.id == task_id).first()

def create_file_submission(db: Session, submission: schemas.FileSubmissionCreate, school_id: int):
    db_submission = db.query(models.FileSubmission).filter_by(task_id=submission.task_id, school_id=school_id).first()
    if db_submission:
        db_submission.file_url = submission.file_url
        db_submission.submitted_at = datetime.utcnow()
    else:
        db_submission = models.FileSubmission(**submission.dict(), school_id=school_id)
        db.add(db_submission)
    db.commit()
    db.refresh(db_submission)
    return db_submission

def get_file_task_status(db: Session, task_id: int):
    task = get_file_task_by_id(db, task_id)
    if not task: return None
    all_schools = get_schools(db)
    submission_map = {sub.school_id: sub for sub in task.submissions}
    submitted_schools_info = []
    not_submitted_schools = []
    for school in all_schools:
        if school.id in submission_map:
            submission = submission_map[school.id]
            submitted_schools_info.append({"id": school.id, "name": school.name, "file_url": submission.file_url, "submitted_at": submission.submitted_at})
        else:
            not_submitted_schools.append(school)
    return {"task": task, "submitted_schools": submitted_schools_info, "not_submitted_schools": not_submitted_schools}

def get_submitted_file_task_ids_for_school(db: Session, school_id: int) -> Set[int]:
    submitted_tasks = db.query(models.FileSubmission.task_id).filter(models.FileSubmission.school_id == school_id).distinct().all()
    return {task_id for (task_id,) in submitted_tasks}

def get_submissions_for_file_task(db: Session, task_id: int) -> List[models.FileSubmission]:
    return db.query(models.FileSubmission).filter(models.FileSubmission.task_id == task_id).all()

def create_data_report(db: Session, report: schemas.DataReportCreate):
    template_id = extract_drive_file_id_from_url(report.template_url)
    if not template_id:
        return None, "URL Google Sheet mẫu không hợp lệ."
    school_year = db.query(models.SchoolYear).filter(models.SchoolYear.id == report.school_year_id).first()
    if not school_year or not school_year.drive_folder_id:
        return None, "Năm học không hợp lệ hoặc chưa có thư mục Drive."
    db_report = models.DataReport(**report.dict())
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    try:
        drive_service, _ = _get_google_service('drive', 'v3')
        year_folder_id = school_year.drive_folder_id
        all_schools = get_schools(db)
        for school in all_schools:
            school_folder_id = _get_or_create_folder(drive_service, school.name, year_folder_id)
            if not school_folder_id:
                print(f"CẢNH BÁO: Không thể tạo thư mục cho trường {school.name} trong năm học.")
                continue
            copy_title = f"{report.title} - {school.name}"
            copied_file = drive_service.files().copy(
                fileId=template_id, 
                body={'name': copy_title, 'parents': [school_folder_id]}
            ).execute()
            file_id = copied_file.get('id')
            file_metadata = drive_service.files().get(fileId=file_id, fields='webViewLink').execute()
            sheet_url = file_metadata.get('webViewLink')
            new_entry = models.DataEntry(report_id=db_report.id, school_id=school.id, sheet_url=sheet_url)
            db.add(new_entry)
        db.commit()
        return db_report, None
    except HttpError as error:
        db.rollback()
        db.delete(db_report)
        db.commit()
        return None, f"Lỗi Google API: {error}"

def get_data_reports(db: Session, school_year_id: Optional[int] = None, current_school_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    query = db.query(models.DataReport)
    if school_year_id:
        query = query.filter(models.DataReport.school_year_id == school_year_id)
    
    reminded_report_ids = set()
    if current_school_id:
        reminders = db.query(models.TaskReminder.task_id).filter(
            models.TaskReminder.school_id == current_school_id,
            models.TaskReminder.task_type == "data"
        ).all()
        reminded_report_ids = {r.task_id for r in reminders}

    return query.order_by(models.DataReport.deadline.desc()).offset(skip).limit(limit).all(), reminded_report_ids

def mark_data_report_as_complete(db: Session, report_id: int, school_id: int):
    entry = db.query(models.DataEntry).filter_by(report_id=report_id, school_id=school_id).first()
    if entry and not entry.submitted_at:
        entry.submitted_at = datetime.utcnow()
        db.commit()
        db.refresh(entry)
        return entry
    return None

def get_data_report_status(db: Session, report_id: int):
    report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if not report: return None
    all_schools = get_schools(db)
    entry_map = {entry.school_id: entry for entry in report.entries}
    submitted_schools_info = []
    not_submitted_schools = []
    for school in all_schools:
        if school.id in entry_map and entry_map[school.id].submitted_at:
            entry = entry_map[school.id]
            submitted_schools_info.append({"id": school.id, "name": school.name, "submitted_at": entry.submitted_at})
        else:
            not_submitted_schools.append(school)
    return {"report": report, "submitted_schools": submitted_schools_info, "not_submitted_schools": not_submitted_schools}

def get_data_entry_for_school(db: Session, report_id: int, school_id: int):
    return db.query(models.DataEntry).filter_by(report_id=report_id, school_id=school_id).first()

def create_reminders_for_task(db: Session, task_type: str, task_id: int):
    not_submitted_schools = []
    if task_type == "file":
        status_data = get_file_task_status(db, task_id)
        if not status_data: return False, "Không tìm thấy công việc."
        not_submitted_schools = status_data.get('not_submitted_schools', [])
    elif task_type == "data":
        status_data = get_data_report_status(db, task_id)
        if not status_data: return False, "Không tìm thấy báo cáo."
        not_submitted_schools = status_data.get('not_submitted_schools', [])

    if not not_submitted_schools:
        return True, "Tất cả các trường đã nộp, không cần gửi nhắc nhở."
    
    count = 0
    for school in not_submitted_schools:
        existing_reminder = db.query(models.TaskReminder).filter_by(
            task_type=task_type, task_id=task_id, school_id=school.id
        ).first()
        if not existing_reminder:
            reminder = models.TaskReminder(task_type=task_type, task_id=task_id, school_id=school.id)
            db.add(reminder)
            count += 1
    
    db.commit()
    return True, f"Đã tạo {count} nhắc nhở cho các trường chưa nộp."

def reset_database(db: Session):
    try:
        db.query(models.TaskReminder).delete()
        db.query(models.FileSubmission).delete()
        db.query(models.DataEntry).delete()
        db.commit()
        db.query(models.FileTask).delete()
        db.query(models.DataReport).delete()
        db.commit()
        db.query(models.School).delete()
        db.commit()
        db.query(models.SchoolYear).delete()
        db.commit()
        return True, "Đã xóa toàn bộ dữ liệu thành công."
    except Exception as e:
        db.rollback()
        return False, f"Lỗi khi xóa dữ liệu: {e}"
