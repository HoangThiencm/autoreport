# client_app.py
import sys
import os
import json
import webbrowser
import requests
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit, QLabel,
    QFileDialog, QHeaderView, QFrame, QTabWidget, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QFont, QColor, QIcon

API_URL = "https://auto-report-backend.onrender.com"
CONFIG_FILE = "client_config.txt"
GDRIVE_SCOPES = ['https://www.googleapis.com/auth/drive']
DRIVE_TOKEN_FILE = 'token.json'

# --- PHẦN LOGIC GOOGLE DRIVE ---
def get_drive_service():
    creds = None
    if os.path.exists(DRIVE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(DRIVE_TOKEN_FILE, GDRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials_oauth.json'):
                raise FileNotFoundError("Không tìm thấy file credentials_oauth.json.")
            flow = InstalledAppFlow.from_client_secrets_file('credentials_oauth.json', GDRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(DRIVE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def upload_file_to_drive(service, file_path, folder_id):
    if not folder_id:
        return (None, "Lỗi: Không có ID thư mục.")
    try:
        file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return (file.get('webViewLink'), None)
    except HttpError as error:
        return (None, f"Lỗi Google API: {error}")

# --- WIDGET TÙY CHỈNH CHO DANH SÁCH YÊU CẦU ---
class ListItemWidget(QWidget):
    def __init__(self, item_id, title, deadline, is_submitted, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        layout = QHBoxLayout(self)
        
        info_layout = QVBoxLayout()
        title_label = QLabel(f"<b>ID {item_id}: {title}</b>")
        deadline_label = QLabel(f"Hạn chót: {deadline}")
        info_layout.addWidget(title_label)
        info_layout.addWidget(deadline_label)
        
        status_label = QLabel("Đã hoàn thành" if is_submitted else "Chưa thực hiện")
        status_label.setStyleSheet(f"color: {'green' if is_submitted else 'red'}; font-weight: bold;")
        
        layout.addLayout(info_layout, 1)
        layout.addWidget(status_label, alignment=Qt.AlignCenter)

# --- GIAO DIỆN CHÍNH ---
class ClientWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hệ thống Báo cáo")
        if os.path.exists('baocao.ico'):
            self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(200, 200, 1100, 800)
        self.api_key = self.load_api_key()
        self.setStyleSheet("""
            QMainWindow { background-color: #ecf0f1; }
            QFrame#card { background-color: white; border-radius: 10px; border: 1px solid #e0e0e0; padding: 20px; margin: 10px; }
            QLineEdit, QDateTimeEdit, QComboBox { border: 1px solid #bdc3c7; border-radius: 5px; padding: 10px; font-size: 16px; }
            QPushButton { background-color: #3498db; color: white; border: none; padding: 12px 18px; border-radius: 5px; font-weight: bold; font-size: 16px; }
            QPushButton:hover { background-color: #2980b9; }
            QLabel { font-weight: bold; color: #34495e; font-size: 16px; }
            QTableWidget, QListWidget { border: 1px solid #ecf0f1; border-radius: 5px; background-color: #ffffff; font-size: 16px; }
            QHeaderView::section { background-color: #34495e; color: white; padding: 8px; font-size: 15px; }
            QTabBar::tab { font-size: 16px; padding: 10px; }
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
        
        self.update_ui_for_api_key()
        if self.api_key:
            self.fetch_school_info()
            self.load_file_tasks()
            self.load_data_reports()
        else:
            QMessageBox.information(self, "Chào mừng", "Vui lòng nhập Mã API được cung cấp và nhấn 'Lưu'.")

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
        self.load_ft_button = QPushButton("Tải lại danh sách")
        self.load_ft_button.clicked.connect(self.load_file_tasks)
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
        submit_title_label = QLabel("Nộp bài")
        submit_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        submit_layout.addWidget(submit_title_label)
        self.submit_file_button = QPushButton("Nộp file cho công việc đã chọn")
        self.ft_status_label = QLabel("Sẵn sàng.")
        submit_layout.addWidget(self.submit_file_button)
        submit_layout.addWidget(self.ft_status_label)
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
        
        self.load_dr_button = QPushButton("Tải lại danh sách")
        self.load_dr_button.clicked.connect(self.load_data_reports)
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
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
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
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.get(f"{API_URL}/file-tasks/", headers=headers)
            self.ft_todo_table.setRowCount(0)
            self.ft_overdue_table.setRowCount(0)
            if response.status_code == 200:
                tasks = response.json()
                now = datetime.now()
                for task in tasks:
                    deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%dT%H:%M:%S")
                    is_submitted = task.get('is_submitted', False)
                    status_text = "Đã thực hiện" if is_submitted else "Chưa thực hiện"
                    status_item = QTableWidgetItem(status_text)
                    status_item.setTextAlignment(Qt.AlignCenter)
                    status_item.setForeground(QColor("green") if is_submitted else QColor("red"))
                    
                    title_item = QTableWidgetItem(task['title'])
                    title_item.setData(Qt.UserRole, task['id'])
                    deadline_item = QTableWidgetItem(deadline_dt.strftime("%H:%M %d/%m/%Y"))
                    
                    table = self.ft_todo_table if deadline_dt > now else self.ft_overdue_table
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(row, 0, title_item)
                    table.setItem(row, 1, deadline_item)
                    table.setItem(row, 2, status_item)
            else:
                QMessageBox.critical(self, "Lỗi API", "Không thể tải danh sách công việc nộp file.")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server.")

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

        try:
            self.ft_status_label.setText("Đang lấy thông tin thư mục nộp bài...")
            QApplication.processEvents()

            headers = {"x-api-key": self.api_key}
            response = requests.get(f"{API_URL}/file-tasks/{task_id}/upload-folder", headers=headers)
            if response.status_code != 200:
                raise Exception(f"Lỗi lấy thư mục: {response.json().get('detail', response.text)}")
            
            upload_folder_id = response.json().get("folder_id")
            if not upload_folder_id:
                 raise Exception("Server không trả về ID thư mục hợp lệ.")

            self.ft_status_label.setText("Đang kết nối Google Drive...")
            QApplication.processEvents()
            service = get_drive_service()
            
            self.ft_status_label.setText("Đang tải file lên...")
            QApplication.processEvents()
            file_url, error = upload_file_to_drive(service, file_path, upload_folder_id)
            if error: raise Exception(error)
            
            self.ft_status_label.setText("Đang báo cáo về server...")
            QApplication.processEvents()
            payload = {"task_id": task_id, "file_url": file_url}
            response = requests.post(f"{API_URL}/file-submissions/", headers=headers, json=payload)
            if response.status_code == 200:
                QMessageBox.information(self, "Hoàn tất", "Nộp bài thành công!")
                self.ft_status_label.setText(f"Đã nộp bài thành công cho ID {task_id}.")
                self.load_file_tasks()
            else:
                raise Exception(response.json().get('detail', response.text))
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Quá trình nộp bài thất bại.\n\nChi tiết: {e}")
            self.ft_status_label.setText("Nộp bài thất bại!")

    def load_data_reports(self):
        if not self.api_key: return
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.get(f"{API_URL}/data-reports/", headers=headers)
            if response.status_code == 200:
                self.dr_list_widget.clear()
                for report in response.json():
                    deadline_dt = datetime.strptime(report['deadline'], "%Y-%m-%dT%H:%M:%S")
                    deadline_str = deadline_dt.strftime("%H:%M %d/%m/%Y")
                    is_submitted = report.get('is_submitted', False)
                    
                    list_item = QListWidgetItem()
                    list_item.setData(Qt.UserRole, report)
                    custom_widget = ListItemWidget(report['id'], report['title'], deadline_str, is_submitted)
                    list_item.setSizeHint(custom_widget.sizeHint())
                    self.dr_list_widget.addItem(list_item)
                    self.dr_list_widget.setItemWidget(list_item, custom_widget)
            else:
                QMessageBox.critical(self, "Lỗi API", "Không thể tải danh sách báo cáo nhập liệu.")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server.")

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
        QApplication.processEvents()
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.post(f"{API_URL}/data-reports/{report_id}/complete", headers=headers)
            if response.status_code == 200:
                QMessageBox.information(self, "Thành công", "Đã đánh dấu báo cáo là hoàn thành.")
                self.dr_status_label.setText(f"Đã hoàn thành báo cáo ID {report_id}.")
                self.load_data_reports()
            else:
                raise Exception(response.json().get('detail', response.text))
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể đánh dấu hoàn thành.\n\nChi tiết: {e}")
            self.dr_status_label.setText("Thao tác thất bại!")

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
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        self.update_ui_for_api_key()
        self.ft_todo_table.setRowCount(0)
        self.ft_overdue_table.setRowCount(0)
        self.dr_list_widget.clear()
        self.api_key_input.setFocus()
        QMessageBox.information(self, "Thông báo", "Vui lòng nhập Mã API mới và nhấn 'Lưu'.")

    def fetch_school_info(self):
        if not self.api_key: return False
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.get(f"{API_URL}/schools/me", headers=headers)
            if response.status_code == 200:
                data = response.json()
                self.school_info_label.setText(f"Đang làm việc với tư cách: Trường {data.get('name')}")
                return True
            else:
                self.school_info_label.setText("Trạng thái: Mã API không hợp lệ.")
                self.edit_api_key_handler()
                return False
        except requests.exceptions.ConnectionError:
            self.school_info_label.setText("Trạng thái: Không thể kết nối đến server.")
            return False

    def load_api_key(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return f.read().strip()
        return None

    def save_api_key_handler(self):
        key = self.api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Lỗi", "Mã API không được để trống.")
            return
        self.api_key = key
        if self.fetch_school_info():
            with open(CONFIG_FILE, 'w') as f:
                f.write(self.api_key)
            self.update_ui_for_api_key()
            self.load_file_tasks()
            self.load_data_reports()
        else:
            self.api_key = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())
