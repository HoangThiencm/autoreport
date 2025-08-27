# email_sender.py
import os.path
import base64
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Phạm vi (scope) chỉ yêu cầu quyền gửi mail
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
TOKEN_FILE = 'gmail_token.json' # Dùng file token riêng cho Gmail
CREDENTIALS_FILE = 'credentials_oauth.json'

def _get_gmail_service():
    """Xác thực người dùng và trả về đối tượng service của Gmail."""
    creds = None
    # Kiểm tra xem file token đã tồn tại chưa
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # Nếu chưa có credentials hợp lệ, yêu cầu người dùng đăng nhập
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"Không tìm thấy file '{CREDENTIALS_FILE}'. Vui lòng làm theo hướng dẫn ở Bước 1.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Lưu credentials cho những lần chạy sau
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
    return build('gmail', 'v1', credentials=creds)

def send_report_email(recipient_email: str, subject: str, body: str):
    """Tạo và gửi email sử dụng tài khoản cá nhân đã xác thực."""
    try:
        service = _get_gmail_service()
        
        message = MIMEText(body, 'html')
        message['To'] = recipient_email
        message['From'] = 'me' # 'me' ở đây sẽ là tài khoản bạn đã đăng nhập
        message['Subject'] = subject
        
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'raw': encoded_message}
        
        # userId="me" để chỉ tài khoản đã được xác thực
        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        print(f"Đã gửi email báo cáo thành công qua tài khoản cá nhân. Message ID: {send_message['id']}")
        return True
    except HttpError as error:
        print(f'Lỗi khi gửi email: {error}')
        return False
    except FileNotFoundError as e:
        print(f"Lỗi cấu hình: {e}")
        return False