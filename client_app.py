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
    QProgressBar
)
from PySide6.QtCore import Qt, QDateTime, Signal, QUrl, QByteArray, QThread, QObject, QUrlQuery
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from spreadsheet_widget import SpreadsheetWidget, ColumnSpec

API_URL = "https://auto-report-backend.onrender.com"

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
        layout = QHBoxLayout(self)
        info_layout = QVBoxLayout()
        
        title_text = f"<b>ID {item_id}: {title}</b>"
        status_text = "Đã hoàn thành" if is_submitted else "Chưa thực hiện"
        status_color = '#27ae60' if is_submitted else '#e74c3c'
        
        if is_locked and not is_submitted:
            title_text = f"<b>ID {item_id}: {title} (Đã khóa)</b>"
            status_text = "Đã khóa"
            status_color = '#7f8c8d'
            self.setStyleSheet("background-color: #f2f2f2;")
        elif is_reminded and not is_submitted:
            self.setStyleSheet("background-color: #fff3cd;")
            title_text = f"<b>ID {item_id}: {title} (Cần chú ý!)</b>"
            
        title_label = QLabel(title_text)
        deadline_label = QLabel(f"Hạn chót: {deadline}")
        info_layout.addWidget(title_label)
        info_layout.addWidget(deadline_label)
        
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(status_label, alignment=Qt.AlignCenter)
        
        if attachment_url:
            btn = QPushButton("Tải File Kèm Theo")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, url=attachment_url: webbrowser.open(url))
            action_layout.addWidget(btn)

        layout.addLayout(info_layout, 1)
        layout.addWidget(action_widget)
        
