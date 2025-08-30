# crud.py
# ... (giữ nguyên các hàm từ đầu file đến trước hàm update_school_year)
import os.path
import re
import io
from sqlalchemy.orm import Session, joinedload
from unidecode import unidecode
from typing import Optional, Set, List, Tuple, Dict, Any
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

import models, schemas

# MODIFIED: ID thư mục gốc mới trên Drive của bạn
ROOT_DRIVE_FOLDER_ID = "0AB0xC4mVFuxMUk9PVA" # ID của thư mục PHONGVH-XH_HONAI
SHARED_ATTACHMENTS_FOLDER_NAME = "_Attachments_Shared"

SERVER_SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/gmail.send'
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
            fields='id',
            sendNotificationEmail=False
        ).execute()
        print(f"Successfully shared folder {folder_id} with {user_email}")
        return True
    except HttpError as e:
        if e.resp.status == 403:
             print(f"Could not share folder {folder_id} with {user_email}. Maybe permission already exists? Error: {e}")
             return True
        print(f"An error occurred while sharing folder: {e}")
        return False

def _get_or_create_folder(service, name: str, parent_id: str):
    try:
        folder_name_ascii = unidecode(name)
        query = f"name='{folder_name_ascii}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        response = service.files().list(q=query, spaces='drive', fields='files(id)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        folders = response.get('files', [])
        
        if folders:
            return folders[0].get('id')
        
        folder_metadata = {'name': folder_name_ascii, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        folder = service.files().create(body=folder_metadata, fields='id', supportsAllDrives=True).execute()
        return folder.get('id')
    except HttpError as e:
        return None

def upload_attachment_to_drive(file_name: str, file_content: bytes) -> Optional[str]:
    """
    Tải file đính kèm lên một thư mục chia sẻ chung và trả về link có thể xem.
    """
    try:
        service, _ = _get_google_service('drive', 'v3')
        # Tạo một thư mục chung để chứa tất cả file đính kèm cho gọn
        shared_folder_id = _get_or_create_folder(service, SHARED_ATTACHMENTS_FOLDER_NAME, ROOT_DRIVE_FOLDER_ID)
        if not shared_folder_id:
            print("Lỗi: Không thể tạo thư mục cho file đính kèm.")
            return None

        file_metadata = {'name': file_name, 'parents': [shared_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype='application/octet-stream', resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        
        # Cấp quyền cho mọi người có link đều xem được
        file_id = file.get('id')
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(fileId=file_id, body=permission, supportsAllDrives=True).execute()
        print(f"Đã tải và chia sẻ file: {file.get('webViewLink')}")
        
        return file.get('webViewLink')
    except HttpError as e:
        print(f"Lỗi khi tải file đính kèm lên Drive: {e}")
        return None

def _rename_drive_folder(service, folder_id: str, new_name: str):
    """
    HÀM MỚI: Đổi tên một thư mục trên Google Drive.
    """
    try:
        new_name_ascii = unidecode(new_name)
        file_metadata = {'name': new_name_ascii}
        service.files().update(
            fileId=folder_id,
            body=file_metadata,
            supportsAllDrives=True,
            fields='id'
        ).execute()
        print(f"Successfully renamed folder {folder_id} to '{new_name_ascii}'")
        return True
    except HttpError as e:
        print(f"An error occurred while renaming folder: {e}")
        return False

def extract_drive_file_id_from_url(url: str) -> Optional[str]:
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match: return match.group(1)
    return None

def download_file_from_drive(file_id: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        service, _ = _get_google_service('drive', 'v3')
        file_metadata = service.files().get(fileId=file_id, fields='name', supportsAllDrives=True).execute()
        file_name = file_metadata.get('name')
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
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
    """
    SỬA ĐỔI: Thêm logic đổi tên thư mục trên Google Drive khi tên năm học thay đổi.
    """
    db_school_year = db.query(models.SchoolYear).filter(models.SchoolYear.id == school_year_id).first()
    if db_school_year:
        update_data = school_year_update.dict(exclude_unset=True)
        
        # Kiểm tra nếu tên thay đổi thì gọi API đổi tên thư mục Drive
        if 'name' in update_data and update_data['name'] != db_school_year.name:
            if db_school_year.drive_folder_id:
                try:
                    drive_service, _ = _get_google_service('drive', 'v3')
                    success = _rename_drive_folder(drive_service, db_school_year.drive_folder_id, update_data['name'])
                    if not success:
                        print(f"CẢNH BÁO: Không thể đổi tên thư mục Google Drive cho năm học ID {school_year_id}.")
                except Exception as e:
                    print(f"Lỗi kết nối Google Drive API để đổi tên: {e}")

        # Cập nhật các trường trong database
        for key, value in update_data.items():
            setattr(db_school_year, key, value)
        db.commit()
        db.refresh(db_school_year)
    return db_school_year

# ... (giữ nguyên các hàm còn lại của file)
# ...
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

def get_or_create_file_submission_folder(db: Session, task_id: int, school_id: int, user_email: Optional[str] = None) -> Optional[str]:
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
    
    if monthly_folder_id and user_email:
        _share_folder_with_user(drive_service, monthly_folder_id, user_email)

    return monthly_folder_id

def get_file_tasks(
    db: Session,
    school_year_id: Optional[int] = None,
    current_school_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
):
    """
    SỬA ĐỔI: Xóa bộ lọc is_locked để client thấy cả các task đã bị khóa.
    """
    tasks_query = db.query(models.FileTask)
    if school_year_id:
        tasks_query = tasks_query.filter(models.FileTask.school_year_id == school_year_id)

    tasks = tasks_query.order_by(models.FileTask.deadline.desc()).all()

    reminders_all = db.query(models.TaskReminder.task_id, models.TaskReminder.school_id)\
                      .filter(models.TaskReminder.task_type == "file").all()
    assigned_map: dict[int, set[int]] = {}
    for t_id, s_id in reminders_all:
        assigned_map.setdefault(t_id, set()).add(s_id)

    reminded_task_ids: set[int] = set()
    if current_school_id:
        filtered = []
        for t in tasks:
            assignees = assigned_map.get(t.id, set())
            if not assignees or (current_school_id in assignees):
                filtered.append(t)
        tasks = filtered
        reminded_task_ids = {t_id for (t_id, s_id) in reminders_all if s_id == current_school_id}

    tasks = tasks[skip: skip + limit]
    return tasks, reminded_task_ids
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
        # exclude_unset=True đảm bảo chỉ cập nhật các trường được gửi lên
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
    if not task:
        return None

    target_ids = [sid for (sid,) in db.query(models.TaskReminder.school_id)
                                  .filter(models.TaskReminder.task_type == "file",
                                          models.TaskReminder.task_id == task_id).all()]
    if target_ids:
        eligible_schools = db.query(models.School).filter(models.School.id.in_(target_ids)).all()
    else:
        eligible_schools = get_schools(db)

    submission_map = {sub.school_id: sub for sub in task.submissions}
    submitted_schools_info = []
    not_submitted_schools = []
    for school in eligible_schools:
        if school.id in submission_map:
            submission = submission_map[school.id]
            submitted_schools_info.append({
                "id": school.id, "name": school.name,
                "file_url": submission.file_url, "submitted_at": submission.submitted_at
            })
        else:
            not_submitted_schools.append(school)

    return {"task": task, "submitted_schools": submitted_schools_info, "not_submitted_schools": not_submitted_schools}

def get_submitted_file_task_ids_for_school(db: Session, school_id: int) -> Set[int]:
    submitted_tasks = db.query(models.FileSubmission.task_id).filter(models.FileSubmission.school_id == school_id).distinct().all()
    return {task_id for (task_id,) in submitted_tasks}

def get_submissions_for_file_task(db: Session, task_id: int) -> List[models.FileSubmission]:
    return db.query(models.FileSubmission).filter(models.FileSubmission.task_id == task_id).all()

def create_data_report(db: Session, report: schemas.DataReportCreate,
                       target_school_ids: Optional[List[int]] = None) -> models.DataReport:
    db_report = models.DataReport(
        title=report.title,
        deadline=report.deadline,
        school_year_id=report.school_year_id,
        columns_schema=[col.dict() for col in report.columns_schema],
        template_data=report.template_data,
        attachment_url=report.attachment_url # <-- THÊM DÒNG NÀY
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)

    if target_school_ids:
        schools = db.query(models.School).filter(models.School.id.in_(target_school_ids)).all()
    else:
        schools = get_schools(db)

    for s in schools:
        db.add(models.DataEntry(report_id=db_report.id, school_id=s.id, data=report.template_data, submitted_at=None))
    db.commit()
    return db_report
    
def create_or_update_data_submission(db: Session, report_id: int, school_id: int, submission_data: List[Dict[str, Any]]) -> Optional[models.DataEntry]:
    entry = db.query(models.DataEntry).filter_by(report_id=report_id, school_id=school_id).first()
    
    if not entry:
        return None

    entry.data = submission_data
    entry.submitted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(entry)
    return entry

def get_data_submission_for_school(db: Session, report_id: int, school_id: int) -> Optional[Dict[str, Any]]:
    entry = db.query(models.DataEntry).filter_by(report_id=report_id, school_id=school_id).first()
    
    if not entry:
        return None
    
    return {"data": entry.data or []}

def get_data_reports(db: Session, school_year_id: Optional[int] = None, current_school_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    """
    SỬA ĐỔI: Xóa bộ lọc is_locked để client thấy cả các báo cáo đã bị khóa.
    """
    query = db.query(models.DataReport)

    if current_school_id:
        # Xóa điều kiện is_locked == False khỏi query
        query = query.join(models.DataEntry).filter(
            models.DataEntry.school_id == current_school_id
        )

    if school_year_id:
        query = query.filter(models.DataReport.school_year_id == school_year_id)
    
    reminded_report_ids = set()
    if current_school_id:
        reminders = db.query(models.TaskReminder.task_id).filter(
            models.TaskReminder.school_id == current_school_id,
            models.TaskReminder.task_type == "data"
        ).all()
        reminded_report_ids = {r.task_id for r in reminders}

    reports = query.order_by(models.DataReport.deadline.desc()).offset(skip).limit(limit).all()
    
    return reports, reminded_report_ids
    
def get_data_report_status(db: Session, report_id: int):
    report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if not report: return None
    entry_map = {e.school_id: e for e in report.entries}
    target_ids = list(entry_map.keys())
    if not target_ids:
        return {"report": report, "submitted_schools": [], "not_submitted_schools": []}

    target_schools = db.query(models.School).filter(models.School.id.in_(target_ids)).all()
    submitted_schools_info = []
    not_submitted_schools = []
    for s in target_schools:
        e = entry_map.get(s.id)
        if e and e.submitted_at:
            submitted_schools_info.append({"id": s.id, "name": s.name, "submitted_at": e.submitted_at})
        else:
            not_submitted_schools.append(s)
    return {"report": report, "submitted_schools": submitted_schools_info, "not_submitted_schools": not_submitted_schools}

def get_dashboard_stats(db: Session) -> schemas.DashboardStats:
    now = datetime.utcnow()
    
    overdue_file_tasks = db.query(models.FileTask).filter(
        models.FileTask.deadline < now, 
        models.FileTask.is_locked == False
    ).count()

    overdue_data_reports = db.query(models.DataReport).filter(
        models.DataReport.deadline < now, 
        models.DataReport.is_locked == False
    ).count()
    
    total_schools = db.query(models.School).count()
    
    active_year = db.query(models.SchoolYear).filter(models.SchoolYear.is_active == True).first()
    
    return schemas.DashboardStats(
        overdue_file_tasks=overdue_file_tasks,
        overdue_data_reports=overdue_data_reports,
        total_schools=total_schools,
        active_school_year_name=active_year.name if active_year else "Chưa có"
    )

def update_data_submission_by_admin(db: Session, report_id: int, school_id: int, submission_update: schemas.AdminDataSubmissionUpdate) -> Optional[models.DataEntry]:
    entry = db.query(models.DataEntry).filter_by(report_id=report_id, school_id=school_id).first()
    
    if not entry:
        return None

    entry.data = submission_update.data
    if not entry.submitted_at:
        entry.submitted_at = datetime.utcnow()
        
    entry.last_edited_by = "admin"
    entry.last_edited_at = datetime.utcnow()
    
    db.commit()
    db.refresh(entry)
    return entry

def get_all_data_submissions_for_report(db: Session, report_id: int) -> List[Dict[str, Any]]:
    q = (
        db.query(models.DataEntry)
        .filter(models.DataEntry.report_id == report_id, models.DataEntry.submitted_at.isnot(None))
        .all()
    )
           
    results = []
    for entry in q:
        if entry.data: 
            results.extend(entry.data)
    return results
 
def delete_data_report(db: Session, report_id: int):
    db_report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if db_report:
        db.delete(db_report)
        db.commit()
    return db_report
    
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

def update_data_report(db: Session, report_id: int, report_update: schemas.DataReportUpdate):
    db_report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if db_report:
        update_data = report_update.dict(exclude_unset=True)
        
        if 'columns_schema' in update_data:
             db_report.columns_schema = update_data['columns_schema']
             del update_data['columns_schema']

        if 'template_data' in update_data:
             db_report.template_data = update_data['template_data']
             del update_data['template_data']

        for key, value in update_data.items():
            setattr(db_report, key, value)
            
        db.commit()
        db.refresh(db_report)
    return db_report
    
def create_file_task_with_targets(
    db: Session,
    task: schemas.FileTaskCreate,
    target_school_ids: Optional[List[int]] = None
):
    # Dòng task.dict() sẽ tự động lấy cả 'attachment_url' từ schema
    db_task = models.FileTask(**task.dict())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    if target_school_ids:
        for sid in target_school_ids:
            db.add(models.TaskReminder(task_type="file", task_id=db_task.id, school_id=sid))
        db.commit()

    return db_task

