# client_app.py
import sys
import os
import json
import webbrowser
import shutil
from datetime import datetime
from typing import Callable, Tuple, List, Dict, Any

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit, QLabel,
    QFileDialog, QHeaderView, QFrame, QTabWidget, QListWidget, QListWidgetItem,
    QProgressBar, QSplitter, QTextEdit
)
from PySide6.QtCore import Qt, QDateTime, Signal, QUrl, QByteArray, QThread, QObject, QUrlQuery, Slot
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from spreadsheet_widget import SpreadsheetWidget, ColumnSpec

API_URL = "https://auto-report-backend.onrender.com"

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller tạo một thư mục tạm và lưu đường dẫn trong _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
    
def get_app_data_path(filename):
    app_data_dir = os.path.join(os.path.expanduser('~'), '.auto_report_client')
    os.makedirs(app_data_dir, exist_ok=True)
    return os.path.join(app_data_dir, filename)

CONFIG_FILE = get_app_data_path("client_config.json")
DRIVE_TOKEN_FILE = get_app_data_path('token.json')
CREDENTIALS_FILE = get_app_data_path('credentials_oauth.json')
SA_KEY_FILE = get_app_data_path('service_account.json')

GDRIVE_SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/userinfo.email', 'openid']

def handle_api_error(self, status_code, response_text, context_message):
    detail = response_text
    try: detail = json.loads(response_text).get('detail', response_text)
    except json.JSONDecodeError: pass
    QMessageBox.critical(self, "Lỗi", f"{context_message}\nLỗi từ server (Code: {status_code}): {detail}")

def get_drive_service() -> Tuple[object, str | None]:
    sa_path_appdata = get_app_data_path('service_account.json')
    sa_path_local = 'service_account.json'
    final_sa_path = None
    if os.path.exists(sa_path_appdata): final_sa_path = sa_path_appdata
    elif os.path.exists(sa_path_local):
        try: shutil.copy(sa_path_local, sa_path_appdata); final_sa_path = sa_path_appdata
        except Exception as e: print(f"Không thể sao chép 'service_account.json': {e}")
    if final_sa_path and os.path.exists(final_sa_path):
        try:
            creds = service_account.Credentials.from_service_account_file(final_sa_path, scopes=GDRIVE_SCOPES)
            service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            print("Đang sử dụng Service Account."); return service, None
        except Exception as e: print(f"Lỗi đọc file Service Account: {e}. Fallback về OAuth.")
    print("Chuyển sang xác thực OAuth người dùng.")
    if not os.path.exists(CREDENTIALS_FILE):
        source_path = 'credentials_oauth.json' 
        if os.path.exists(source_path): shutil.copy(source_path, CREDENTIALS_FILE)
        else: raise FileNotFoundError("Không tìm thấy 'credentials_oauth.json' hoặc 'service_account.json'.")
    creds = None
    if os.path.exists(DRIVE_TOKEN_FILE): creds = Credentials.from_authorized_user_file(DRIVE_TOKEN_FILE, GDRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GDRIVE_SCOPES)
            creds = flow.run_local_server(port=0) 
        with open(DRIVE_TOKEN_FILE, 'w') as token: token.write(creds.to_json())
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    user_info = build('oauth2', 'v2', credentials=creds).userinfo().get().execute()
    return service, user_info.get('email')

class UploadWorker(QObject):
    finished = Signal(str); error = Signal(str); progress = Signal(int)
    def __init__(self, service, file_path, folder_id):
        super().__init__(); self.service = service; self.file_path = file_path; self.folder_id = folder_id
    def run(self):
        try:
            if not self.folder_id: raise ValueError("Lỗi: Không có ID thư mục.")
            file_metadata = {'name': os.path.basename(self.file_path), 'parents': [self.folder_id]}
            media = MediaFileUpload(self.file_path, resumable=True)
            request = self.service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: self.progress.emit(int(status.progress() * 100))
            self.finished.emit(response.get('webViewLink'))
        except Exception as e: self.error.emit(str(e))

