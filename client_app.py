# client_app.py
import sys
import os
import json
import webbrowser
import shutil
from datetime import datetime
from typing import Callable, Tuple

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
    QProgressBar
)
from PySide6.QtCore import Qt, QDateTime, Signal, QUrl, QByteArray, QThread, QObject, QUrlQuery
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

API_URL = "https://auto-report-backend.onrender.com" 

# --- SỬA LỖI ĐÓNG GÓI EXE: Lưu file vào thư mục người dùng ---
def get_app_data_path(filename):
    """Lấy đường dẫn đầy đủ tới file trong thư mục cấu hình của ứng dụng."""
    # Tạo một thư mục ẩn tên là .auto_report_client trong thư mục home của người dùng
    # Ví dụ: C:/Users/HoangThien/.auto_report_client/
    app_data_dir = os.path.join(os.path.expanduser('~'), '.auto_report_client')
    os.makedirs(app_data_dir, exist_ok=True)
    return os.path.join(app_data_dir, filename)

# Tất cả các file cấu hình sẽ được đọc/ghi vào thư mục cố định này
CONFIG_FILE = get_app_data_path("client_config.json")
DRIVE_TOKEN_FILE = get_app_data_path('token.json')
CREDENTIALS_FILE = get_app_data_path('credentials_oauth.json')

# Scope đầy đủ và chính xác nhất để tránh lỗi
GDRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive', 
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def handle_api_error(self, status_code, response_text, context_message):
    detail = response_text
    try:
        error_data = json.loads(response_text)
        detail = error_data.get('detail', response_text)
    except json.JSONDecodeError:
        pass
    QMessageBox.critical(self, "Lỗi", f"{context_message}\nLỗi từ server (Code: {status_code}): {detail}")