class ClientWindow(QMainWindow):
    authentication_successful = Signal(str)
    upload_complete_signal = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.network_manager = QNetworkAccessManager(self)
        self.setWindowTitle("Hệ thống Báo cáo - phiên bản dành cho trường học")
        if os.path.exists('baocao.ico'): self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(200, 200, 1100, 800)
        self.api_key = self.load_api_key(); self.drive_service = None; self.user_email = None
        self.setStyleSheet("""
            QMainWindow { background-color: #f8f9fa; }
            QFrame#card { background-color: white; border-radius: 8px; border: 1px solid #e9ecef; padding: 20px; }
            QLineEdit { border: 1px solid #ced4da; border-radius: 4px; padding: 8px; font-size: 15px; }
            QPushButton { background-color: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; font-weight: bold; font-size: 15px; }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton:disabled { background-color: #6c757d; }
            QLabel { color: #212529; font-size: 15px; }
            QTableWidget { border: 1px solid #dee2e6; border-radius: 4px; }
            QHeaderView::section { background-color: #f1f3f5; padding: 8px; font-weight: bold; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 10px 15px; font-weight: bold; }
        """)
        central_widget = QWidget(); self.layout = QVBoxLayout(central_widget)
        self.create_api_key_ui()
        self.tab_widget = QTabWidget(); self.file_submission_tab = QWidget(); self.data_entry_tab = QWidget()
        self.tab_widget.addTab(self.file_submission_tab, "Báo cáo Nộp File"); self.tab_widget.addTab(self.data_entry_tab, "Báo cáo Nhập liệu")
        self.layout.addWidget(self.tab_widget); self.setCentralWidget(central_widget)
        self.create_file_submission_ui(); self.create_data_entry_ui()
        self.authentication_successful.connect(self.on_authentication_success); self.upload_complete_signal.connect(self.handle_final_submission)
        self.update_ui_for_api_key()
        if self.api_key: self.fetch_school_info()
        else: QMessageBox.information(self, "Chào mừng", "Vui lòng nhập Mã API được cung cấp và nhấn 'Lưu'.")

    def _handle_reply(self, reply: QNetworkReply, on_success: Callable, on_error: Callable):
        if reply.error() == QNetworkReply.NoError:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            response_data = bytes(reply.readAll()).decode('utf-8')
            if 200 <= status_code < 300:
                try: on_success(json.loads(response_data) if response_data else {}, {})
                except json.JSONDecodeError: on_error(status_code, "Lỗi giải mã JSON.")
            else: on_error(status_code, response_data)
        elif reply.error() == QNetworkReply.TimeoutError: on_error(408, "Yêu cầu hết thời gian chờ.")
        else: on_error(0, f"Lỗi mạng: {reply.errorString()}")
        reply.deleteLater()

    def api_get(self, endpoint: str, on_success: Callable, on_error: Callable, headers: dict = None, params: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        if params: query = QUrlQuery(); [query.addQueryItem(k, str(v)) for k, v in params.items()]; url.setQuery(query)
        request = QNetworkRequest(url); request.setTransferTimeout(30000) 
        if headers: [request.setRawHeader(k.encode(), v.encode()) for k, v in headers.items()]
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_post(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable, headers: dict = None):
        url = QUrl(f"{API_URL}{endpoint}"); request = QNetworkRequest(url); request.setTransferTimeout(30000)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        if headers: [request.setRawHeader(k.encode(), v.encode()) for k, v in headers.items()]
        payload = QByteArray(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        reply = self.network_manager.post(request, payload)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def refresh_data(self):
        if self.api_key: self.load_file_tasks(); self.load_data_reports()
            
    def create_api_key_ui(self):
        card = QFrame(); card.setObjectName("card"); layout = QVBoxLayout(card)
        layout.addWidget(QLabel("Cấu hình Mã API"))
        input_layout = QHBoxLayout(); input_layout.addWidget(QLabel("Mã API của trường:"))
        self.api_key_input = QLineEdit(); self.save_api_key_button = QPushButton("Lưu"); self.edit_api_key_button = QPushButton("Thay đổi")
        input_layout.addWidget(self.api_key_input); input_layout.addWidget(self.save_api_key_button); input_layout.addWidget(self.edit_api_key_button)
        self.school_info_label = QLabel("Trạng thái: Chưa cấu hình."); self.school_info_label.setStyleSheet("font-style: italic; color: #555;")
        layout.addLayout(input_layout); layout.addWidget(self.school_info_label); self.layout.addWidget(card)
        self.save_api_key_button.clicked.connect(self.save_api_key_handler); self.edit_api_key_button.clicked.connect(self.edit_api_key_handler)

    def create_file_submission_ui(self):
        layout = QVBoxLayout(self.file_submission_tab)
        tasks_card = QFrame(); tasks_card.setObjectName("card"); tasks_layout = QVBoxLayout(tasks_card)
        tasks_layout.addWidget(QLabel("Danh sách Công việc Nộp File"))
        self.load_ft_button = QPushButton("Làm mới danh sách"); self.load_ft_button.clicked.connect(self.refresh_data); tasks_layout.addWidget(self.load_ft_button)
        tables_layout = QHBoxLayout()
        todo_group = QVBoxLayout(); todo_group.addWidget(QLabel("Công việc cần thực hiện:")); self.ft_todo_table = self.create_tasks_table(); todo_group.addWidget(self.ft_todo_table); tables_layout.addLayout(todo_group)
        overdue_group = QVBoxLayout(); overdue_group.addWidget(QLabel("Công việc đã quá hạn:")); self.ft_overdue_table = self.create_tasks_table(); overdue_group.addWidget(self.ft_overdue_table); tables_layout.addLayout(overdue_group)
        tasks_layout.addLayout(tables_layout); layout.addWidget(tasks_card)
        submit_card = QFrame(); submit_card.setObjectName("card"); submit_layout = QVBoxLayout(submit_card)
        submit_layout.addWidget(QLabel("Nộp báo cáo"))
        self.submit_file_button = QPushButton("Nộp file cho công việc đã chọn"); self.ft_status_label = QLabel("Sẵn sàng.")
        self.progress_bar = QProgressBar(); self.progress_bar.hide()
        submit_layout.addWidget(self.submit_file_button); submit_layout.addWidget(self.ft_status_label); submit_layout.addWidget(self.progress_bar)
        layout.addWidget(submit_card)
        self.submit_file_button.clicked.connect(self.submit_file_handler)
        self.ft_todo_table.itemSelectionChanged.connect(self.on_table_selection_changed); self.ft_overdue_table.itemSelectionChanged.connect(self.on_table_selection_changed)

    def create_data_entry_ui(self):
        main_layout = QHBoxLayout(self.data_entry_tab)
        list_card = QFrame(); list_card.setObjectName("card"); list_card.setMaximumWidth(400); list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("Chọn Báo cáo Nhập liệu"))
        self.load_dr_button = QPushButton("Làm mới danh sách"); self.load_dr_button.clicked.connect(self.refresh_data); list_layout.addWidget(self.load_dr_button)
        self.dr_list_widget = QListWidget(); self.dr_list_widget.currentItemChanged.connect(self.display_data_report_sheet); list_layout.addWidget(self.dr_list_widget)
        main_layout.addWidget(list_card)
        self.spreadsheet_container = QFrame(); self.spreadsheet_container.setObjectName("card"); self.spreadsheet_layout = QVBoxLayout(self.spreadsheet_container)
        self.dr_status_label = QLabel("Vui lòng chọn một báo cáo từ danh sách bên trái."); self.dr_status_label.setAlignment(Qt.AlignCenter)
        self.spreadsheet_layout.addWidget(self.dr_status_label)
        main_layout.addWidget(self.spreadsheet_container, 1)

    def create_tasks_table(self):
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Tiêu đề", "Hạn chót", "Trạng thái", "Hành động"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        return table
       
    def on_table_selection_changed(self):
        sender = self.sender()
        if not sender or not sender.selectedItems(): return
        other_table = self.ft_overdue_table if sender == self.ft_todo_table else self.ft_todo_table
        other_table.blockSignals(True); other_table.clearSelection(); other_table.blockSignals(False)

    def load_file_tasks(self):
        if not self.api_key: return
        self.load_ft_button.setDisabled(True); self.load_ft_button.setText("Đang tải...")
        def on_success(tasks, _):
            self.ft_todo_table.setRowCount(0); self.ft_overdue_table.setRowCount(0)
            now = datetime.now()
            for task in tasks:
                deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%dT%H:%M:%S")
                is_submitted = task.get('is_submitted', False)
                is_reminded = task.get('is_reminded', False)
                is_locked = task.get('is_locked', False)
                
                status_text = "Đã thực hiện" if is_submitted else "Chưa thực hiện"
                status_color = QColor("#27ae60" if is_submitted else "#e74c3c")

                title_text = task['title']
                bg_color = None

                if is_locked and not is_submitted:
                    title_text += " (Đã khóa)"
                    status_text = "Đã khóa"
                    status_color = QColor("#7f8c8d")
                    bg_color = QColor("#f2f2f2")
                elif is_reminded and not is_submitted:
                    title_text += " (Cần chú ý!)"
                    bg_color = QColor("#fff3cd")

                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(status_color)
                
                title_item = QTableWidgetItem(title_text)
                title_item.setData(Qt.UserRole, {'id': task['id'], 'is_locked': is_locked})
                
                deadline_item = QTableWidgetItem(deadline_dt.strftime("%H:%M %d/%m/%Y"))
                table = self.ft_todo_table if deadline_dt > now else self.ft_overdue_table
                row = table.rowCount(); table.insertRow(row)
                table.setItem(row, 0, title_item); table.setItem(row, 1, deadline_item); table.setItem(row, 2, status_item)

                attachment_url = task.get("attachment_url")
                if attachment_url:
                    btn = QPushButton("Tải File Kèm Theo")
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.clicked.connect(lambda _, url=attachment_url: webbrowser.open(url))
                    table.setCellWidget(row, 3, btn)

                if bg_color:
                    for col in range(table.columnCount()):
                        if table.item(row, col):
                            table.item(row, col).setBackground(bg_color)

            self.load_ft_button.setDisabled(False); self.load_ft_button.setText("Làm mới danh sách")
        def on_error(s, e): handle_api_error(self, s, e, "Không thể tải công việc."); self.load_ft_button.setDisabled(False); self.load_ft_button.setText("Làm mới")
        self.api_get("/file-tasks/", on_success, on_error, headers={"x-api-key": self.api_key})
        
    def submit_file_handler(self):
        selected_table = self.ft_todo_table if self.ft_todo_table.selectedItems() else self.ft_overdue_table
        if not selected_table.selectedItems(): 
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một công việc."); return
        
        row = selected_table.currentRow()
        task_data = selected_table.item(row, 0).data(Qt.UserRole)
        task_id = task_data['id']
        is_locked = task_data['is_locked']

        if is_locked:
            QMessageBox.warning(self, "Admin đã khoá", "Yêu cầu này đã bị quản trị viên khóa, không thể nộp bài.")
            return

        if "Đã thực hiện" in selected_table.item(row, 2).text() and QMessageBox.question(self, 'Xác nhận', "Đã nộp. Nộp lại file khác?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.No: return
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file để nộp");
        if not file_path: return
        
        self.ft_status_label.setText("Đang xử lý..."); self.submit_file_button.setDisabled(True)
        
        def on_generic_error(s, e): 
            QMessageBox.critical(self, "Lỗi", f"Nộp bài thất bại.\n{e}"); self.ft_status_label.setText("Nộp bài thất bại!"); self.progress_bar.hide(); self.submit_file_button.setDisabled(False)
        
        def start_submission_process():
            try:
                if not self.drive_service: self.ft_status_label.setText("Đang xác thực..."); self.drive_service, self.user_email = get_drive_service()
                self.ft_status_label.setText("Đang lấy thông tin thư mục...")
                params = {"user_email": self.user_email} if self.user_email else {}
                self.api_get(f"/file-tasks/{task_id}/upload-folder", on_folder_id_success, on_generic_error, headers={"x-api-key": self.api_key}, params=params)
            except Exception as e: on_generic_error(0, f"Lỗi xác thực Google Drive: {e}")
        
        def on_folder_id_success(data, _):
            self.ft_status_label.setText("Đang tải file lên..."); self.progress_bar.setValue(0); self.progress_bar.show()
            self.upload_thread = QThread(); self.upload_worker = UploadWorker(self.drive_service, file_path, data.get("folder_id"))
            self.upload_worker.moveToThread(self.upload_thread); self.upload_thread.started.connect(self.upload_worker.run)
            self.upload_worker.finished.connect(lambda url: self.upload_complete_signal.emit(task_id, url))
            self.upload_worker.error.connect(lambda e: on_generic_error(0, e)); self.upload_worker.progress.connect(self.progress_bar.setValue)
            self.upload_worker.finished.connect(self.upload_thread.quit); self.upload_worker.finished.connect(self.upload_worker.deleteLater); self.upload_thread.finished.connect(self.upload_thread.deleteLater)
            self.upload_thread.start()
        
        start_submission_process()

    def handle_final_submission(self, task_id, file_url):
        self.progress_bar.hide(); self.ft_status_label.setText("Đang báo cáo về server...")
        def on_success(d, _):
            QMessageBox.information(self, "Hoàn tất", "Nộp báo cáo thành công!")
            self.ft_status_label.setText(f"Đã nộp thành công.")
            self.submit_file_button.setDisabled(False)
            self.refresh_data()
        def on_error(s, e): handle_api_error(self, s, e, "Nộp bài thất bại."); self.submit_file_button.setDisabled(False)
        self.api_post("/file-submissions/", {"task_id": task_id, "file_url": file_url}, on_success, on_error, headers={"x-api-key": self.api_key})

    def load_data_reports(self):
        if not self.api_key: return
        self.load_dr_button.setDisabled(True); self.load_dr_button.setText("Đang tải...")
        def on_success(reports, _):
            self.dr_list_widget.clear()
            for report in reports:
                deadline_str = QDateTime.fromString(report['deadline'], "%Y-%m-%dT%H:%M:%S").toString("HH:mm dd/MM/yyyy")
                item = QListWidgetItem()
                item.setData(Qt.UserRole, report)
                
                widget = ListItemWidget(
                    report['id'], 
                    report['title'], 
                    deadline_str, 
                    report.get('attachment_url'),
                    report.get('is_submitted', False), 
                    report.get('is_reminded', False),
                    report.get('is_locked', False)
                )
                
                item.setSizeHint(widget.sizeHint()); self.dr_list_widget.addItem(item); self.dr_list_widget.setItemWidget(item, widget)
            self.load_dr_button.setDisabled(False); self.load_dr_button.setText("Làm mới")
        def on_error(s, e): handle_api_error(self, s, e, "Không thể tải báo cáo."); self.load_dr_button.setDisabled(False); self.load_dr_button.setText("Làm mới")
        self.api_get("/data-reports/", on_success, on_error, headers={"x-api-key": self.api_key})

    def display_data_report_sheet(self, current_item, previous_item):
        for i in reversed(range(self.spreadsheet_layout.count())): self.spreadsheet_layout.itemAt(i).widget().setParent(None)
        if not current_item:
            label = QLabel("Vui lòng chọn một báo cáo từ danh sách bên trái."); label.setAlignment(Qt.AlignCenter)
            self.spreadsheet_layout.addWidget(label); return
        
        report_data = current_item.data(Qt.UserRole)
        report_id = report_data['id']
        is_locked = report_data.get('is_locked', False)

        loading_label = QLabel(f"Đang tải biểu mẫu cho '{report_data['title']}'..."); self.spreadsheet_layout.addWidget(loading_label)
        
        def on_schema_error(s, e): 
            handle_api_error(self, s, e, "Không thể tải cấu trúc biểu mẫu.")
            loading_label.setText("Lỗi tải biểu mẫu.")
        
        def on_schema_success(schema_data, h):
            columns = [ColumnSpec(**col) for col in schema_data.get("columns_schema", [])]
            if not columns: 
                loading_label.setText("Báo cáo này không có biểu mẫu.")
                return

            def on_data_success(submission_data, h):
                loading_label.setParent(None)
                
                if is_locked and not report_data.get('is_submitted', False):
                    locked_label = QLabel("🔴 Admin đã khoá danh sách này. Không thể nhập liệu.")
                    locked_label.setAlignment(Qt.AlignCenter)
                    locked_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px; margin-bottom: 10px;")
                    self.spreadsheet_layout.addWidget(locked_label)

                sheet = SpreadsheetWidget(columns, self)
                sheet.set_data(submission_data.get("data", []))
                
                sheet.setEnabled(not is_locked)
                
                sheet.saved.connect(lambda records: self.on_data_save(report_id, records, is_locked))
                self.spreadsheet_layout.addWidget(sheet)
            
            self.api_get(f"/data-reports/{report_id}/my-submission", on_data_success, on_schema_error, headers={"x-api-key": self.api_key})
        
        self.api_get(f"/data-reports/{report_id}/schema", on_schema_success, on_schema_error, headers={"x-api-key": self.api_key})

    def on_data_save(self, report_id: int, records: List[Dict[str, Any]], is_locked: bool):
        if is_locked:
            QMessageBox.warning(self, "Admin đã khoá", "Báo cáo này đã bị quản trị viên khóa, không thể lưu dữ liệu.")
            return

        print(f"Đang lưu {len(records)} dòng cho báo cáo ID {report_id}...")
        def on_save_success(d, h): 
            QMessageBox.information(self, "Thành công", "Đã lưu và nộp dữ liệu thành công!")
            self.refresh_data()
        def on_save_error(s, e): 
            handle_api_error(self, s, e, "Không thể lưu dữ liệu.")
        
        self.api_post(f"/data-reports/{report_id}/submit", {"data": records}, on_save_success, on_save_error, headers={"x-api-key": self.api_key})

    def update_ui_for_api_key(self):
        if self.api_key:
            self.api_key_input.setText("**********"); self.api_key_input.setDisabled(True)
            self.save_api_key_button.hide(); self.edit_api_key_button.show()
        else:
            self.api_key_input.clear(); self.api_key_input.setDisabled(False)
            self.save_api_key_button.show(); self.edit_api_key_button.hide()
            self.school_info_label.setText("Trạng thái: Chưa cấu hình.")

    def edit_api_key_handler(self):
        self.api_key = None; self.drive_service = None; self.user_email = None
        if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
        if os.path.exists(DRIVE_TOKEN_FILE): os.remove(DRIVE_TOKEN_FILE)
        self.update_ui_for_api_key(); self.ft_todo_table.setRowCount(0); self.ft_overdue_table.setRowCount(0); self.dr_list_widget.clear()
        self.api_key_input.setFocus(); QMessageBox.information(self, "Thông báo", "Vui lòng nhập Mã API mới và nhấn 'Lưu'.")

    def on_authentication_success(self, school_name):
        self.school_info_label.setText(f"Đang làm việc với tư cách: Trường {school_name}"); self.refresh_data()

    def fetch_school_info(self):
        if not self.api_key: return
        self.school_info_label.setText("Đang xác thực API Key...")
        def on_success(data, _):
            self.authentication_successful.emit(data.get('name', 'Không xác định'))
        def on_error(s, e): self.school_info_label.setText("Mã API không hợp lệ."); self.edit_api_key_handler()
        self.api_get("/schools/me", on_success, on_error, headers={"x-api-key": self.api_key})

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
        except IOError: QMessageBox.critical(self, "Lỗi", "Không thể lưu file cấu hình."); return
        self.api_key = key; self.update_ui_for_api_key(); self.fetch_school_info()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())
