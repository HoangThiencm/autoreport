# scheduler.py (ĐÃ SỬA LỖI LOGIC)
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
import crud, models
from email_sender import send_report_email

ADMIN_EMAIL = "panh05702@gmail.com"

def check_deadlines_and_send_email():
    print(f"[{datetime.now()}] Bắt đầu kiểm tra deadline...")
    db: Session = SessionLocal()
    
    try:
        # --- KIỂM TRA YÊU CẦU NỘP FILE QUÁ HẠN ---
        overdue_file_tasks = db.query(models.FileTask).filter(
            models.FileTask.deadline < datetime.utcnow(),
            models.FileTask.is_notification_sent == False
        ).all()

        for task in overdue_file_tasks:
            print(f"Phát hiện yêu cầu nộp file quá hạn: '{task.title}'")
            status_data = crud.get_file_task_status(db, task_id=task.id)
            subject = f"[BÁO CÁO TỰ ĐỘNG] Yêu cầu nộp file '{task.title}' đã quá hạn"
            # ... (Phần tạo body email giữ nguyên)
            body = f"""...""" # Giữ nguyên phần body của bạn
            
            # SỬA LỖI LOGIC: Chỉ cập nhật DB nếu gửi mail thành công
            if send_report_email(ADMIN_EMAIL, subject, body):
                task.is_notification_sent = True
                db.commit()
                print(f"Đã gửi mail và cập nhật trạng thái cho: '{task.title}'.")
            else:
                print(f"Gửi mail thất bại cho: '{task.title}'. Sẽ thử lại trong lần kiểm tra sau.")

        # --- KIỂM TRA YÊU CẦU NHẬP LIỆU QUÁ HẠN ---
        overdue_data_reports = db.query(models.DataReport).filter(
            models.DataReport.deadline < datetime.utcnow(),
            models.DataReport.is_notification_sent == False
        ).all()

        for report in overdue_data_reports:
            print(f"Phát hiện yêu cầu nhập liệu quá hạn: '{report.title}'")
            status_data = crud.get_data_report_status(db, report_id=report.id)
            subject = f"[BÁO CÁO TỰ ĐỘNG] Yêu cầu nhập liệu '{report.title}' đã quá hạn"
            # ... (Phần tạo body email giữ nguyên)
            body = f"""...""" # Giữ nguyên phần body của bạn

            # SỬA LỖI LOGIC: Chỉ cập nhật DB nếu gửi mail thành công
            if send_report_email(ADMIN_EMAIL, subject, body):
                report.is_notification_sent = True
                db.commit()
                print(f"Đã gửi mail và cập nhật trạng thái cho: '{report.title}'.")
            else:
                print(f"Gửi mail thất bại cho: '{report.title}'. Sẽ thử lại trong lần kiểm tra sau.")

    finally:
        db.close()