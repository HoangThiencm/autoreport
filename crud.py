import os.path
import re
import io
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from unidecode import unidecode
from typing import Optional, Set, List, Tuple, Dict, Any, Literal
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
        description=report.description,
        deadline=report.deadline,
        school_year_id=report.school_year_id,
        columns_schema=[col.dict() for col in report.columns_schema],
        template_data=report.template_data,
        attachment_url=report.attachment_url
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
    """
    SỬA LỖI LOGIC: Khi một yêu cầu nộp file được tạo cho "Tất cả",
    hàm này sẽ tạo bản ghi TaskReminder cho TẤT CẢ các trường hiện có.
    Điều này làm cho việc giao nhiệm vụ trở nên rõ ràng và giúp truy vấn báo cáo nhanh hơn nhiều.
    """
    db_task = models.FileTask(**task.dict())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    ids_to_assign = []
    if target_school_ids is None:
        # Nếu target_school_ids là None, có nghĩa là giao cho TẤT CẢ các trường
        all_schools = db.query(models.School.id).all()
        ids_to_assign = [s.id for s in all_schools]
    else:
        # Ngược lại, chỉ giao cho các trường được chỉ định
        ids_to_assign = target_school_ids

    if ids_to_assign:
        for sid in ids_to_assign:
            # Tạo một "lời nhắc" (thực chất là bản ghi giao nhiệm vụ) cho mỗi trường
            db.add(models.TaskReminder(task_type="file", task_id=db_task.id, school_id=sid))
        db.commit()

    return db_task

