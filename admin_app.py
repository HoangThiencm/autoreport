# admin_app.py (REFACTORED TO USE QNetworkAccessManager)
import sys
import os
import webbrowser
import requests # Chỉ dùng cho handle_api_error, không dùng cho gọi API chính
import json
from typing import Callable

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QMessageBox, QLineEdit, QLabel,
    QTabWidget, QTextEdit, QDateTimeEdit, QComboBox, QFrame, QGridLayout,
    QListWidgetItem, QDateEdit, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QInputDialog
)
from PySide6.QtCore import QDateTime, Qt, QDate, QUrl, QTimeZone, QByteArray, QUrlQuery
from PySide6.QtGui import QIcon, QColor, QFont, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

import clipboard

https://auto-report-backend.onrender.com

def handle_api_error(self, status_code, response_text, context_message):
    detail = response_text
    try:
        error_data = json.loads(response_text)
        detail = error_data.get('detail', response_text)
    except json.JSONDecodeError:
        pass # detail is already the response_text
    QMessageBox.critical(self, "Lỗi", f"{context_message}\nLỗi từ server (Code: {status_code}): {detail}")

# --- CÁC WIDGET TÙY CHỈNH ---
class SchoolListItemWidget(QWidget):
    def __init__(self, school_id, name, api_key, parent=None):
        super().__init__(parent)
        self.school_id = school_id
        self.api_key = api_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        self.name_label = QLabel(f"<b>{name}</b>")
        self.key_label = QLineEdit(api_key)
        self.key_label.setReadOnly(True)
        self.key_label.setStyleSheet("background-color: #f1f1f1; border: 1px solid #ccc; padding: 5px; border-radius: 4px;")
        self.copy_button = QPushButton("Sao chép")
        self.copy_button.setStyleSheet("padding: 5px 10px; font-size: 14px;")
        self.copy_button.clicked.connect(self.copy_api_key)
        self.delete_button = QPushButton("Xóa")
        self.delete_button.setStyleSheet("background-color: #e74c3c; padding: 5px 10px; font-size: 14px;")
        self.delete_button.clicked.connect(self.delete_school)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(QLabel("API Key:"))
        layout.addWidget(self.key_label, 2)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.delete_button)

    def copy_api_key(self):
        clipboard.copy(self.api_key)
        QMessageBox.information(self, "Thành công", "Đã sao chép API Key vào clipboard!")

    def delete_school(self):
        main_window = self.window()
        if not isinstance(main_window, AdminWindow): return

        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc chắn muốn xóa trường '{self.name_label.text().strip('<b></b>')}' không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            main_window.api_delete(
                f"/schools/{self.school_id}",
                on_success=lambda data, headers: (
                    QMessageBox.information(self, "Thành công", "Đã xóa trường thành công."),
                    main_window.load_schools()
                ),
                on_error=lambda status, err: handle_api_error(self, status, err, "Không thể xóa trường.")
            )

