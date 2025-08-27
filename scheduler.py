# scheduler.py
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
import crud, models
from email_sender import send_report_email

ADMIN_EMAIL = "autoreport@thcsnguyencongtrubh.edu.vn"

def check_deadlines_and_send_email():
    """
    Hàm này sẽ được chạy định kỳ.
    1. Tìm các yêu cầu (nộp file và nhập liệu) đã quá hạn và chưa gửi thông báo.
    2. Lấy báo cáo trạng thái của từng yêu cầu.
    3. Gửi email cho admin.
    4. Đánh dấu yêu cầu là đã gửi thông báo.
    """
    print(f"[{datetime.now()}] Bắt đầu kiểm tra deadline...")
    db: Session = SessionLocal()
    
    try:
        # --- 1. KIỂM TRA YÊU CẦU NỘP FILE QUÁ HẠN ---
        overdue_file_tasks = db.query(models.FileTask).filter(
            models.FileTask.deadline < datetime.utcnow(),
            models.FileTask.is_notification_sent == False
        ).all()

        for task in overdue_file_tasks:
            print(f"Phát hiện yêu cầu nộp file quá hạn: '{task.title}'")
            status_data = crud.get_file_task_status(db, task_id=task.id)
            
            subject = f"[BÁO CÁO TỰ ĐỘNG] Yêu cầu nộp file '{task.title}' đã quá hạn"
            
            body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <p>Chào Quản trị viên,</p>
                <p>Yêu cầu nộp file '<b>{task.title}</b>' đã quá hạn vào lúc {task.deadline.strftime('%H:%M %d/%m/%Y')}.</p>
            """
            
            not_submitted = status_data.get('not_submitted_schools')
            if not_submitted:
                body += "<p><b>Danh sách các đơn vị CHƯA NỘP:</b></p><ul style='list-style-type: square; padding-left: 20px;'>"
                for school in not_submitted:
                    body += f"<li>{school.name}</li>"
                body += "</ul>"
            else:
                body += "<p>Tất cả các đơn vị đã nộp báo cáo đầy đủ.</p>"

            body += """
                <br>
                <p>Trân trọng,<br>Hệ thống Báo cáo Tự động.</p>
            </body>
            </html>
            """
            
            send_report_email(ADMIN_EMAIL, subject, body)
            
            task.is_notification_sent = True
            db.commit()
            print(f"Đã cập nhật trạng thái thông báo cho yêu cầu nộp file '{task.title}'.")

        # --- 2. KIỂM TRA YÊU CẦU NHẬP LIỆU QUÁ HẠN ---
        overdue_data_reports = db.query(models.DataReport).filter(
            models.DataReport.deadline < datetime.utcnow(),
            models.DataReport.is_notification_sent == False
        ).all()

        for report in overdue_data_reports:
            print(f"Phát hiện yêu cầu nhập liệu quá hạn: '{report.title}'")
            status_data = crud.get_data_report_status(db, report_id=report.id)
            
            subject = f"[BÁO CÁO TỰ ĐỘNG] Yêu cầu nhập liệu '{report.title}' đã quá hạn"
            
            body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <p>Chào Quản trị viên,</p>
                <p>Yêu cầu nhập liệu '<b>{report.title}</b>' đã quá hạn vào lúc {report.deadline.strftime('%H:%M %d/%m/%Y')}.</p>
            """
            
            not_submitted = status_data.get('not_submitted_schools')
            if not_submitted:
                body += "<p><b>Danh sách các đơn vị CHƯA HOÀN THÀNH:</b></p><ul style='list-style-type: square; padding-left: 20px;'>"
                for school in not_submitted:
                    body += f"<li>{school.name}</li>"
                body += "</ul>"
            else:
                body += "<p>Tất cả các đơn vị đã hoàn thành nhập liệu.</p>"

            body += """
                <br>
                <p>Trân trọng,<br>Hệ thống Báo cáo Tự động.</p>
            </body>
            </html>
            """
            
            send_report_email(ADMIN_EMAIL, subject, body)
            
            report.is_notification_sent = True
            db.commit()
            print(f"Đã cập nhật trạng thái thông báo cho yêu cầu nhập liệu '{report.title}'.")

    finally:
        db.close()
