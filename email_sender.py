# email_sender.py
import base64
from email.mime.text import MIMEText
from googleapiclient.errors import HttpError

# Import hàm xác thực chung từ crud.py
from crud import _get_google_service

# Dòng "from email_sender import send_report_email" đã được XÓA ở đây vì nó gây ra lỗi

def send_report_email(recipient_email: str, subject: str, body: str):
    """Tạo và gửi email sử dụng Gmail API."""
    try:
        # Sử dụng hàm xác thực chung để lấy service Gmail
        service = _get_google_service('gmail', 'v1')
        
        message = MIMEText(body, 'html') # Cho phép gửi email dạng HTML để đẹp hơn
        message['To'] = recipient_email
        message['From'] = 'me'
        message['Subject'] = subject
        
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        create_message = {'raw': encoded_message}
        
        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        print(f"Đã gửi email báo cáo thành công. Message ID: {send_message['id']}")
        return True
    except HttpError as error:
        print(f'Lỗi khi gửi email: {error}')
        return False