def compute_compliance_summary(
    db: Session,
    start: datetime,
    end: datetime,
    school_year_id: int | None,
    kind: Literal["file", "data", "both"] = "both"
) -> Dict[str, Any]:
    """
    Tổng hợp tình trạng nộp theo khoảng thời gian [start, end].
    - Chuẩn hóa thời gian sang UTC để so sánh ổn định trên Render/localhost.
    - Tính trạng thái RIÊNG cho 'file' và 'data':
        -1 = không được giao, 0 = thiếu, 1 = trễ, 2 = đúng hạn
    - Nếu kind='both': lấy trạng thái "tốt nhất" giữa 2 loại (2 > 1 > 0 > -1).
      Như vậy một trường có ít nhất 1 hạng mục đúng hạn sẽ KHÔNG bị xếp chung vào "không nộp".
    """
    from datetime import timezone

    # Chuẩn hóa mốc thời gian
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    # Khởi tạo bảng trạng thái theo trường
    schools = db.query(models.School).all()
    school_map = {s.id: s for s in schools}
    per_school = {
        s.id: {
            "id": s.id,
            "name": s.name,
            # trạng thái từng loại
            "file_status": -1,
            "data_status": -1,
            # đếm giao & kết quả (tham khảo/xuất thêm)
            "file_assigned": 0, "file_ontime": 0, "file_late": 0, "file_missing": 0,
            "data_assigned": 0, "data_ontime": 0, "data_late": 0, "data_missing": 0,
        }
        for s in schools
    }

    def _score_from_counts(ontime, late, missing, assigned):
        """Trả về điểm: -1/0/1/2 (không giao/thiếu/trễ/đúng hạn)."""
        if assigned == 0:
            return -1
        if missing > 0:
            return 0
        if late > 0:
            return 1
        if ontime > 0:
            return 2
        return 0

    # ====== FILE TASKS ======
    if kind in ("file", "both"):
        q = db.query(models.FileTask).filter(
            models.FileTask.deadline >= start_utc,
            models.FileTask.deadline <= end_utc
        )
        if school_year_id:
            q = q.filter(models.FileTask.school_year_id == school_year_id)
        tasks = q.all()

        if tasks:
            task_ids = [t.id for t in tasks]
            # submissions & reminders
            submissions = db.query(models.FileSubmission)\
                            .filter(models.FileSubmission.task_id.in_(task_ids)).all()
            reminders = db.query(models.TaskReminder)\
                          .filter(models.TaskReminder.task_type == "file",
                                  models.TaskReminder.task_id.in_(task_ids)).all()

            sub_map: Dict[int, Dict[int, models.FileSubmission]] = {}
            for sub in submissions:
                sub_map.setdefault(sub.task_id, {})[sub.school_id] = sub

            # TaskReminder thể hiện trường nào được giao (assigned)
            rem_map: Dict[int, Set[int]] = {}
            for rem in reminders:
                rem_map.setdefault(rem.task_id, set()).add(rem.school_id)

            for task in tasks:
                # ❗ FIX: nếu task KHÔNG có bất kỳ reminder nào ⇒ coi như giao CHO TẤT CẢ TRƯỜNG
                eligible_school_ids = rem_map.get(task.id)
                if not eligible_school_ids:
                    eligible_school_ids = set(school_map.keys())

                # chuẩn hóa deadline UTC
                deadline_utc = (task.deadline.replace(tzinfo=timezone.utc)
                                if task.deadline.tzinfo is None else
                                task.deadline.astimezone(timezone.utc))
                task_subs = sub_map.get(task.id, {})

                for sid in eligible_school_ids:
                    if sid not in per_school:
                        continue
                    ps = per_school[sid]
                    ps["file_assigned"] += 1
                    sub = task_subs.get(sid)
                    if not sub or not sub.submitted_at:
                        ps["file_missing"] += 1
                    else:
                        submitted_utc = (sub.submitted_at.replace(tzinfo=timezone.utc)
                                         if sub.submitted_at.tzinfo is None else
                                         sub.submitted_at.astimezone(timezone.utc))
                        if submitted_utc <= deadline_utc:
                            ps["file_ontime"] += 1
                        else:
                            ps["file_late"] += 1

        # Gán điểm trạng thái file cho từng trường
        for ps in per_school.values():
            ps["file_status"] = _score_from_counts(
                ps["file_ontime"], ps["file_late"], ps["file_missing"], ps["file_assigned"]
            )

    # ====== DATA REPORTS ======
    if kind in ("data", "both"):
        q = db.query(models.DataReport).filter(
            models.DataReport.deadline >= start_utc,
            models.DataReport.deadline <= end_utc
        )
        if school_year_id:
            q = q.filter(models.DataReport.school_year_id == school_year_id)
        reports = q.all()

        if reports:
            report_ids = [r.id for r in reports]
            entries = db.query(models.DataEntry)\
                        .filter(models.DataEntry.report_id.in_(report_ids)).all()
            # Map report -> {school_id: entry}
            entry_map: Dict[int, Dict[int, models.DataEntry]] = {r.id: {} for r in reports}
            for e in entries:
                entry_map.setdefault(e.report_id, {})[e.school_id] = e

            for report in reports:
                deadline_utc = (report.deadline.replace(tzinfo=timezone.utc)
                                if report.deadline.tzinfo is None else
                                report.deadline.astimezone(timezone.utc))
                assigned_school_ids = set(entry_map.get(report.id, {}).keys())

                for sid in assigned_school_ids:
                    if sid not in per_school:
                        continue
                    ps = per_school[sid]
                    ps["data_assigned"] += 1
                    entry = entry_map[report.id].get(sid)
                    if not entry or not entry.submitted_at:
                        ps["data_missing"] += 1
                    else:
                        submitted_utc = (entry.submitted_at.replace(tzinfo=timezone.utc)
                                         if entry.submitted_at.tzinfo is None else
                                         entry.submitted_at.astimezone(timezone.utc))
                        if submitted_utc <= deadline_utc:
                            ps["data_ontime"] += 1
                        else:
                            ps["data_late"] += 1

        # Gán điểm trạng thái data cho từng trường
        for ps in per_school.values():
            ps["data_status"] = _score_from_counts(
                ps["data_ontime"], ps["data_late"], ps["data_missing"], ps["data_assigned"]
            )

    # ====== HỢP NHẤT KẾT QUẢ THEO 'kind' ======
    ontime, late, missing = [], [], []

    def _push(target_list, ps, assigned_total, ontime_total, late_total, missing_total):
        target_list.append({
            "id": ps["id"],
            "name": ps["name"],
            "assigned_count": assigned_total,
            "ontime_count": ontime_total,
            "late_count": late_total,
            "missing_count": missing_total,
        })

    for ps in per_school.values():
        if kind == "file":
            if ps["file_assigned"] == 0:
                continue
            score = ps["file_status"]
            if score == 2:
                _push(ontime, ps, ps["file_assigned"], ps["file_ontime"], ps["file_late"], ps["file_missing"])
            elif score == 1:
                _push(late, ps, ps["file_assigned"], ps["file_ontime"], ps["file_late"], ps["file_missing"])
            elif score == 0:
                _push(missing, ps, ps["file_assigned"], ps["file_ontime"], ps["file_late"], ps["file_missing"])

        elif kind == "data":
            if ps["data_assigned"] == 0:
                continue
            score = ps["data_status"]
            if score == 2:
                _push(ontime, ps, ps["data_assigned"], ps["data_ontime"], ps["data_late"], ps["data_missing"])
            elif score == 1:
                _push(late, ps, ps["data_assigned"], ps["data_ontime"], ps["data_late"], ps["data_missing"])
            elif score == 0:
                _push(missing, ps, ps["data_assigned"], ps["data_ontime"], ps["data_late"], ps["data_missing"])

        else:  # kind == "both"
            # Gộp theo trạng thái "tốt nhất" giữa file và data
            score = max(ps["file_status"], ps["data_status"])
            assigned_total = ps["file_assigned"] + ps["data_assigned"]
            ontime_total = ps["file_ontime"] + ps["data_ontime"]
            late_total = ps["file_late"] + ps["data_late"]
            missing_total = ps["file_missing"] + ps["data_missing"]

            if assigned_total == 0:
                continue

            if score == 2:
                _push(ontime, ps, assigned_total, ontime_total, late_total, missing_total)
            elif score == 1:
                _push(late, ps, assigned_total, ontime_total, late_total, missing_total)
            else:  # 0 hoặc -1 (không nên có -1 nếu assigned_total > 0)
                _push(missing, ps, assigned_total, ontime_total, late_total, missing_total)

    # Sắp xếp theo tên
    ontime.sort(key=lambda x: x["name"])
    late.sort(key=lambda x: x["name"])
    missing.sort(key=lambda x: x["name"])

    return {"ontime": ontime, "late": late, "missing": missing}