class ListItemWidget(QWidget):
    def __init__(self, item_id, title, deadline, attachment_url, is_submitted, is_reminded, is_locked, parent=None):
        super().__init__(parent)
        self.item_id = item_id

        # Layout chính, ngang
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # === Cột trái: Tiêu đề và Hạn chót ===
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # --- Logic xử lý văn bản và màu sắc ---
        title_text = f"<b>ID {item_id}: {title}</b>"
        if attachment_url:
            title_text += " 📎"
            
        status_text = "Đã hoàn thành" if is_submitted else "Chưa thực hiện"
        status_color = '#27ae60' if is_submitted else '#e74c3c'
        
        if is_locked and not is_submitted:
            title_text = f"<b>ID {item_id}: {title} (Đã khóa)</b>"
            status_text = "Đã khóa"
            status_color = '#7f8c8d'
            self.setStyleSheet("background-color: #f2f2f2; border-radius: 5px;")
        elif is_reminded and not is_submitted:
            self.setStyleSheet("background-color: #fff3cd; border-radius: 5px;")
            title_text = f"<b>ID {item_id}: {title} (Cần chú ý!)</b>"
        # --- Kết thúc logic ---

        title_label = QLabel(title_text)
        title_label.setWordWrap(True)
        
        deadline_label = QLabel(f"Hạn chót: {deadline}")
        deadline_label.setStyleSheet("color: #555;")

        info_layout.addWidget(title_label)
        info_layout.addWidget(deadline_label)
        info_layout.addStretch()

        # === Cột phải: Trạng thái và Nút hành động ===
        action_layout = QVBoxLayout()
        action_layout.setAlignment(Qt.AlignCenter)
        
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        action_layout.addWidget(status_label)
        
        if attachment_url:
            # Rút ngắn văn bản và điều chỉnh kích thước nút
            btn = QPushButton("Xem File")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("padding: 5px 12px; font-size: 13px;")
            btn.clicked.connect(lambda _, url=attachment_url: webbrowser.open(url))
            action_layout.addWidget(btn)
        
        # Thêm các cột vào layout chính
        layout.addLayout(info_layout, 1)  # Cột trái sẽ co giãn
        layout.addLayout(action_layout, 0) # Cột phải chỉ chiếm không gian cần thiết



class FileTaskItemWidget(QWidget):
    def __init__(self, title, deadline_dt, is_submitted, is_reminded, is_locked, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True) # CHO PHÉP TỰ ĐỘNG XUỐNG DÒNG
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.title_label)

        bottom_layout = QHBoxLayout()
        
        deadline_str = deadline_dt.strftime("%H:%M %d/%m/%Y")
        self.deadline_label = QLabel(f"Hạn: {deadline_str}")
        
        if not is_submitted and datetime.now() > deadline_dt:
             self.deadline_label.setText(f"<b>QUÁ HẠN: {deadline_str}</b>")
             self.deadline_label.setStyleSheet("color: #e74c3c;")
        
        bottom_layout.addWidget(self.deadline_label)
        bottom_layout.addStretch()

        if is_locked and not is_submitted:
            status_text, status_color = "Đã khóa", "#7f8c8d"
            self.setStyleSheet("background-color: #f2f2f2; border-radius: 5px;")
        elif is_submitted:
            status_text, status_color = "✓ Đã hoàn thành", "#27ae60"
        elif is_reminded:
            status_text, status_color = "CHƯA NỘP (Nhắc nhở)", "#f39c12"
            self.setStyleSheet("background-color: #fff3cd; border-radius: 5px;")
        else:
            status_text, status_color = "Chưa thực hiện", "#e74c3c"

        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        bottom_layout.addWidget(self.status_label)

        layout.addLayout(bottom_layout)
        