class ListItemWidget(QWidget):
    def __init__(self, item_id, title, deadline, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.title_label = QLabel(f"<b>ID {item_id}: {title}</b>")
        self.deadline_label = QLabel(f"Hạn chót: {deadline}")
        self.deadline_label.setStyleSheet("color: #666; font-weight: normal;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.deadline_label)

class DashboardCard(QPushButton):
    def __init__(self, icon_svg_data, title, description, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("DashboardCard")
        self.setStyleSheet("""
            #DashboardCard { background-color: white; border: 1px solid #e0e0e0; border-radius: 10px; text-align: left; padding: 20px; }
            #DashboardCard:hover { background-color: #f0f4f8; border: 1px solid #3498db; }
            #CardTitle { font-size: 18px; font-weight: bold; color: #2c3e50; margin-top: 10px; }
            #CardDescription { font-size: 14px; color: #7f8c8d; margin-top: 5px; font-weight: normal;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(60, 60)
        self.set_icon(icon_svg_data)
        layout.addWidget(self.icon_label)
        layout.addSpacing(15)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        description_label = QLabel(description)
        description_label.setObjectName("CardDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

    def set_icon(self, svg_data):
        renderer = QSvgRenderer(svg_data.encode('utf-8'))
        pixmap = QPixmap(self.icon_label.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        self.icon_label.setPixmap(pixmap)

# --- CỬA SỔ CHÍNH ---
class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.network_manager = QNetworkAccessManager(self)
        self.setWindowTitle("Bảng điều khiển cho Quản trị viên")
        if os.path.exists('baocao.ico'):
            self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(100, 100, 1280, 800)
        font = QFont("Segoe UI", 10)
        self.setFont(font)
        self.setStyleSheet("""
            QMainWindow { background-color: #f4f6f9; }
            QFrame#card { background-color: white; border-radius: 8px; border: 1px solid #dfe4ea; padding: 20px; margin: 10px; }
            QLineEdit, QTextEdit, QDateTimeEdit, QComboBox, QDateEdit { border: 1px solid #ced4da; border-radius: 5px; padding: 10px; font-size: 16px; background-color: #ffffff;}
            QPushButton { background-color: #3498db; color: white; border: none; padding: 12px 18px; border-radius: 5px; font-weight: bold; font-size: 16px; }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:disabled { background-color: #bdc3c7; }
            QLabel { color: #34495e; font-size: 16px; }
            QLabel#main_title { font-size: 28px; font-weight: bold; color: #e74c3c; }
            QLabel#subtitle { font-size: 20px; font-weight: bold; color: #e74c3c; margin-bottom: 20px; }
            QListWidget, QTableWidget { border: 1px solid #dfe4ea; border-radius: 5px; background-color: #ffffff; font-size: 16px;}
            QHeaderView::section { background-color: #e9ecef; color: #495057; padding: 10px; font-size: 14px; font-weight: bold; border: none;}
            QTabBar::tab { font-size: 16px; padding: 12px 20px; font-weight: bold;}
            QTabWidget::pane { border: none; }
        """)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.dashboard_tab, self.school_years_tab, self.schools_tab, self.file_tasks_tab, self.data_reports_tab, self.report_tab, self.settings_tab = (QWidget() for _ in range(7))
        self.create_main_dashboard()
        self.create_school_years_tab()
        self.create_schools_tab()
        self.create_file_tasks_tab()
        self.create_data_reports_tab()
        self.create_report_tab()
        self.create_settings_tab()
        for widget in [self.dashboard_tab, self.school_years_tab, self.schools_tab, self.file_tasks_tab, self.data_reports_tab, self.report_tab, self.settings_tab]:
            self.stacked_widget.addWidget(widget)
        self.stacked_widget.setCurrentWidget(self.dashboard_tab)
        
        self.load_all_initial_data()

    def _handle_reply(self, reply: QNetworkReply, on_success: Callable, on_error: Callable):
        if reply.error() == QNetworkReply.NoError:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            headers = {
                bytes(key).decode('utf-8'): bytes(reply.rawHeader(bytes(key).decode('utf-8'))).decode('utf-8')
                for key in reply.rawHeaderList()
            }
            response_data = bytes(reply.readAll()).decode('utf-8')
            
            if 200 <= status_code < 300:
                try:
                    json_data = json.loads(response_data) if response_data else {}
                    on_success(json_data, headers)
                except json.JSONDecodeError:
                    on_error(status_code, "Lỗi giải mã JSON từ server.")
            else:
                on_error(status_code, response_data)
        else:
            on_error(0, f"Lỗi mạng: {reply.errorString()}")
        reply.deleteLater()
        
    def api_get(self, endpoint: str, on_success: Callable, on_error: Callable, params: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        if params:
            query = QUrlQuery()
            for key, value in params.items():
                query.addQueryItem(key, str(value))
            url.setQuery(query)
        
        request = QNetworkRequest(url)
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_post(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable):
        url = QUrl(f"{API_URL}{endpoint}")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps(data).encode('utf-8'))
        reply = self.network_manager.post(request, payload)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_delete(self, endpoint: str, on_success: Callable, on_error: Callable):
        url = QUrl(f"{API_URL}{endpoint}")
        request = QNetworkRequest(url)
        reply = self.network_manager.deleteResource(request)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))
    
    def api_download(self, endpoint: str, on_success: Callable, on_error: Callable):
        url = QUrl(f"{API_URL}{endpoint}")
        request = QNetworkRequest(url)
        reply = self.network_manager.get(request)

        def handle_download_reply():
            if reply.error() == QNetworkReply.NoError:
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code == 200:
                    on_success(reply.readAll())
                else:
                    on_error(status_code, bytes(reply.readAll()).decode('utf-8'))
            else:
                on_error(0, f"Lỗi mạng: {reply.errorString()}")
            reply.deleteLater()
            
        reply.finished.connect(handle_download_reply)

    def load_all_initial_data(self):
        self.load_school_years()
        self.load_schools()
        self.load_file_tasks()
        self.load_data_reports()

    def create_main_dashboard(self):
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(40, 20, 40, 20)
        layout.setAlignment(Qt.AlignCenter)
        header_frame = QFrame()
        header_layout = QVBoxLayout(header_frame)
        main_title = QLabel("HỆ THỐNG QUẢN LÝ BÁO CÁO TRƯỜNG HỌC") 
        main_title.setObjectName("main_title")
        subtitle = QLabel("PHÒNG VĂN HÓA - XÃ HỘI PHƯỜNG HỐ NAI")
        subtitle.setObjectName("subtitle")
        header_layout.addWidget(main_title, alignment=Qt.AlignCenter)
        header_layout.addWidget(subtitle, alignment=Qt.AlignCenter)
        layout.addWidget(header_frame)
        dashboard_layout = QGridLayout()
        dashboard_layout.setSpacing(25)
        dashboard_layout.setAlignment(Qt.AlignCenter)
        cards_info = [
            ("QUẢN LÝ NĂM HỌC", "Tạo và quản lý các năm học.", lambda: self.stacked_widget.setCurrentWidget(self.school_years_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3498db" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>'),
            ("QUẢN LÝ NHÀ TRƯỜNG", "Thêm trường và cấp mã API.", lambda: self.stacked_widget.setCurrentWidget(self.schools_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#2ecc71" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'),
            ("BÁO CÁO NỘP FILE", "Ban hành yêu cầu nộp văn bản.", lambda: self.stacked_widget.setCurrentWidget(self.file_tasks_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#9b59b6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>'),
            ("BÁO CÁO NHẬP LIỆU", "Ban hành yêu cầu qua Google Sheet.", lambda: self.stacked_widget.setCurrentWidget(self.data_reports_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e67e22" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>'),
            ("XEM BÁO CÁO", "Theo dõi và tải về các báo cáo.", lambda: self.stacked_widget.setCurrentWidget(self.report_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1abc9c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>'),
            ("CÀI ĐẶT", "Các chức năng quản trị hệ thống.", lambda: self.stacked_widget.setCurrentWidget(self.settings_tab), '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e74c3c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>')
        ]
        for i, (title, desc, action, icon) in enumerate(cards_info):
            card = DashboardCard(icon, title, desc)
            card.clicked.connect(action)
            dashboard_layout.addWidget(card, i // 3, i % 3)
        layout.addLayout(dashboard_layout)
        layout.addStretch(1)

    def create_school_years_tab(self):
        layout = QVBoxLayout(self.school_years_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        form_card = QFrame()
        form_card.setObjectName("card")
        form_layout = QVBoxLayout(form_card)
        form_layout.addWidget(QLabel("Tạo Năm học mới"))
        self.sy_name_input = QLineEdit()
        self.sy_name_input.setPlaceholderText("Ví dụ: Năm học 2024-2025")
        self.sy_start_date_input = QDateEdit(QDate.currentDate())
        self.sy_start_date_input.setCalendarPopup(True)
        self.sy_end_date_input = QDateEdit(QDate.currentDate().addYears(1))
        self.sy_end_date_input.setCalendarPopup(True)
        self.add_sy_button = QPushButton("Thêm Năm học")
        form_layout.addWidget(QLabel("Tên Năm học:"))
        form_layout.addWidget(self.sy_name_input)
        form_layout.addWidget(QLabel("Ngày bắt đầu:"))
        form_layout.addWidget(self.sy_start_date_input)
        form_layout.addWidget(QLabel("Ngày kết thúc:"))
        form_layout.addWidget(self.sy_end_date_input)
        form_layout.addWidget(self.add_sy_button)
        form_layout.addStretch()
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("Danh sách các Năm học"))
        self.school_years_list_widget_tab = QListWidget() 
        list_layout.addWidget(self.school_years_list_widget_tab)
        layout.addWidget(form_card, 1)
        layout.addWidget(list_card, 2)
        self.add_sy_button.clicked.connect(self.add_new_school_year)

    def create_schools_tab(self):
        layout = QVBoxLayout(self.schools_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        input_card = QFrame()
        input_card.setObjectName("card")
        input_layout = QGridLayout(input_card)
        title_label = QLabel("Thêm Trường học Mới")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        input_layout.addWidget(title_label, 0, 0, 1, 2)
        input_layout.addWidget(QLabel("Tên trường:"), 1, 0)
        self.school_name_input = QLineEdit()
        self.school_name_input.setPlaceholderText("Nhập tên trường mới...")
        input_layout.addWidget(self.school_name_input, 1, 1)
        self.add_school_button = QPushButton("Thêm Trường")
        input_layout.addWidget(self.add_school_button, 2, 0, 1, 2)
        layout.addWidget(input_card)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_title_label = QLabel("Danh sách Trường học và API Key")
        list_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        list_layout.addWidget(list_title_label)
        self.schools_list_widget = QListWidget()
        list_layout.addWidget(self.schools_list_widget)
        layout.addWidget(list_card)
        self.add_school_button.clicked.connect(self.add_new_school)

    def create_file_tasks_tab(self):
        layout = QVBoxLayout(self.file_tasks_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        input_card = QFrame()
        input_card.setObjectName("card")
        input_layout = QGridLayout(input_card)
        title_label = QLabel("Ban hành Yêu cầu Nộp File")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        input_layout.addWidget(title_label, 0, 0, 1, 2)
        input_layout.addWidget(QLabel("Chọn Năm học:"), 1, 0)
        self.ft_school_year_selector = QComboBox()
        input_layout.addWidget(self.ft_school_year_selector, 1, 1)
        input_layout.addWidget(QLabel("Tiêu đề:"), 2, 0)
        self.ft_title_input = QLineEdit()
        input_layout.addWidget(self.ft_title_input, 2, 1)
        input_layout.addWidget(QLabel("Nội dung:"), 3, 0)
        self.ft_content_input = QTextEdit()
        input_layout.addWidget(self.ft_content_input, 3, 1)
        input_layout.addWidget(QLabel("Thời hạn (Deadline):"), 4, 0)
        self.ft_deadline_input = QDateTimeEdit(QDateTime.currentDateTime().addDays(7))
        self.ft_deadline_input.setCalendarPopup(True)
        self.ft_deadline_input.setDisplayFormat("HH:mm dd/MM/yyyy")
        input_layout.addWidget(self.ft_deadline_input, 4, 1)
        self.add_ft_button = QPushButton("Phát hành")
        input_layout.addWidget(self.add_ft_button, 5, 0, 1, 2)
        layout.addWidget(input_card)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_title_label = QLabel("Danh sách yêu cầu đã ban hành")
        list_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        task_filter_layout = QHBoxLayout()
        task_filter_layout.addWidget(QLabel("Lọc theo năm học:"))
        self.ft_filter_sy_selector = QComboBox()
        self.ft_filter_sy_selector.addItem("Tất cả", userData=None)
        self.ft_filter_sy_selector.currentIndexChanged.connect(self.load_file_tasks)
        task_filter_layout.addWidget(self.ft_filter_sy_selector)
        task_filter_layout.addStretch()
        list_layout.addWidget(list_title_label)
        list_layout.addLayout(task_filter_layout)
        self.file_tasks_list_widget = QListWidget()
        list_layout.addWidget(self.file_tasks_list_widget)
        layout.addWidget(list_card)
        self.add_ft_button.clicked.connect(self.add_new_file_task)

    def create_data_reports_tab(self):
        layout = QVBoxLayout(self.data_reports_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        design_card = QFrame()
        design_card.setObjectName("card")
        design_layout = QGridLayout(design_card)
        title_label = QLabel("Ban hành Báo cáo Nhập liệu (Google Sheet)")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        design_layout.addWidget(title_label, 0, 0, 1, 2)
        design_layout.addWidget(QLabel("Năm học:"), 1, 0)
        self.dr_school_year_selector = QComboBox()
        design_layout.addWidget(self.dr_school_year_selector, 1, 1)
        design_layout.addWidget(QLabel("Tiêu đề báo cáo:"), 2, 0)
        self.dr_title_input = QLineEdit()
        design_layout.addWidget(self.dr_title_input, 2, 1)
        design_layout.addWidget(QLabel("URL Google Sheet Mẫu:"), 3, 0)
        self.dr_template_url_input = QLineEdit()
        self.dr_template_url_input.setPlaceholderText("Dán link Google Sheet mẫu vào đây...")
        design_layout.addWidget(self.dr_template_url_input, 3, 1)
        design_layout.addWidget(QLabel("Hạn chót:"), 4, 0)
        self.dr_deadline_input = QDateTimeEdit(QDateTime.currentDateTime().addDays(7))
        self.dr_deadline_input.setCalendarPopup(True)
        self.dr_deadline_input.setDisplayFormat("HH:mm dd/MM/yyyy")
        design_layout.addWidget(self.dr_deadline_input, 4, 1)
        self.add_dr_button = QPushButton("Ban hành Báo cáo")
        self.add_dr_button.setStyleSheet("background-color: #27ae60;")
        self.add_dr_button.clicked.connect(self.add_new_data_report)
        design_layout.addWidget(self.add_dr_button, 5, 0, 1, 2)
        layout.addWidget(design_card)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("Danh sách đã ban hành"))
        self.data_reports_list_widget = QListWidget()
        list_layout.addWidget(self.data_reports_list_widget)
        layout.addWidget(list_card)

    def create_report_tab(self):
        layout = QVBoxLayout(self.report_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        self.report_tabs = QTabWidget()
        self.file_report_tab = QWidget()
        self.data_report_tab = QWidget()
        self.report_tabs.addTab(self.file_report_tab, "Báo cáo Nộp File")
        self.report_tabs.addTab(self.data_report_tab, "Báo cáo Nhập liệu")
        self.create_file_report_ui()
        self.create_data_report_ui()
        layout.addWidget(self.report_tabs)

    def create_file_report_ui(self):
        layout = QVBoxLayout(self.file_report_tab)
        control_card = QFrame()
        control_card.setObjectName("card")
        control_layout = QHBoxLayout(control_card)
        control_layout.addWidget(QLabel("Chọn yêu cầu:"))
        self.fr_task_selector = QComboBox()
        self.fr_task_selector.currentIndexChanged.connect(self.load_file_task_report)
        control_layout.addWidget(self.fr_task_selector, 1)
        self.fr_remind_button = QPushButton("Gửi nhắc nhở")
        self.fr_remind_button.setStyleSheet("background-color: #e67e22;")
        self.fr_remind_button.clicked.connect(lambda: self.send_reminder_handler("file"))
        control_layout.addWidget(self.fr_remind_button)
        self.fr_refresh_button = QPushButton("Làm mới")
        self.fr_refresh_button.setStyleSheet("background-color: #f39c12;")
        self.fr_refresh_button.clicked.connect(self.load_file_task_report)
        control_layout.addWidget(self.fr_refresh_button)
        self.fr_download_button = QPushButton("Tải tất cả file đã nộp")
        self.fr_download_button.setStyleSheet("background-color: #27ae60;")
        self.fr_download_button.clicked.connect(self.download_all_files)
        control_layout.addWidget(self.fr_download_button)
        layout.addWidget(control_card)
        report_card = QFrame()
        report_card.setObjectName("card")
        report_layout = QVBoxLayout(report_card)
        self.fr_title_label = QLabel("Báo cáo chi tiết")
        self.fr_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        report_layout.addWidget(self.fr_title_label)
        self.fr_table = QTableWidget()
        self.fr_table.setColumnCount(4)
        self.fr_table.setHorizontalHeaderLabels(["STT", "Tên trường", "Trạng thái", "Thời gian nộp"])
        self.fr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.fr_table.setEditTriggers(QTableWidget.NoEditTriggers)
        report_layout.addWidget(self.fr_table)
        layout.addWidget(report_card)

    def create_data_report_ui(self):
        layout = QVBoxLayout(self.data_report_tab)
        control_card = QFrame()
        control_card.setObjectName("card")
        control_layout = QHBoxLayout(control_card)
        control_layout.addWidget(QLabel("Chọn báo cáo:"))
        self.dr_report_selector = QComboBox()
        self.dr_report_selector.currentIndexChanged.connect(self.load_data_entry_report)
        control_layout.addWidget(self.dr_report_selector, 1)
        self.dr_remind_button = QPushButton("Gửi nhắc nhở")
        self.dr_remind_button.setStyleSheet("background-color: #e67e22;")
        self.dr_remind_button.clicked.connect(lambda: self.send_reminder_handler("data"))
        control_layout.addWidget(self.dr_remind_button)
        self.dr_refresh_button = QPushButton("Làm mới")
        self.dr_refresh_button.setStyleSheet("background-color: #f39c12;")
        self.dr_refresh_button.clicked.connect(self.load_data_entry_report)
        control_layout.addWidget(self.dr_refresh_button)
        layout.addWidget(control_card)
        report_card = QFrame()
        report_card.setObjectName("card")
        report_layout = QVBoxLayout(report_card)
        self.dr_title_label = QLabel("Báo cáo chi tiết")
        self.dr_title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        report_layout.addWidget(self.dr_title_label)
        self.dr_table = QTableWidget()
        self.dr_table.setColumnCount(4)
        self.dr_table.setHorizontalHeaderLabels(["STT", "Tên trường", "Trạng thái", "Thời gian hoàn thành"])
        self.dr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.dr_table.setEditTriggers(QTableWidget.NoEditTriggers)
        report_layout.addWidget(self.dr_table)
        layout.addWidget(report_card)

    def create_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        back_button = QPushButton("⬅️ Quay lại trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        danger_zone_card = QFrame()
        danger_zone_card.setObjectName("card")
        danger_zone_card.setStyleSheet("#card { border: 2px solid #e74c3c; }")
        danger_layout = QVBoxLayout(danger_zone_card)
        title = QLabel("🔴 KHU VỰC NGUY HIỂM")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #e74c3c;")
        danger_layout.addWidget(title)
        description = QLabel("Các hành động dưới đây không thể hoàn tác. Hãy chắc chắn trước khi thực hiện.")
        description.setWordWrap(True)
        danger_layout.addWidget(description)
        danger_layout.addSpacing(20)
        self.reset_db_button = QPushButton("Xóa Toàn Bộ Dữ Liệu")
        self.reset_db_button.setStyleSheet("background-color: #e74c3c;")
        self.reset_db_button.clicked.connect(self.handle_reset_database)
        danger_layout.addWidget(self.reset_db_button)
        layout.addWidget(danger_zone_card)
        layout.addStretch()

    def add_new_school_year(self):
        name = self.sy_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên năm học.")
            return
        payload = {"name": name, "start_date": self.sy_start_date_input.date().toString("yyyy-MM-dd"), "end_date": self.sy_end_date_input.date().toString("yyyy-MM-dd")}
        
        self.add_sy_button.setDisabled(True)
        self.add_sy_button.setText("Đang xử lý...")

        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", f"Đã thêm năm học '{name}' thành công.")
            self.sy_name_input.clear()
            self.load_school_years()
            self.add_sy_button.setDisabled(False)
            self.add_sy_button.setText("Thêm Năm học")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể thêm năm học.")
            self.add_sy_button.setDisabled(False)
            self.add_sy_button.setText("Thêm Năm học")

        self.api_post("/school_years/", payload, on_success, on_error)

    def load_school_years(self):
        def on_success(data, headers):
            selectors = [self.ft_school_year_selector, self.ft_filter_sy_selector, self.dr_school_year_selector]
            for selector in selectors:
                selector.clear()
            self.school_years_list_widget_tab.clear()
            self.ft_filter_sy_selector.addItem("Tất cả", userData=None)
            for sy in data:
                item_text = f"ID {sy['id']}: {sy['name']} ({sy['start_date']} - {sy['end_date']})"
                list_item = QListWidgetItem(item_text)
                list_item.setData(Qt.UserRole, sy['id'])
                self.school_years_list_widget_tab.addItem(list_item)
                for selector in [self.ft_school_year_selector, self.dr_school_year_selector, self.ft_filter_sy_selector]:
                    selector.addItem(sy['name'], userData=sy['id'])
        
        def on_error(status, err):
            QMessageBox.critical(self, "Lỗi tải năm học", err)

        self.api_get("/school_years/", on_success, on_error)

    def load_schools(self):
        def on_success(data, headers):
            self.schools_list_widget.clear()
            for school in data:
                list_item = QListWidgetItem()
                custom_widget = SchoolListItemWidget(school['id'], school['name'], school['api_key'], parent=self.schools_list_widget)
                list_item.setSizeHint(custom_widget.sizeHint())
                self.schools_list_widget.addItem(list_item)
                self.schools_list_widget.setItemWidget(list_item, custom_widget)
        
        def on_error(status, err):
            QMessageBox.critical(self, "Lỗi tải trường học", err)

        self.api_get("/schools/", on_success, on_error)

    def add_new_school(self):
        school_name = self.school_name_input.text().strip()
        if not school_name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên trường.")
            return
        
        self.add_school_button.setDisabled(True)
        self.add_school_button.setText("Đang thêm...")

        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", f"Đã thêm trường '{school_name}' thành công.")
            self.school_name_input.clear()
            self.load_schools()
            self.add_school_button.setDisabled(False)
            self.add_school_button.setText("Thêm Trường")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể thêm trường.")
            self.add_school_button.setDisabled(False)
            self.add_school_button.setText("Thêm Trường")

        self.api_post("/schools/", {"name": school_name}, on_success, on_error)

    def load_file_tasks(self):
        school_year_id = self.ft_filter_sy_selector.currentData()
        params = {}
        if school_year_id:
            params['school_year_id'] = school_year_id

        def on_success(data, headers):
            self.file_tasks_list_widget.clear()
            self.fr_task_selector.clear()
            for task in data:
                deadline_local = QDateTime.fromString(task['deadline'], "yyyy-MM-dd'T'HH:mm:ss")
                deadline_str = deadline_local.toString("HH:mm dd/MM/yyyy")
                list_item = QListWidgetItem()
                custom_widget = ListItemWidget(task['id'], task['title'], deadline_str)
                list_item.setSizeHint(custom_widget.sizeHint())
                self.file_tasks_list_widget.addItem(list_item)
                self.file_tasks_list_widget.setItemWidget(list_item, custom_widget)
                self.fr_task_selector.addItem(f"ID {task['id']}: {task['title']}", userData=task['id'])

        def on_error(status, err):
            QMessageBox.critical(self, "Lỗi tải công việc", err)

        self.api_get("/file-tasks/", on_success, on_error, params=params)

    def add_new_file_task(self):
        school_year_id = self.ft_school_year_selector.currentData()
        title = self.ft_title_input.text().strip()
        content = self.ft_content_input.toPlainText().strip()
        if not title or not content or not school_year_id:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ thông tin.")
            return

        self.add_ft_button.setDisabled(True)
        self.add_ft_button.setText("Đang phát hành...")
        deadline_local = self.ft_deadline_input.dateTime()
        payload = {"title": title, "content": content, "deadline": deadline_local.toString("yyyy-MM-dd'T'HH:mm:ss"), "school_year_id": school_year_id}
        
        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", "Đã ban hành yêu cầu mới.")
            self.ft_title_input.clear()
            self.ft_content_input.clear()
            self.load_file_tasks()
            self.add_ft_button.setDisabled(False)
            self.add_ft_button.setText("Phát hành")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tạo yêu cầu.")
            self.add_ft_button.setDisabled(False)
            self.add_ft_button.setText("Phát hành")

        self.api_post("/file-tasks/", payload, on_success, on_error)
        
    def load_data_reports(self):
        def on_success(data, headers):
            self.data_reports_list_widget.clear()
            self.dr_report_selector.clear()
            for report in data:
                deadline_local = QDateTime.fromString(report['deadline'], "yyyy-MM-dd'T'HH:mm:ss")
                deadline_str = deadline_local.toString("HH:mm dd/MM/yyyy")
                list_item = QListWidgetItem()
                custom_widget = ListItemWidget(report['id'], report['title'], deadline_str)
                list_item.setSizeHint(custom_widget.sizeHint())
                self.data_reports_list_widget.addItem(list_item)
                self.data_reports_list_widget.setItemWidget(list_item, custom_widget)
                self.dr_report_selector.addItem(f"ID {report['id']}: {report['title']}", userData=report['id'])
        
        def on_error(status, err):
            QMessageBox.critical(self, "Lỗi tải báo cáo", err)

        self.api_get("/data-reports/", on_success, on_error)

    def add_new_data_report(self):
        school_year_id = self.dr_school_year_selector.currentData()
        title = self.dr_title_input.text().strip()
        template_url = self.dr_template_url_input.text().strip()
        if not all([title, school_year_id, template_url]):
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ Tiêu đề, URL và chọn Năm học.")
            return

        self.add_dr_button.setDisabled(True)
        self.add_dr_button.setText("Đang ban hành...")
        deadline_local = self.dr_deadline_input.dateTime()
        payload = {"title": title, "deadline": deadline_local.toString("yyyy-MM-dd'T'HH:mm:ss"), "school_year_id": school_year_id, "template_url": template_url}
        
        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", "Đã ban hành báo cáo nhập liệu mới.")
            self.dr_title_input.clear()
            self.dr_template_url_input.clear()
            self.load_data_reports()
            self.add_dr_button.setDisabled(False)
            self.add_dr_button.setText("Ban hành Báo cáo")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tạo báo cáo.")
            self.add_dr_button.setDisabled(False)
            self.add_dr_button.setText("Ban hành Báo cáo")

        self.api_post("/data-reports/", payload, on_success, on_error)
        
    def load_file_task_report(self):
        task_id = self.fr_task_selector.currentData()
        if task_id is None:
            self.fr_table.setRowCount(0)
            self.fr_title_label.setText("Vui lòng chọn một yêu cầu")
            return
        
        self.fr_refresh_button.setDisabled(True)
        self.fr_refresh_button.setText("Đang tải...")

        def on_success(data, headers):
            task_title = data.get('task', {}).get('title', '')
            self.fr_title_label.setText(f"Báo cáo chi tiết cho: {task_title}")
            submitted = data.get('submitted_schools', [])
            not_submitted = data.get('not_submitted_schools', [])
            
            self.fr_table.setRowCount(0)
            self.fr_table.setRowCount(len(submitted) + len(not_submitted))
            
            stt = 0
            for school_info in submitted:
                stt_item = QTableWidgetItem(str(stt + 1))
                name_item = QTableWidgetItem(school_info['name'])
                status_item = QTableWidgetItem("Đã nộp")
                status_item.setForeground(QColor("green"))
                
                submitted_at_dt = QDateTime.fromString(school_info['submitted_at'], "yyyy-MM-dd'T'HH:mm:ss")
                submitted_at_dt.setTimeZone(QTimeZone(b"UTC"))
                submitted_at_local = submitted_at_dt.toLocalTime()
                time_item = QTableWidgetItem(submitted_at_local.toString("HH:mm dd/MM/yyyy"))

                self.fr_table.setItem(stt, 0, stt_item)
                self.fr_table.setItem(stt, 1, name_item)
                self.fr_table.setItem(stt, 2, status_item)
                self.fr_table.setItem(stt, 3, time_item)
                stt += 1

            for school in not_submitted:
                stt_item = QTableWidgetItem(str(stt + 1))
                name_item = QTableWidgetItem(school['name'])
                status_item = QTableWidgetItem("Chưa nộp")
                status_item.setForeground(QColor("red"))
                time_item = QTableWidgetItem("")

                self.fr_table.setItem(stt, 0, stt_item)
                self.fr_table.setItem(stt, 1, name_item)
                self.fr_table.setItem(stt, 2, status_item)
                self.fr_table.setItem(stt, 3, time_item)
                stt += 1
            
            self.fr_table.resizeColumnsToContents()
            self.fr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.fr_refresh_button.setDisabled(False)
            self.fr_refresh_button.setText("Làm mới")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tải dữ liệu báo cáo.")
            self.fr_refresh_button.setDisabled(False)
            self.fr_refresh_button.setText("Làm mới")

        self.api_get(f"/file-tasks/{task_id}/status", on_success, on_error)

    def load_data_entry_report(self):
        report_id = self.dr_report_selector.currentData()
        if report_id is None:
            self.dr_table.setRowCount(0)
            self.dr_title_label.setText("Vui lòng chọn một báo cáo")
            return
        
        self.dr_refresh_button.setDisabled(True)
        self.dr_refresh_button.setText("Đang tải...")

        def on_success(data, headers):
            report_title = data.get('report', {}).get('title', '')
            self.dr_title_label.setText(f"Báo cáo chi tiết cho: {report_title}")
            submitted = data.get('submitted_schools', [])
            not_submitted = data.get('not_submitted_schools', [])

            self.dr_table.setRowCount(0)
            self.dr_table.setRowCount(len(submitted) + len(not_submitted))

            stt = 0
            for school_info in submitted:
                stt_item = QTableWidgetItem(str(stt + 1))
                name_item = QTableWidgetItem(school_info['name'])
                status_item = QTableWidgetItem("Đã hoàn thành")
                status_item.setForeground(QColor("green"))

                submitted_at_dt = QDateTime.fromString(school_info['submitted_at'], "yyyy-MM-dd'T'HH:mm:ss")
                submitted_at_dt.setTimeZone(QTimeZone(b"UTC"))
                submitted_at_local = submitted_at_dt.toLocalTime()
                time_item = QTableWidgetItem(submitted_at_local.toString("HH:mm dd/MM/yyyy"))

                self.dr_table.setItem(stt, 0, stt_item)
                self.dr_table.setItem(stt, 1, name_item)
                self.dr_table.setItem(stt, 2, status_item)
                self.dr_table.setItem(stt, 3, time_item)
                stt += 1

            for school in not_submitted:
                stt_item = QTableWidgetItem(str(stt + 1))
                name_item = QTableWidgetItem(school['name'])
                status_item = QTableWidgetItem("Chưa thực hiện")
                status_item.setForeground(QColor("red"))
                time_item = QTableWidgetItem("")

                self.dr_table.setItem(stt, 0, stt_item)
                self.dr_table.setItem(stt, 1, name_item)
                self.dr_table.setItem(stt, 2, status_item)
                self.dr_table.setItem(stt, 3, time_item)
                stt += 1

            self.dr_table.resizeColumnsToContents()
            self.dr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.dr_refresh_button.setDisabled(False)
            self.dr_refresh_button.setText("Làm mới")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể tải dữ liệu báo cáo.")
            self.dr_refresh_button.setDisabled(False)
            self.dr_refresh_button.setText("Làm mới")
            
        self.api_get(f"/data-reports/{report_id}/status", on_success, on_error)
        
    def send_reminder_handler(self, task_type):
        task_id = None
        button_to_disable = None
        if task_type == "file":
            task_id = self.fr_task_selector.currentData()
            button_to_disable = self.fr_remind_button
        elif task_type == "data":
            task_id = self.dr_report_selector.currentData()
            button_to_disable = self.dr_remind_button

        if task_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một yêu cầu để gửi nhắc nhở.")
            return

        reply = QMessageBox.question(self, 'Xác nhận', "Bạn có chắc chắn muốn gửi nhắc nhở đến tất cả các trường chưa nộp báo cáo này không?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No: return

        button_to_disable.setDisabled(True)
        button_to_disable.setText("Đang gửi...")

        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", data.get("message", "Đã gửi nhắc nhở thành công."))
            button_to_disable.setDisabled(False)
            button_to_disable.setText("Gửi nhắc nhở")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể gửi nhắc nhở.")
            button_to_disable.setDisabled(False)
            button_to_disable.setText("Gửi nhắc nhở")

        self.api_post(f"/admin/remind/{task_type}/{task_id}", {}, on_success, on_error)

    def download_all_files(self):
        task_id = self.fr_task_selector.currentData()
        if task_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một yêu cầu để tải file.")
            return
        
        task_name = self.fr_task_selector.currentText().replace(":", "_").replace(" ", "_")
        save_path, _ = QFileDialog.getSaveFileName(self, "Lưu file ZIP", f"{task_name}.zip", "ZIP Files (*.zip)")
        if not save_path: return

        self.fr_download_button.setDisabled(True)
        self.fr_download_button.setText("Đang tải...")

        def on_success(data_bytes):
            try:
                with open(save_path, 'wb') as f:
                    f.write(data_bytes)
                QMessageBox.information(self, "Thành công", f"Đã tải và lưu file ZIP thành công tại:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể ghi file vào đĩa.\n{e}")
            self.fr_download_button.setDisabled(False)
            self.fr_download_button.setText("Tải tất cả file đã nộp")

        def on_error(status, err):
            if status == 404:
                 QMessageBox.information(self, "Thông báo", "Không có file nào được nộp cho yêu cầu này.")
            else:
                handle_api_error(self, status, err, "Không thể tải file.")
            self.fr_download_button.setDisabled(False)
            self.fr_download_button.setText("Tải tất cả file đã nộp")
        
        self.api_download(f"/file-tasks/{task_id}/download-all", on_success, on_error)
        
    def handle_reset_database(self):
        password, ok = QInputDialog.getText(self, "Yêu cầu Mật khẩu", "Vui lòng nhập mật khẩu quản trị để tiếp tục:", QLineEdit.Password)
        if not ok or not password: return

        confirm_text, ok = QInputDialog.getText(self, "Xác nhận Lần cuối", 'Hành động này sẽ xóa TẤT CẢ năm học, trường, và báo cáo.\nĐể xác nhận, vui lòng gõ chính xác "XOA DU LIEU" vào ô bên dưới:')
        if not ok or confirm_text != "XOA DU LIEU":
            QMessageBox.warning(self, "Đã hủy", "Chuỗi xác nhận không chính xác. Hành động đã được hủy.")
            return

        self.reset_db_button.setDisabled(True)
        self.reset_db_button.setText("Đang xóa...")
        payload = {"password": password}
        
        def on_success(data, headers):
            QMessageBox.information(self, "Thành công", "Đã xóa toàn bộ dữ liệu thành công.")
            self.load_all_initial_data()
            self.reset_db_button.setDisabled(False)
            self.reset_db_button.setText("Xóa Toàn Bộ Dữ Liệu")

        def on_error(status, err):
            handle_api_error(self, status, err, "Không thể xóa dữ liệu.")
            self.reset_db_button.setDisabled(False)
            self.reset_db_button.setText("Xóa Toàn Bộ Dữ Liệu")

        self.api_post("/admin/reset-database", payload, on_success, on_error)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AdminWindow()
    window.show()
    sys.exit(app.exec())