def get_data_entry_for_school(db: Session, report_id: int, school_id: int) -> Optional[models.DataEntry]:
    """Lấy bản ghi nộp báo cáo nhập liệu của một trường cụ thể."""
    return db.query(models.DataEntry).filter(
        models.DataEntry.report_id == report_id,
        models.DataEntry.school_id == school_id
    ).first()

def get_data_report_with_schema(db: Session, report_id: int) -> Dict[str, Any]:
    """
    Trả về payload schema cho DataReport kèm 'description' (nội dung yêu cầu) và 'attachment_url' (nếu có).
    - An toàn: nếu model chưa có cột 'description' hoặc 'attachment_url' thì trả về chuỗi rỗng / None.
    - Không thay đổi cấu trúc cũ: 'columns_schema' giữ nguyên như trước để client hiển thị bảng nhập liệu.
    """
    report = db.query(models.DataReport).filter(models.DataReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo nhập liệu.")

    # columns_schema có thể là list/dict JSON tuỳ thiết kế cũ
    columns_schema = report.columns_schema if hasattr(report, "columns_schema") else []

    # Lấy mô tả yêu cầu nếu có cột; nếu chưa có cột -> trả ""
    description = getattr(report, "description", "") or ""
    
    # Lấy link hướng dẫn nếu DataReport có cột này (không bắt buộc)
    attachment_url = getattr(report, "attachment_url", None)

    # Một số DB để tên là 'name' thay vì 'title'
    title = getattr(report, "title", None) or getattr(report, "name", f"Báo cáo #{report.id}")

    return {
        "id": report.id,
        "title": title,
        "deadline": report.deadline,
        "columns_schema": columns_schema,
        "description": description,
        "attachment_url": attachment_url,
    }