class ClientWindow(QMainWindow):
    authentication_successful = Signal(str)
    upload_complete_signal = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.network_manager = QNetworkAccessManager(self)
        self.setWindowTitle("Hệ thống Báo cáo - phiên bản dành cho trường học")
        self.setWindowIcon(QIcon(resource_path('baocao.ico')))
        self.setGeometry(200, 200, 1100, 800)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #f8f9fa; }
            QFrame#card { background-color: white; border-radius: 8px; border: 1px solid #e9ecef; padding: 20px; }
            QLineEdit { border: 1px solid #ced4da; border-radius: 4px; padding: 8px; font-size: 15px; }
            QPushButton { background-color: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; font-weight: bold; font-size: 15px; }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton:disabled { background-color: #6c757d; }
            QLabel { color: #212529; font-size: 15px; }
            QTableWidget, QListWidget, QTextEdit { border: 1px solid #dee2e6; border-radius: 4px; }
            QHeaderView::section { background-color: #f1f3f5; padding: 8px; font-weight: bold; }
            QTabWidget::pane { border-top: 1px solid #dee2e6; }
            QTabBar::tab { 
                background-color: #f8f9fa; color: #495057;
                border: 1px solid #dee2e6; border-bottom: none; 
                padding: 10px 20px; font-weight: bold;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { 
                background-color: #007bff; color: white;
                border-color: #007bff;
            }
            QTabBar::tab:!selected:hover { background-color: #e9ecef; }
        """)

        self.api_key = self.load_api_key()
        self.drive_service = None
        self.user_email = None
        self.current_displayed_report_id = None

        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        self.create_api_key_ui()
        self.tab_widget = QTabWidget()
        self.file_submission_tab = QWidget()
        self.data_entry_tab = QWidget()
        self.tab_widget.addTab(self.file_submission_tab, "NỘP FILE BÁO CÁO")
        self.tab_widget.addTab(self.data_entry_tab, "NHẬP LIỆU BÁO CÁO")
        self.layout.addWidget(self.tab_widget)
        
        self.create_file_submission_ui()
        self.create_data_entry_ui()

        self.authentication_successful.connect(self.on_authentication_success)
        self.upload_complete_signal.connect(self.handle_final_submission)

        self.update_ui_for_api_key()
        if self.api_key:
            self.fetch_school_info()
        else:
            QMessageBox.information(self, "Chào mừng", "Vui lòng nhập Mã API được cung cấp và nhấn 'Lưu'.")

    def _handle_reply(self, reply: QNetworkReply, on_success: Callable, on_error: Callable):
        try:
            if reply.error() == QNetworkReply.NoError:
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code is None:
                    status_code = 200
                raw = bytes(reply.readAll())
                if 200 <= int(status_code) < 300:
                    try:
                        text = raw.decode('utf-8') if raw else ''
                        on_success(json.loads(text) if text else {}, {})
                    except Exception:
                        on_error(int(status_code), "Lỗi giải mã JSON từ server.")
                else:
                    on_error(int(status_code), raw.decode('utf-8', errors='ignore'))
            else:
                on_error(0, f"Lỗi mạng: {reply.errorString()}")
        finally:
            reply.deleteLater()

    def api_get(self, endpoint: str, on_success: Callable, on_error: Callable,
                headers: dict = None, params: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        if params:
            q = QUrlQuery()
            for k, v in params.items():
                if v is not None:
                    q.addQueryItem(k, str(v))
            url.setQuery(q)

        def do_get(url_obj: QUrl, redirects_left: int = 5):
            req = QNetworkRequest(url_obj)
            req.setRawHeader(b"Accept", b"application/json,*/*")
            req.setRawHeader(b"User-Agent", b"ClientApp/1.0")
            if headers:
                for k, v in headers.items():
                    req.setRawHeader(k.encode(), v.encode())

            reply = self.network_manager.get(req)

            def finished():
                if reply.error() != QNetworkReply.NoError:
                    self._handle_reply(reply, on_success, on_error)
                    return

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code and 300 <= int(status_code) < 400 and redirects_left > 0:
                    red_attr = getattr(QNetworkRequest, "RedirectionTargetAttribute", None)
                    target = reply.attribute(red_attr) if red_attr is not None else None
                    reply.readAll()
                    reply.deleteLater()
                    if target:
                        new_url = url_obj.resolved(target) if isinstance(target, QUrl) else QUrl(str(target))
                        do_get(new_url, redirects_left - 1)
                        return

                self._handle_reply(reply, on_success, on_error)

            reply.finished.connect(finished)

        do_get(url)

    def api_post(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable,
                 headers: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")

        def do_post(url_obj: QUrl, redirects_left: int = 5):
            req = QNetworkRequest(url_obj)
            req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            req.setRawHeader(b"Accept", b"application/json,*/*")
            req.setRawHeader(b"User-Agent", b"ClientApp/1.0")
            if headers:
                for k, v in headers.items():
                    req.setRawHeader(k.encode(), v.encode())

            payload = QByteArray(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            reply = self.network_manager.post(req, payload)

            def finished():
                if reply.error() != QNetworkReply.NoError:
                    self._handle_reply(reply, on_success, on_error)
                    return

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code and 300 <= int(status_code) < 400 and redirects_left > 0:
                    red_attr = getattr(QNetworkRequest, "RedirectionTargetAttribute", None)
                    target = reply.attribute(red_attr) if red_attr is not None else None
                    reply.readAll()
                    reply.deleteLater()
                    if target:
                        new_url = url_obj.resolved(target) if isinstance(target, QUrl) else QUrl(str(target))
                        do_post(new_url, redirects_left - 1)
                        return

                self._handle_reply(reply, on_success, on_error)

            reply.finished.connect(finished)

        do_post(url)

    def create_api_key_ui(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Mã API của trường:"))
        self.api_key_input = QLineEdit()
        self.save_api_key_button = QPushButton("Lưu")
        self.edit_api_key_button = QPushButton("Thay đổi")
        input_layout.addWidget(self.api_key_input)
        input_layout.addWidget(self.save_api_key_button)
        input_layout.addWidget(self.edit_api_key_button)
        self.school_info_label = QLabel("Trạng thái: Chưa cấu hình.")
        self.school_info_label.setStyleSheet("font-style: italic; color: #555;")
        layout.addLayout(input_layout)
        layout.addWidget(self.school_info_label)
        self.layout.addWidget(card)
        self.save_api_key_button.clicked.connect(self.save_api_key_handler)
        self.edit_api_key_button.clicked.connect(self.edit_api_key_handler)

    def create_file_submission_ui(self):
        layout = QVBoxLayout(self.file_submission_tab)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        tasks_card = QFrame()
        tasks_card.setObjectName("card")
        tasks_layout = QVBoxLayout(tasks_card)
        tasks_layout.addWidget(QLabel("<b>Danh sách Công việc</b>"))
        self.load_ft_button = QPushButton("Làm mới danh sách")
        self.load_ft_button.clicked.connect(self.refresh_data)
        tasks_layout.addWidget(self.load_ft_button)
        self.ft_list_widget = QListWidget()
        self.ft_list_widget.currentItemChanged.connect(self.display_file_task_details)
        tasks_layout.addWidget(self.ft_list_widget)
        splitter.addWidget(tasks_card)
        details_card = QFrame()
        details_card.setObjectName("card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setAlignment(Qt.AlignTop)
        details_layout.addWidget(QLabel("<b>Chi tiết Công việc</b>"))
        self.ft_details_title = QLabel("Vui lòng chọn một công việc từ danh sách")
        self.ft_details_title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        self.ft_details_title.setWordWrap(True)
        details_layout.addWidget(self.ft_details_title)
        self.ft_details_content = QTextEdit()
        self.ft_details_content.setReadOnly(True)
        details_layout.addWidget(self.ft_details_content)
        self.ft_details_attachment_btn = QPushButton("Mở/Tải File Đính Kèm")
        self.ft_details_attachment_btn.clicked.connect(self.open_ft_attachment)
        self.ft_details_attachment_btn.hide()
        details_layout.addWidget(self.ft_details_attachment_btn)
        details_layout.addStretch(1)
        submit_group = QFrame()
        submit_group.setFrameShape(QFrame.StyledPanel)
        submit_layout = QVBoxLayout(submit_group)
        submit_layout.addWidget(QLabel("<b>Nộp báo cáo</b>"))
        self.submit_file_button = QPushButton("Nộp file cho công việc đã chọn")
        self.ft_status_label = QLabel("Sẵn sàng.")
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        submit_layout.addWidget(self.submit_file_button)
        submit_layout.addWidget(self.ft_status_label)
        submit_layout.addWidget(self.progress_bar)
        details_layout.addWidget(submit_group)
        splitter.addWidget(details_card)
        splitter.setSizes([450, 650])
        self.submit_file_button.clicked.connect(self.submit_file_handler)

    def create_data_entry_ui(self):
        main_layout = QHBoxLayout(self.data_entry_tab)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("<b>Danh sách Báo cáo cần nhập liệu</b>"))
        self.load_dr_button = QPushButton("Làm mới")
        self.load_dr_button.clicked.connect(self.load_data_reports)
        list_layout.addWidget(self.load_dr_button)
        self.dr_list_widget = QListWidget()
        self.dr_list_widget.currentItemChanged.connect(self.display_data_report_sheet)
        list_layout.addWidget(self.dr_list_widget)
        main_layout.addWidget(list_card)
        self.spreadsheet_container = QFrame()
        self.spreadsheet_container.setObjectName("card")
        self.spreadsheet_layout = QVBoxLayout(self.spreadsheet_container)
        self.dr_status_label = QLabel("Vui lòng chọn một báo cáo từ danh sách bên trái.")
        self.dr_status_label.setAlignment(Qt.AlignCenter)
        self.spreadsheet_layout.addWidget(self.dr_status_label)
        main_layout.addWidget(self.spreadsheet_container, 1)

    # --- Logic & Event Handlers ---
    def load_api_key(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f: return json.load(f).get("api_key")
        except (IOError, json.JSONDecodeError): return None
        return None

    def save_api_key_handler(self):
        key = self.api_key_input.text().strip()
        if not key: QMessageBox.warning(self, "Lỗi", "Mã API không được để trống."); return
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump({"api_key": key}, f)
            self.api_key = key
            QMessageBox.information(self, "Thành công", "Đã lưu Mã API.")
            self.update_ui_for_api_key()
            self.fetch_school_info()
        except IOError:
            QMessageBox.critical(self, "Lỗi", "Không thể ghi file cấu hình.")

    def edit_api_key_handler(self):
        self.api_key = None
        self.school_info_label.setText("Trạng thái: Chưa cấu hình.")
        self.update_ui_for_api_key()

    def update_ui_for_api_key(self):
        has_key = bool(self.api_key)
        self.api_key_input.setText(self.api_key if has_key else "")
        self.api_key_input.setReadOnly(has_key)
        self.save_api_key_button.setVisible(not has_key)
        self.edit_api_key_button.setVisible(has_key)
        self.tab_widget.setEnabled(has_key)

    def fetch_school_info(self):
        if not self.api_key: return
        self.school_info_label.setText("Đang xác thực API Key...")
        def on_success(data, _):
            self.authentication_successful.emit(data.get('name', 'Không xác định'))
        def on_error(s, e): self.school_info_label.setText("Mã API không hợp lệ."); self.edit_api_key_handler()
        self.api_get("/schools/me", on_success, on_error, headers={"x-api-key": self.api_key})

    def on_authentication_success(self, school_name):
        self.school_info_label.setText(f"Đang làm việc với tư cách: Trường {school_name}"); self.refresh_data()

    def refresh_data(self):
        self.load_file_tasks()
        self.load_data_reports()

    def handle_final_submission(self, task_id, file_url):
        self.ft_status_label.setText("Đang hoàn tất nộp bài...")
        payload = {"task_id": task_id, "file_url": file_url}
        def on_success(d, h):
            QMessageBox.information(self, "Thành công", "Nộp file thành công!")
            self.ft_status_label.setText("Sẵn sàng.")
            self.load_file_tasks()
        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể hoàn tất việc nộp bài.")
            self.ft_status_label.setText("Lỗi khi hoàn tất.")
        self.api_post("/file-submissions/", payload, on_success, on_error, headers={"x-api-key": self.api_key})

    def display_file_task_details(self, current_item, previous_item):
        if not current_item:
            self.ft_details_title.setText("Vui lòng chọn một công việc từ danh sách")
            self.ft_details_content.setText("")
            self.ft_details_attachment_btn.hide()
            return
        task_data = current_item.data(Qt.UserRole)
        self.ft_details_title.setText(task_data.get('title', 'N/A'))
        self.ft_details_content.setText(task_data.get('content', 'Không có nội dung chi tiết.'))
        if task_data.get("attachment_url"):
            self.ft_details_attachment_btn.show()
        else:
            self.ft_details_attachment_btn.hide()

    def open_ft_attachment(self):
        current_item = self.ft_list_widget.currentItem()
        if not current_item: return
        task_data = current_item.data(Qt.UserRole)
        url = task_data.get("attachment_url")
        if url: webbrowser.open(url)
       
    def load_file_tasks(self):
        if not self.api_key: return
        self.load_ft_button.setDisabled(True)
        self.load_ft_button.setText("Đang tải...")
        def on_success(tasks, _):
            self.ft_list_widget.clear()
            self.display_file_task_details(None, None)
            if not tasks:
                placeholder_item = QListWidgetItem("Không có công việc nào.")
                placeholder_item.setFlags(Qt.NoItemFlags)
                self.ft_list_widget.addItem(placeholder_item)
            tasks.sort(key=lambda t: t['deadline'], reverse=True)
            for task in tasks:
                deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%dT%H:%M:%S")
                is_submitted = task.get('is_submitted', False)
                is_reminded = task.get('is_reminded', False)
                is_locked = task.get('is_locked', False)
                list_item = QListWidgetItem(self.ft_list_widget)
                list_item.setData(Qt.UserRole, task)
                item_widget = FileTaskItemWidget(
                    task['title'], deadline_dt,
                    is_submitted, is_reminded, is_locked
                )
                list_item.setSizeHint(item_widget.sizeHint())
                self.ft_list_widget.setItemWidget(list_item, item_widget)
            self.load_ft_button.setDisabled(False)
            self.load_ft_button.setText("Làm mới danh sách")
        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể tải công việc.")
            self.load_ft_button.setDisabled(False)
            self.load_ft_button.setText("Làm mới")
        self.api_get("/file-tasks/", on_success, on_error, headers={"x-api-key": self.api_key})
        
    def submit_file_handler(self):
        current_item = self.ft_list_widget.currentItem()
        if not current_item: 
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một công việc."); return
        task_data = current_item.data(Qt.UserRole)
        task_id = task_data['id']
        is_locked = task_data.get('is_locked', False)
        is_submitted = task_data.get('is_submitted', False)
        if is_locked:
            QMessageBox.warning(self, "Admin đã khoá", "Yêu cầu này đã bị quản trị viên khóa, không thể nộp bài.")
            return
        if is_submitted and QMessageBox.question(self, 'Xác nhận', "Đã nộp. Nộp lại file khác?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.No: return
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file để nộp");
        if not file_path: return
        self.submit_file_button.setDisabled(True)
        self.ft_status_label.setText("Đang chuẩn bị...")
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        try:
            self.drive_service, self.user_email = get_drive_service()
            def on_folder_id_success(data, headers):
                folder_id = data.get("folder_id")
                self.upload_thread = QThread()
                self.upload_worker = UploadWorker(self.drive_service, file_path, folder_id)
                self.upload_worker.moveToThread(self.upload_thread)
                self.upload_thread.started.connect(self.upload_worker.run)
                self.upload_worker.finished.connect(self.on_upload_finished)
                self.upload_worker.error.connect(self.on_upload_error)
                self.upload_worker.progress.connect(self.on_upload_progress)
                self.upload_worker.finished.connect(self.upload_thread.quit)
                self.upload_worker.finished.connect(self.upload_worker.deleteLater)
                self.upload_thread.finished.connect(self.upload_thread.deleteLater)
                self.upload_thread.start()
                self.ft_status_label.setText("Đang tải file lên Google Drive...")
            def on_folder_id_error(s, e):
                handle_api_error(self, s, e, "Không thể lấy thư mục nộp bài.")
                self.submit_file_button.setDisabled(False)
            params = {"user_email": self.user_email} if self.user_email else {}
            self.api_get(f"/file-tasks/{task_id}/upload-folder", on_folder_id_success, on_folder_id_error, headers={"x-api-key": self.api_key}, params=params)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi Google Drive", f"Không thể kết nối: {e}")
            self.submit_file_button.setDisabled(False)

    def on_upload_progress(self, percent): self.progress_bar.setValue(percent)
    def on_upload_error(self, error_msg):
        QMessageBox.critical(self, "Lỗi tải file", f"Lỗi: {error_msg}")
        self.ft_status_label.setText("Lỗi tải file.")
        self.submit_file_button.setDisabled(False)
        self.progress_bar.hide()

    def on_upload_finished(self, file_url):
        current_item = self.ft_list_widget.currentItem()
        if not current_item: return
        task_id = current_item.data(Qt.UserRole)['id']
        self.upload_complete_signal.emit(task_id, file_url)
        self.submit_file_button.setDisabled(False)
        self.progress_bar.hide()
    
    @Slot()
    def load_data_reports(self):
        if not self.api_key: return
        self.load_dr_button.setDisabled(True)
        self.load_dr_button.setText("Đang tải...")

        def on_success(reports, _):
            self.dr_list_widget.clear()
            self.display_data_report_sheet(None, None)
            
            if not reports:
                placeholder_item = QListWidgetItem("Không có báo cáo nào.")
                placeholder_item.setFlags(Qt.NoItemFlags)
                self.dr_list_widget.addItem(placeholder_item)
            else:
                reports.sort(key=lambda r: r.get('deadline', ''), reverse=True)
                for report in reports:
                    deadline_str = "N/A"
                    if report.get('deadline'):
                        try:
                            deadline_dt = datetime.strptime(report['deadline'], "%Y-%m-%dT%H:%M:%S")
                            deadline_str = deadline_dt.strftime("%H:%M %d/%m/%Y")
                        except ValueError:
                            deadline_str = report['deadline']
                    
                    is_submitted = report.get('is_submitted', False)
                    is_reminded = report.get('is_reminded', False)
                    is_locked = report.get('is_locked', False)
                    
                    list_item = QListWidgetItem(self.dr_list_widget)
                    list_item.setData(Qt.UserRole, report)
                    
                    item_widget = ListItemWidget(
                        item_id=report['id'],
                        title=report['title'],
                        deadline=deadline_str,
                        attachment_url=report.get('attachment_url'),
                        is_submitted=is_submitted,
                        is_reminded=is_reminded,
                        is_locked=is_locked
                    )
                    list_item.setSizeHint(item_widget.sizeHint())
                    self.dr_list_widget.setItemWidget(list_item, item_widget)
                    
            self.load_dr_button.setDisabled(False)
            self.load_dr_button.setText("Làm mới")

        def on_error(s, e):
            handle_api_error(self, s, e, "Lỗi tải danh sách báo cáo.")
            self.load_dr_button.setDisabled(False)
            self.load_dr_button.setText("Làm mới")

        self.api_get("/data-reports/", on_success, on_error, headers={"x-api-key": self.api_key})

    @Slot(QListWidgetItem, QListWidgetItem)
    def display_data_report_sheet(self, current_item, previous_item):
        # Xóa layout cũ một lần duy nhất
        for i in reversed(range(self.spreadsheet_layout.count())):
            widget = self.spreadsheet_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        if not current_item:
            self.current_displayed_report_id = None
            self.dr_status_label = QLabel("Vui lòng chọn một báo cáo từ danh sách bên trái.")
            self.dr_status_label.setAlignment(Qt.AlignCenter)
            self.spreadsheet_layout.addWidget(self.dr_status_label)
            return

        report_data = current_item.data(Qt.UserRole)
        report_id = report_data['id']
        self.current_displayed_report_id = report_id
        is_locked = report_data.get('is_locked', False)

        title_label = QLabel(report_data.get('title', 'N/A'))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        title_label.setWordWrap(True)
        self.spreadsheet_layout.addWidget(title_label)
        
        dynamic_content_widget = QWidget()
        self.dynamic_layout = QVBoxLayout(dynamic_content_widget)
        self.spreadsheet_layout.addWidget(dynamic_content_widget, 1)

        loading_label = QLabel("Đang tải chi tiết báo cáo và biểu mẫu...")
        self.dynamic_layout.addWidget(loading_label)

        def on_schema_error(s, e):
            if report_id != self.current_displayed_report_id: return
            try:
                for i in reversed(range(self.dynamic_layout.count())): self.dynamic_layout.itemAt(i).widget().setParent(None)
                error_label = QLabel(f"Lỗi tải chi tiết báo cáo: {e}")
                self.dynamic_layout.addWidget(error_label)
            except RuntimeError:
                print("Race condition caught: on_schema_error")

        def on_schema_success(schema_data, _):
            if report_id != self.current_displayed_report_id: return
            try:
                for i in reversed(range(self.dynamic_layout.count())): self.dynamic_layout.itemAt(i).widget().setParent(None)

                description = schema_data.get("description")
                if description:
                    desc_label = QLabel("<b>Nội dung yêu cầu:</b>")
                    desc_text = QTextEdit(description)
                    desc_text.setReadOnly(True)
                    desc_text.setMaximumHeight(150)
                    self.dynamic_layout.addWidget(desc_label)
                    self.dynamic_layout.addWidget(desc_text)
                    
                attachment_url = schema_data.get("attachment_url")
                if attachment_url:
                    attachment_btn = QPushButton("Mở/Tải File Hướng Dẫn")
                    attachment_btn.clicked.connect(lambda: webbrowser.open(attachment_url))
                    self.dynamic_layout.addWidget(attachment_btn)

                separator = QFrame()
                separator.setFrameShape(QFrame.HLine); separator.setFrameShadow(QFrame.Sunken)
                self.dynamic_layout.addWidget(separator)
                
                def on_submission_error(s, e):
                    if report_id != self.current_displayed_report_id: return
                    try:
                        error_label = QLabel(f"Lỗi tải dữ liệu đã nộp: {e}")
                        self.dynamic_layout.addWidget(error_label)
                    except RuntimeError:
                        print("Race condition caught: on_submission_error")

                def on_submission_success(submission_data, _):
                    if report_id != self.current_displayed_report_id: return
                    try:
                        columns = [ColumnSpec(**c) for c in schema_data["columns_schema"]]
                        
                        if is_locked and not report_data.get('is_submitted', False):
                            locked_label = QLabel("🔴 Admin đã khoá báo cáo này. Không thể nhập liệu.")
                            locked_label.setAlignment(Qt.AlignCenter)
                            locked_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px; margin: 10px;")
                            self.dynamic_layout.addWidget(locked_label)

                        sheet = SpreadsheetWidget(columns, self)
                        sheet.set_data(submission_data.get("data", []))
                        
                        def save_data(records):
                            def on_save_success(d, h): 
                                QMessageBox.information(self, "Thành công", "Đã nộp báo cáo và lưu dữ liệu thành công!")
                                # Tải lại danh sách báo cáo để cập nhật trạng thái
                                self.load_data_reports()
                                # Xóa lựa chọn hiện tại để làm mới giao diện chi tiết
                                # và buộc người dùng thấy trạng thái đã được cập nhật trong danh sách.
                                self.dr_list_widget.setCurrentRow(-1)
                            def on_save_error(s, e): handle_api_error(self, s, e, "Lỗi lưu dữ liệu.")
                            self.api_post(f"/data-reports/{report_id}/submit", {"data": records}, on_save_success, on_save_error, headers={"x-api-key": self.api_key})
                        
                        sheet.saved.connect(save_data)
                        self.dynamic_layout.addWidget(sheet)
                        if is_locked: sheet.setEnabled(False)
                    except RuntimeError:
                        print("Race condition caught: on_submission_success")

                self.api_get(f"/data-reports/{report_id}/my-submission", on_submission_success, on_submission_error, headers={"x-api-key": self.api_key})
            except RuntimeError:
                print("Race condition caught: on_schema_success")

        self.api_get(f"/data-reports/{report_id}/schema", on_schema_success, on_schema_error, headers={"x-api-key": self.api_key})

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())

