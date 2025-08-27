# crud.py
import os.path
import re
import io
from sqlalchemy.orm import Session, joinedload
from unidecode import unidecode
from typing import Optional, Set, List, Tuple
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
import gspread

import models, schemas

ROOT_DRIVE_FOLDER_ID = "13di1au2iwdr5cbz57b4q_SEK-RF5ZiiC"

SERVER_SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/spreadsheets'
]

def _get_google_service(service_name: str, version: str):
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SERVER_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials_oauth.json'):
                raise FileNotFoundError("Server không tìm thấy file credentials_oauth.json.")
            flow = InstalledAppFlow.from_client_secrets_file('credentials_oauth.json', SERVER_SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build(service_name, version, credentials=creds), creds

def _get_or_create_folder(service, name: str, parent_id: str):
    try:
        query = f"name='{unidecode(name)}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        response = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
        folders = response.get('files', [])
        if folders:
            return folders[0].get('id')
        
        folder_metadata = {'name': unidecode(name), 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')
    except HttpError as e:
        print(f"Lỗi khi lấy hoặc tạo thư mục '{name}': {e}")
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

# --- SchoolYear & School ---

def get_school_years(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.SchoolYear).order_by(models.SchoolYear.start_date.desc()).offset(skip).limit(limit).all()

def create_school_year(db: Session, school_year: schemas.SchoolYearCreate):
    drive_service, _ = _get_google_service('drive', 'v3')
    folder_id = _get_or_create_folder(drive_service, school_year.name, ROOT_DRIVE_FOLDER_ID)
    if not folder_id:
        return None
        
    db_school_year = models.SchoolYear(**school_year.dict(), drive_folder_id=folder_id)
    db.add(db_school_year)
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

# --- FileTask & FileSubmission ---

def get_or_create_file_submission_folder(db: Session, task_id: int, school_id: int) -> Optional[str]:
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
    
    return monthly_folder_id

def get_file_tasks(db: Session, school_year_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    query = db.query(models.FileTask)
    if school_year_id:
        query = query.filter(models.FileTask.school_year_id == school_year_id)
    return query.order_by(models.FileTask.deadline.desc()).offset(skip).limit(limit).all()

def create_file_task(db: Session, task: schemas.FileTaskCreate):
    db_task = models.FileTask(**task.dict())
    db.add(db_task)
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

# --- DataReport & DataEntry ---

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

def get_data_reports(db: Session, school_year_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    query = db.query(models.DataReport)
    if school_year_id:
        query = query.filter(models.DataReport.school_year_id == school_year_id)
    return query.order_by(models.DataReport.deadline.desc()).offset(skip).limit(limit).all()

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