# --- PHẦN LOGIC GOOGLE DRIVE ---
def get_drive_service() -> Tuple[object, str]:
    # Tự động sao chép file credentials nếu nó chưa tồn tại trong thư mục cấu hình
    if not os.path.exists(CREDENTIALS_FILE):
        # Tìm file credentials_oauth.json nằm bên cạnh file .exe
        source_path = 'credentials_oauth.json' 
        if os.path.exists(source_path):
            shutil.copy(source_path, CREDENTIALS_FILE)
        else:
            raise FileNotFoundError("Không tìm thấy file credentials_oauth.json. Vui lòng đặt file này bên cạnh file thực thi (.exe).")

    creds = None
    if os.path.exists(DRIVE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(DRIVE_TOKEN_FILE, GDRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GDRIVE_SCOPES)
            # Lệnh này sẽ tự động mở trình duyệt
            creds = flow.run_local_server(port=0) 
        with open(DRIVE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    service = build('drive', 'v3', credentials=creds)
    user_info_service = build('oauth2', 'v2', credentials=creds)
    user_info = user_info_service.userinfo().get().execute()
    user_email = user_info.get('email')
    
    return service, user_email

# --- WORKER MỚI CHO VIỆC TẢI FILE LÊN ---
class UploadWorker(QObject):
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(int)

    def __init__(self, service, file_path, folder_id):
        super().__init__()
        self.service = service
        self.file_path = file_path
        self.folder_id = folder_id

    def run(self):
        try:
            if not self.folder_id:
                raise ValueError("Lỗi: Không có ID thư mục.")
            
            file_metadata = {'name': os.path.basename(self.file_path), 'parents': [self.folder_id]}
            media = MediaFileUpload(self.file_path, resumable=True)
            request = self.service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink')
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    self.progress.emit(int(status.progress() * 100))
            
            file_url = response.get('webViewLink')
            self.finished.emit(file_url)
            
        except Exception as e:
            self.error.emit(str(e))

# --- WIDGET TÙY CHỈNH ---
class ListItemWidget(QWidget):
    def __init__(self, item_id, title, deadline, is_submitted, is_reminded, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        layout = QHBoxLayout(self)
        info_layout = QVBoxLayout()
        title_label = QLabel(f"<b>ID {item_id}: {title}</b>")
        deadline_label = QLabel(f"Hạn chót: {deadline}")
        info_layout.addWidget(title_label)
        info_layout.addWidget(deadline_label)
        status_label = QLabel("Đã hoàn thành" if is_submitted else "Chưa thực hiện")
        status_label.setStyleSheet(f"color: {'#27ae60' if is_submitted else '#e74c3c'}; font-weight: bold;")
        layout.addLayout(info_layout, 1)
        layout.addWidget(status_label, alignment=Qt.AlignCenter)
        if is_reminded and not is_submitted:
            self.setStyleSheet("background-color: #fff3cd;")
            title_label.setText(f"<b>ID {item_id}: {title} (Cần chú ý!)</b>")

# --- GIAO DIỆN CHÍNH ---
class ClientWindow(QMainWindow):
    authentication_successful = Signal(str)

    def __init__(self):
        super().__init__()
        self.network_manager = QNetworkAccessManager(self)
        self.setWindowTitle("Hệ thống Báo cáo - phiên bản dành cho trường học")
        if os.path.exists('baocao.ico'):
            self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(200, 200, 1100, 800)
        self.api_key = self.load_api_key()
        self.drive_service = None
        self.user_email = None

        self.setStyleSheet("""
            QMainWindow { background-color: #f4f6f9; }
            QFrame#card { background-color: white; border-radius: 10px; border: 1px solid #dfe4ea; padding: 20px; margin: 10px; }
            QLineEdit, QDateTimeEdit, QComboBox { border: 1px solid #ced4da; border-radius: 5px; padding: 10px; font-size: 16px; }
            QPushButton { background-color: #3498db; color: white; border: none; padding: 12px 18px; border-radius: 5px; font-weight: bold; font-size: 16px; }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:disabled { background-color: #bdc3c7; }
            QLabel { font-weight: bold; color: #34495e; font-size: 16px; }
            QTableWidget, QListWidget { border: 1px solid #dfe4ea; border-radius: 5px; background-color: #ffffff; font-size: 16px; }
            QHeaderView::section { background-color: #34495e; color: white; padding: 8px; font-size: 15px; border: none;}
            QTabWidget::pane { border: none; }
            QTabBar::tab { background-color: #e4e7eb; color: #566573; padding: 12px 25px; font-size: 16px; font-weight: bold; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
            QTabBar::tab:hover { background-color: #d5dbdb; }
            QTabBar::tab:selected { background-color: #3498db; color: white; }
        """)
        
        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.create_api_key_ui()
        self.tab_widget = QTabWidget()
        self.file_submission_tab = QWidget()
        self.data_entry_tab = QWidget()
        self.tab_widget.addTab(self.file_submission_tab, "Báo cáo Nộp File")
        self.tab_widget.addTab(self.data_entry_tab, "Báo cáo Nhập liệu (Google Sheet)")
        self.layout.addWidget(self.tab_widget)
        self.setCentralWidget(central_widget)
        self.create_file_submission_ui()
        self.create_data_entry_ui()
        self.authentication_successful.connect(self.on_authentication_success)
        self.update_ui_for_api_key()
        if self.api_key:
            self.fetch_school_info()
        else:
            QMessageBox.information(self, "Chào mừng", "Vui lòng nhập Mã API được cung cấp và nhấn 'Lưu'.")

    def _handle_reply(self, reply: QNetworkReply, on_success: Callable, on_error: Callable):
        if reply.error() == QNetworkReply.NoError:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            response_data = bytes(reply.readAll()).decode('utf-8')
            if 200 <= status_code < 300:
                try:
                    on_success(json.loads(response_data) if response_data else {})
                except json.JSONDecodeError:
                    on_error(status_code, "Lỗi giải mã JSON.")
            else:
                on_error(status_code, response_data)
        else:
            on_error(0, f"Lỗi mạng: {reply.errorString()}")
        reply.deleteLater()

    def api_get(self, endpoint: str, on_success: Callable, on_error: Callable, headers: dict = None, params: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        if params:
            query = QUrlQuery()
            for key, value in params.items():
                query.addQueryItem(key, str(value))
            url.setQuery(query)

        request = QNetworkRequest(url)
        if headers:
            for key, value in headers.items():
                request.setRawHeader(key.encode(), value.encode())
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_post(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable, headers: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        if headers:
            for key, value in headers.items():
                request.setRawHeader(key.encode(), value.encode())
        payload = QByteArray(json.dumps(data).encode('utf-8'))
        reply = self.network_manager.post(request, payload)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def refresh_data(self):
        if self.api_key:
            self.load_file_tasks()
            self.load_data_reports()
            
    def create_api_key_ui(self):
        api_key_card = QFrame()
        api_key_card.setObjectName("card")
        api_key_layout = QVBoxLayout(api_key_card)
        title_label = QLabel("Cấu hình Mã API")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        api_key_layout.addWidget(title_label)
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
        api_key_layout.addLayout(input_layout)
        api_key_layout.addWidget(self.school_info_label)
        self.layout.addWidget(api_key_card)
        self.save_api_key_button.clicked.connect(self.save_api_key_handler)
        self.edit_api_key_button.clicked.connect(self.edit_api_key_handler)

    def create_file_submission_ui(self):
        layout = QVBoxLayout(self.file_submission_tab)
        tasks_card = QFrame()
        tasks_card.setObjectName("card")
        tasks_layout = QVBoxLayout(tasks_card)
        tasks_title_label = QLabel("Danh sách Công việc Nộp File")
        tasks_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        tasks_layout.addWidget(tasks_title_label)
        self.load_ft_button = QPushButton("Làm mới danh sách")
        self.load_ft_button.clicked.connect(self.refresh_data)
        tasks_layout.addWidget(self.load_ft_button)
        tables_layout = QHBoxLayout()
        todo_group = QVBoxLayout()
        todo_group.addWidget(QLabel("Công việc cần thực hiện:"))
        self.ft_todo_table = self.create_tasks_table()
        todo_group.addWidget(self.ft_todo_table)
        tables_layout.addLayout(todo_group)
        overdue_group = QVBoxLayout()
        overdue_group.addWidget(QLabel("Công việc đã quá hạn:"))
        self.ft_overdue_table = self.create_tasks_table()
        overdue_group.addWidget(self.ft_overdue_table)
        tables_layout.addLayout(overdue_group)
        tasks_layout.addLayout(tables_layout)
        layout.addWidget(tasks_card)
        submit_card = QFrame()
        submit_card.setObjectName("card")
        submit_layout = QVBoxLayout(submit_card)
        submit_title_label = QLabel("Nộp báo cáo")
        submit_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        submit_layout.addWidget(submit_title_label)
        self.submit_file_button = QPushButton("Nộp file cho công việc đã chọn")
        self.ft_status_label = QLabel("Sẵn sàng.")
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        submit_layout.addWidget(self.submit_file_button)
        submit_layout.addWidget(self.ft_status_label)
        submit_layout.addWidget(self.progress_bar)
        layout.addWidget(submit_card)
        self.submit_file_button.clicked.connect(self.submit_file_handler)
        self.ft_todo_table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.ft_overdue_table.itemSelectionChanged.connect(self.on_table_selection_changed)

    def create_data_entry_ui(self):
        layout = QVBoxLayout(self.data_entry_tab)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_title_label = QLabel("Danh sách Báo cáo Nhập liệu")
        list_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        list_layout.addWidget(list_title_label)
        self.load_dr_button = QPushButton("Làm mới danh sách")
        self.load_dr_button.clicked.connect(self.refresh_data)
        list_layout.addWidget(self.load_dr_button)
        self.dr_list_widget = QListWidget()
        list_layout.addWidget(self.dr_list_widget)
        layout.addWidget(list_card)
        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QVBoxLayout(action_card)
        action_title = QLabel("Hành động")
        action_title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        action_layout.addWidget(action_title)
        self.open_sheet_button = QPushButton("Mở Trang tính để Nhập liệu")
        self.open_sheet_button.clicked.connect(self.open_google_sheet)
        action_layout.addWidget(self.open_sheet_button)
        self.mark_complete_button = QPushButton("Đánh dấu là đã hoàn thành")
        self.mark_complete_button.setStyleSheet("background-color: #27ae60;")
        self.mark_complete_button.clicked.connect(self.mark_as_complete)
        action_layout.addWidget(self.mark_complete_button)
        self.dr_status_label = QLabel("Vui lòng chọn một báo cáo từ danh sách trên.")
        action_layout.addWidget(self.dr_status_label)
        layout.addWidget(action_card)

    def create_tasks_table(self):
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Tiêu đề", "Hạn chót", "Trạng thái"])
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        return table
        
    def on_table_selection_changed(self):
        sender = self.sender()
        if not sender or not sender.selectedItems(): return
        other_table = self.ft_overdue_table if sender == self.ft_todo_table else self.ft_todo_table
        other_table.blockSignals(True)
        other_table.clearSelection()
        other_table.blockSignals(False)

    def load_file_tasks(self):
        if not self.api_key: return
        self.load_ft_button.setDisabled(True)
        self.load_ft_button.setText("Đang tải...")
        def on_success(tasks):
            self.ft_todo_table.setRowCount(0)
            self.ft_overdue_table.setRowCount(0)
            now = datetime.now()
            for task in tasks:
                deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%dT%H:%M:%S")
                is_submitted = task.get('is_submitted', False)
                is_reminded = task.get('is_reminded', False)
                status_text = "Đã thực hiện" if is_submitted else "Chưa thực hiện"
                status_item = QTableWidgetItem(status_text)
                status_item.setTextAlignment(Qt.AlignCenter)
                status_item.setForeground(QColor("#27ae60") if is_submitted else QColor("#e74c3c"))
                title_text = task['title']
                if is_reminded and not is_submitted:
                    title_text += " (Cần chú ý!)"
                title_item = QTableWidgetItem(title_text)
                title_item.setData(Qt.UserRole, task['id'])
                deadline_item = QTableWidgetItem(deadline_dt.strftime("%H:%M %d/%m/%Y"))
                table = self.ft_todo_table if deadline_dt > now else self.ft_overdue_table
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, title_item)
                table.setItem(row, 1, deadline_item)
                table.setItem(row, 2, status_item)
                if is_reminded and not is_submitted:
                    for col in range(table.columnCount()):
                        table.item(row, col).setBackground(QColor("#fff3cd"))
            self.ft_todo_table.resizeRowsToContents()
            self.ft_overdue_table.resizeRowsToContents()
            self.load_ft_button.setDisabled(False)
            self.load_ft_button.setText("Làm mới danh sách")
        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tải danh sách công việc nộp file.")
            self.load_ft_button.setDisabled(False)
            self.load_ft_button.setText("Làm mới danh sách")
        headers = {"x-api-key": self.api_key}
        self.api_get("/file-tasks/", on_success, on_error, headers=headers)

    def submit_file_handler(self):
        selected_table = self.ft_todo_table if self.ft_todo_table.selectedItems() else self.ft_overdue_table
        if not selected_table.selectedItems():
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một công việc để nộp file.")
            return

        row = selected_table.currentRow()
        task_id = selected_table.item(row, 0).data(Qt.UserRole)
        if "Đã thực hiện" in selected_table.item(row, 2).text():
            if QMessageBox.question(self, 'Xác nhận', "Công việc này đã được nộp. Bạn có muốn nộp lại file khác không?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                return

        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file để nộp")
        if not file_path: return

        self.ft_status_label.setText("Đang xử lý...")
        self.submit_file_button.setDisabled(True)
        headers = {"x-api-key": self.api_key}
        
        def on_generic_error(status, err_msg):
            QMessageBox.critical(self, "Lỗi", f"Quá trình nộp bài thất bại.\n\nChi tiết: {err_msg}")
            self.ft_status_label.setText("Nộp bài thất bại!")
            self.progress_bar.hide()
            self.submit_file_button.setDisabled(False)

        def on_upload_error(err_msg):
            on_generic_error(0, err_msg)

        def start_submission_process():
            try:
                if not self.drive_service or not self.user_email:
                    self.ft_status_label.setText("Đang xác thực với Google...")
                    self.drive_service, self.user_email = get_drive_service()
                
                if not self.user_email:
                    raise ValueError("Không thể lấy được email người dùng từ Google.")

                self.ft_status_label.setText("Đang lấy thông tin thư mục nộp bài...")
                params = {"user_email": self.user_email}
                self.api_get(f"/file-tasks/{task_id}/upload-folder", on_folder_id_success, on_generic_error, headers=headers, params=params)

            except Exception as e:
                on_generic_error(0, f"Lỗi xác thực Google Drive: {e}")

        def on_folder_id_success(data):
            upload_folder_id = data.get("folder_id")
            start_upload_in_thread(self.drive_service, upload_folder_id)

        def start_upload_in_thread(service, folder_id):
            self.ft_status_label.setText("Đang tải file lên Google Drive...")
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.upload_thread = QThread()
            self.upload_worker = UploadWorker(service, file_path, folder_id)
            self.upload_worker.moveToThread(self.upload_thread)
            self.upload_thread.started.connect(self.upload_worker.run)
            self.upload_worker.finished.connect(on_upload_finished)
            self.upload_worker.error.connect(on_upload_error)
            self.upload_worker.progress.connect(self.progress_bar.setValue)
            self.upload_worker.finished.connect(self.upload_thread.quit)
            self.upload_worker.finished.connect(self.upload_worker.deleteLater)
            self.upload_thread.finished.connect(self.upload_thread.deleteLater)
            self.upload_thread.start()

        def on_upload_finished(file_url):
            self.progress_bar.hide()
            self.ft_status_label.setText("Đang báo cáo về server...")
            payload = {"task_id": task_id, "file_url": file_url}
            self.api_post("/file-submissions/", payload, on_submission_success, on_generic_error, headers=headers)

        def on_submission_success(data):
            QMessageBox.information(self, "Hoàn tất", "Nộp báo cáo thành công!")
            self.ft_status_label.setText(f"Đã nộp bài thành công cho ID {task_id}.")
            self.submit_file_button.setDisabled(False)
            self.refresh_data()
        
        start_submission_process()

    def load_data_reports(self):
        if not self.api_key: return
        self.load_dr_button.setDisabled(True)
        self.load_dr_button.setText("Đang tải...")
        def on_success(reports):
            self.dr_list_widget.clear()
            for report in reports:
                deadline_dt = datetime.strptime(report['deadline'], "%Y-%m-%dT%H:%M:%S")
                deadline_str = deadline_dt.strftime("%H:%M %d/%m/%Y")
                is_submitted = report.get('is_submitted', False)
                is_reminded = report.get('is_reminded', False)
                list_item = QListWidgetItem()
                list_item.setData(Qt.UserRole, report)
                custom_widget = ListItemWidget(report['id'], report['title'], deadline_str, is_submitted, is_reminded)
                list_item.setSizeHint(custom_widget.sizeHint())
                self.dr_list_widget.addItem(list_item)
                self.dr_list_widget.setItemWidget(list_item, custom_widget)
            self.load_dr_button.setDisabled(False)
            self.load_dr_button.setText("Làm mới danh sách")
        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tải danh sách báo cáo nhập liệu.")
            self.load_dr_button.setDisabled(False)
            self.load_dr_button.setText("Làm mới danh sách")
        headers = {"x-api-key": self.api_key}
        self.api_get("/data-reports/", on_success, on_error, headers=headers)

    def open_google_sheet(self):
        current_item = self.dr_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một báo cáo từ danh sách.")
            return
        report_data = current_item.data(Qt.UserRole)
        sheet_url = report_data.get('sheet_url')
        if sheet_url:
            webbrowser.open(sheet_url)
        else:
            QMessageBox.critical(self, "Lỗi", "Không tìm thấy đường dẫn trang tính cho báo cáo này.")

    def mark_as_complete(self):
        current_item = self.dr_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một báo cáo từ danh sách.")
            return
        report_data = current_item.data(Qt.UserRole)
        report_id = report_data['id']
        if report_data.get('is_submitted'):
            QMessageBox.information(self, "Thông báo", "Báo cáo này đã được đánh dấu hoàn thành trước đó.")
            return
        reply = QMessageBox.question(self, 'Xác nhận', "Bạn có chắc chắn đã nhập liệu xong và muốn đánh dấu là hoàn thành không?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        self.dr_status_label.setText("Đang gửi xác nhận...")
        self.mark_complete_button.setDisabled(True)
        def on_success(data):
            QMessageBox.information(self, "Thành công", "Đã đánh dấu báo cáo là hoàn thành.")
            self.dr_status_label.setText(f"Đã hoàn thành báo cáo ID {report_id}.")
            self.mark_complete_button.setDisabled(False)
            self.refresh_data()
        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể đánh dấu hoàn thành.")
            self.dr_status_label.setText("Thao tác thất bại!")
            self.mark_complete_button.setDisabled(False)
        headers = {"x-api-key": self.api_key}
        self.api_post(f"/data-reports/{report_id}/complete", {}, on_success, on_error, headers=headers)

    def update_ui_for_api_key(self):
        if self.api_key:
            self.api_key_input.setText("**********")
            self.api_key_input.setDisabled(True)
            self.save_api_key_button.hide()
            self.edit_api_key_button.show()
        else:
            self.api_key_input.clear()
            self.api_key_input.setDisabled(False)
            self.save_api_key_button.show()
            self.edit_api_key_button.hide()
            self.school_info_label.setText("Trạng thái: Chưa cấu hình.")

    def edit_api_key_handler(self):
        self.api_key = None
        self.drive_service = None
        self.user_email = None
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        if os.path.exists(DRIVE_TOKEN_FILE):
            os.remove(DRIVE_TOKEN_FILE)
        self.update_ui_for_api_key()
        self.ft_todo_table.setRowCount(0)
        self.ft_overdue_table.setRowCount(0)
        self.dr_list_widget.clear()
        self.api_key_input.setFocus()
        QMessageBox.information(self, "Thông báo", "Vui lòng nhập Mã API mới và nhấn 'Lưu'.")

    def on_authentication_success(self, school_name):
        self.school_info_label.setText(f"Đang làm việc với tư cách: Trường {school_name}")
        self.refresh_data()

    def fetch_school_info(self):
        if not self.api_key: return
        self.school_info_label.setText("Đang xác thực API Key...")
        def on_success(data):
            school_name = data.get('name', 'Không xác định')
            self.authentication_successful.emit(school_name)
        def on_error(status, err):
            self.school_info_label.setText("Trạng thái: Mã API không hợp lệ.")
            self.edit_api_key_handler()
        headers = {"x-api-key": self.api_key}
        self.api_get("/schools/me", on_success, on_error, headers=headers)

    def load_api_key(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f).get("api_key")
        except (IOError, json.JSONDecodeError):
            return None
        return None

    def save_api_key_handler(self):
        key = self.api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Lỗi", "Mã API không được để trống.")
            return
        config_data = {"api_key": key}
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_data, f, indent=4)
        except IOError:
            QMessageBox.critical(self, "Lỗi", "Không thể lưu file cấu hình.")
            return
        self.api_key = key
        self.update_ui_for_api_key()
        self.fetch_school_info()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())
