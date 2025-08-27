# admin_app.py
import sys
import os
import webbrowser
import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QMessageBox, QLineEdit, QLabel,
    QTabWidget, QTextEdit, QDateTimeEdit, QComboBox, QFrame, QGridLayout,
    QListWidgetItem, QDateEdit, QStackedWidget, QTableWidget, 
    QTableWidgetItem, QHeaderView, QFileDialog
)
from PySide6.QtCore import QDateTime, Qt, QDate, QUrl
from PySide6.QtGui import QIcon, QColor, QFont, QDesktopServices, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
import clipboard

# XÓA BỎ DÒNG IMPORT NHAPLIEU.PY
# from nhaplieu import SheetDesignerWindow 

API_URL = "http://127.0.0.1:8000"

# --- (Các class SchoolListItemWidget, ListItemWidget, DashboardCard không đổi) ---
class SchoolListItemWidget(QWidget):
    def __init__(self, school_id, name, api_key, parent=None):
        super().__init__(parent)
        self.school_id = school_id
        self.api_key = api_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.name_label = QLabel(f"<b>{name}</b>")
        self.name_label.setFont(QFont("Segoe UI", 12))
        self.key_label = QLineEdit(api_key)
        self.key_label.setReadOnly(True)
        self.key_label.setStyleSheet("background-color: #ecf0f1; border: 1px solid #bdc3c7; padding: 5px; border-radius: 5px;")
        
        self.copy_button = QPushButton("Sao chép API Key")
        self.copy_button.setFont(QFont("Segoe UI", 12))
        self.copy_button.setStyleSheet("QPushButton { background-color: #3498db; color: white; border: none; padding: 8px 12px; border-radius: 5px; } QPushButton:hover { background-color: #2980b9; }")
        self.copy_button.clicked.connect(self.copy_api_key)

        self.delete_button = QPushButton("Xóa")
        self.delete_button.setFont(QFont("Segoe UI", 12))
        self.delete_button.setStyleSheet("QPushButton { background-color: #e74c3c; color: white; border: none; padding: 8px 12px; border-radius: 5px; } QPushButton:hover { background-color: #c0392b; }")
        self.delete_button.clicked.connect(self.delete_school)

        layout.addWidget(self.name_label)
        layout.addStretch()
        layout.addWidget(QLabel("API Key:"))
        layout.addWidget(self.key_label)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.delete_button)
        
    def copy_api_key(self):
        clipboard.copy(self.api_key)
        QMessageBox.information(self, "Thành công", "Đã sao chép API Key vào clipboard!")

    def delete_school(self):
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc chắn muốn xóa trường '{self.name_label.text().strip('<b></b>')}' không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                response = requests.delete(f"{API_URL}/schools/{self.school_id}")
                if response.status_code == 200:
                    QMessageBox.information(self, "Thành công", "Đã xóa trường thành công.")
                    main_window = self.window()
                    if isinstance(main_window, AdminWindow):
                        main_window.load_schools()
                else:
                    QMessageBox.critical(self, "Lỗi", f"Không thể xóa trường.\nLỗi: {response.json().get('detail', response.text)}")
            except requests.exceptions.ConnectionError:
                QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

class ListItemWidget(QWidget):
    def __init__(self, item_id, title, deadline, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        self.title_label = QLabel(f"<b>ID {item_id}: {title}</b>")
        self.title_label.setStyleSheet("color: #34495e; font-size: 14px;")
        self.deadline_label = QLabel(f"Hạn chót: {deadline}")
        self.deadline_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
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
            #CardTitle { font-size: 18px; font-weight: bold; color: #34495e; margin-top: 10px; }
            #CardDescription { font-size: 14px; color: #7f8c8d; margin-top: 5px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(80, 80)
        self.set_icon(icon_svg_data)
        layout.addWidget(self.icon_label)
        layout.addSpacing(10)
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
        self.setWindowTitle("Bảng điều khiển cho Quản trị viên")
        if os.path.exists('baocao.ico'):
            self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet("""
            QMainWindow { background-color: #ecf0f1; }
            QFrame#card { background-color: white; border-radius: 10px; border: 1px solid #e0e0e0; padding: 20px; margin: 10px; }
            QLineEdit, QTextEdit, QDateTimeEdit, QComboBox, QDateEdit { border: 1px solid #bdc3c7; border-radius: 5px; padding: 10px; font-size: 16px; }
            QPushButton { background-color: #3498db; color: white; border: none; padding: 12px 18px; border-radius: 5px; font-weight: bold; font-size: 16px; }
            QPushButton:hover { background-color: #2980b9; }
            QLabel { font-weight: bold; color: #34495e; font-size: 16px; }
            QLabel#main_title { font-size: 35px; font-weight: bold; color: #e74c3c; margin-bottom: 5px; }
            QLabel#subtitle { font-size: 30px; font-weight: bold; color: #e74c3c; margin-top: 0; }
            QListWidget, QTableWidget { border: 1px solid #ecf0f1; border-radius: 5px; background-color: #ffffff; }
            QHeaderView::section { background-color: #34495e; color: white; padding: 8px; font-size: 14px; }
        """)
        
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.dashboard_tab = QWidget()
        self.school_years_tab = QWidget()
        self.schools_tab = QWidget()
        self.file_tasks_tab = QWidget()
        self.data_reports_tab = QWidget()
        self.report_tab = QWidget()
        
        self.create_main_dashboard()
        self.create_school_years_tab()
        self.create_schools_tab()
        self.create_file_tasks_tab()
        self.create_data_reports_tab()
        self.create_report_tab()

        self.stacked_widget.addWidget(self.dashboard_tab)
        self.stacked_widget.addWidget(self.school_years_tab)
        self.stacked_widget.addWidget(self.schools_tab)
        self.stacked_widget.addWidget(self.file_tasks_tab)
        self.stacked_widget.addWidget(self.data_reports_tab)
        self.stacked_widget.addWidget(self.report_tab)

        self.stacked_widget.setCurrentWidget(self.dashboard_tab)
        
        self.load_school_years()
        self.load_schools()
        self.load_file_tasks()
        self.load_data_reports()

    def create_main_dashboard(self):
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setAlignment(Qt.AlignCenter)
        header_frame = QFrame()
        header_layout = QVBoxLayout(header_frame)
        main_title = QLabel("HỆ THỐNG QUẢN LÝ PHÁT HÀNH VĂN BẢN TRƯỜNG HỌC") 
        main_title.setObjectName("main_title")
        subtitle = QLabel("PHÒNG VĂN HÓA - XÃ HỘI PHƯỜNG HỐ NAI")
        subtitle.setObjectName("subtitle")
        header_layout.addWidget(main_title, alignment=Qt.AlignCenter)
        header_layout.addWidget(subtitle, alignment=Qt.AlignCenter)
        layout.addWidget(header_frame)
        layout.addStretch(1)
        dashboard_layout = QGridLayout()
        dashboard_layout.setSpacing(20)
        dashboard_layout.setAlignment(Qt.AlignCenter)
        
        cards_info = [
            ("QUẢN LÝ NĂM HỌC", "Thêm, sửa, xóa các năm học.", lambda: self.stacked_widget.setCurrentWidget(self.school_years_tab), "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='4' rx='2' ry='2'/><line x1='16' x2='16' y1='2' y2='6'/><line x1='8' x2='8' y1='2' y2='6'/><line x1='3' x2='21' y1='10' y2='10'/></svg>"),
            ("QUẢN LÝ NHÀ TRƯỜNG", "Thêm, sửa, xóa thông tin các trường.", lambda: self.stacked_widget.setCurrentWidget(self.schools_tab), "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M14 22v-4a2 2 0 1 0-4 0v4'/><path d='M18 10V6a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4'/><path d='M22 10V6a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4'/><path d='M2 14v4a2 2 0 0 0 2 2h2'/><path d='M2 10v4a2 2 0 0 1-2 2h2'/><path d='M10 14v4a2 2 0 0 0 2 2h2'/><path d='M6 10v4a2 2 0 0 1 2 2h2'/><path d='M10 10v4a2 2 0 0 0 2 2h2'/></svg>"),
            ("BÁO CÁO NỘP FILE", "Ban hành yêu cầu nộp văn bản, file.", lambda: self.stacked_widget.setCurrentWidget(self.file_tasks_tab), "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z'/><path d='M14 2v4a2 2 0 0 0 2 2h4'/><path d='M10 9H8'/><path d='M16 13H8'/><path d='M16 17H8'/></svg>"),
            ("BÁO CÁO NHẬP LIỆU", "Ban hành yêu cầu nhập liệu qua Google Sheet.", lambda: self.stacked_widget.setCurrentWidget(self.data_reports_tab), "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21.17 13.17a2.39 2.39 0 0 0-1.05-1.05 2.5 2.5 0 0 0-3.17.22 2.5 2.5 0 0 0-.22 3.17 2.39 2.39 0 0 0 1.05 1.05 2.5 2.5 0 0 0 3.17-.22 2.5 2.5 0 0 0 .22-3.17Z'/><path d='M8.83 8.83a2.39 2.39 0 0 0-1.05-1.05 2.5 2.5 0 0 0-3.17.22 2.5 2.5 0 0 0-.22 3.17 2.39 2.39 0 0 0 1.05 1.05 2.5 2.5 0 0 0 3.17-.22 2.5 2.5 0 0 0 .22-3.17Z'/><path d='m12 2 4 4-2.5 2.5-4-4L12 2Z'/><path d='M2 12l4 4-2.5 2.5-4-4L2 12Z'/><path d='M12 22l4-4-2.5-2.5-4 4L12 22Z'/></svg>"),
            ("XEM BÁO CÁO", "Xem trạng thái và tải về các báo cáo.", lambda: self.stacked_widget.setCurrentWidget(self.report_tab), "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21.21 15.89A10 10 0 1 1 8 2.83'/><path d='M22 12A10 10 0 0 0 12 2v10Z'/></svg>")
        ]
        
        for i, (title, desc, action, icon) in enumerate(cards_info):
            card = DashboardCard(icon, title, desc)
            card.clicked.connect(action)
            dashboard_layout.addWidget(card, i // 2, i % 2 if i < 4 else 0, 1, 2 if i >= 4 else 1)

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

        # --- KHÔI PHỤC GIAO DIỆN CŨ ---
        design_layout.addWidget(QLabel("URL Google Sheet Mẫu:"), 3, 0)
        self.dr_template_url_input = QLineEdit()
        self.dr_template_url_input.setPlaceholderText("Dán link Google Sheet mẫu vào đây...")
        design_layout.addWidget(self.dr_template_url_input, 3, 1)
        # --- KẾT THÚC KHÔI PHỤC ---

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

    def download_all_files(self):
        task_id = self.fr_task_selector.currentData()
        task_name = self.fr_task_selector.currentText().replace(":", "_").replace(" ", "_")
        if task_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một yêu cầu để tải file.")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Lưu file ZIP", f"{task_name}.zip", "ZIP Files (*.zip)")
        if not save_path: return
        try:
            response = requests.get(f"{API_URL}/file-tasks/{task_id}/download-all", stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                QMessageBox.information(self, "Thành công", f"Đã tải và lưu file ZIP thành công tại:\n{save_path}")
            elif response.status_code == 404:
                 QMessageBox.information(self, "Thông báo", "Không có file nào được nộp cho yêu cầu này.")
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể tải file.\nServer báo lỗi: {response.text}")
        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, "Lỗi kết nối", f"Không thể kết nối đến server để tải file.\nLỗi: {e}")

    def load_file_task_report(self):
        task_id = self.fr_task_selector.currentData()
        if task_id is None:
            self.fr_table.setRowCount(0)
            self.fr_title_label.setText("Vui lòng chọn một yêu cầu")
            return
        try:
            response = requests.get(f"{API_URL}/file-tasks/{task_id}/status")
            if response.status_code == 200:
                data = response.json()
                task_title = data.get('task', {}).get('title', '')
                self.fr_title_label.setText(f"Báo cáo chi tiết cho: {task_title}")
                submitted = data.get('submitted_schools', [])
                not_submitted = data.get('not_submitted_schools', [])
                self.fr_table.setRowCount(0)
                stt = 1
                for school_info in submitted:
                    row_position = self.fr_table.rowCount()
                    self.fr_table.insertRow(row_position)
                    self.fr_table.setItem(row_position, 0, QTableWidgetItem(str(stt)))
                    self.fr_table.setItem(row_position, 1, QTableWidgetItem(school_info['name']))
                    status_item = QTableWidgetItem("Đã nộp")
                    status_item.setForeground(QColor("green"))
                    self.fr_table.setItem(row_position, 2, status_item)
                    
                    submitted_at_utc = QDateTime.fromString(school_info['submitted_at'], "yyyy-MM-dd'T'HH:mm:ss")
                    submitted_at_utc.setTimeSpec(Qt.UTC)
                    submitted_at_local = submitted_at_utc.toLocalTime()
                    self.fr_table.setItem(row_position, 3, QTableWidgetItem(submitted_at_local.toString("HH:mm dd/MM/yyyy")))
                    stt += 1

                for school in not_submitted:
                    row_position = self.fr_table.rowCount()
                    self.fr_table.insertRow(row_position)
                    self.fr_table.setItem(row_position, 0, QTableWidgetItem(str(stt)))
                    self.fr_table.setItem(row_position, 1, QTableWidgetItem(school['name']))
                    status_item = QTableWidgetItem("Chưa nộp")
                    status_item.setForeground(QColor("red"))
                    self.fr_table.setItem(row_position, 2, status_item)
                    stt += 1
                self.fr_table.resizeColumnsToContents()
            else:
                QMessageBox.critical(self, "Lỗi API", f"Không thể tải dữ liệu báo cáo.\nLỗi: {response.text}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

    def load_data_entry_report(self):
        report_id = self.dr_report_selector.currentData()
        if report_id is None:
            self.dr_table.setRowCount(0)
            self.dr_title_label.setText("Vui lòng chọn một báo cáo")
            return
        try:
            response = requests.get(f"{API_URL}/data-reports/{report_id}/status")
            if response.status_code == 200:
                data = response.json()
                report_title = data.get('report', {}).get('title', '')
                self.dr_title_label.setText(f"Báo cáo chi tiết cho: {report_title}")
                
                submitted = data.get('submitted_schools', [])
                not_submitted = data.get('not_submitted_schools', [])
                
                self.dr_table.setRowCount(0)
                stt = 1
                
                for school_info in submitted:
                    row_position = self.dr_table.rowCount()
                    self.dr_table.insertRow(row_position)
                    self.dr_table.setItem(row_position, 0, QTableWidgetItem(str(stt)))
                    self.dr_table.setItem(row_position, 1, QTableWidgetItem(school_info['name']))
                    status_item = QTableWidgetItem("Đã hoàn thành")
                    status_item.setForeground(QColor("green"))
                    self.dr_table.setItem(row_position, 2, status_item)

                    submitted_at_utc = QDateTime.fromString(school_info['submitted_at'], "yyyy-MM-dd'T'HH:mm:ss")
                    submitted_at_utc.setTimeSpec(Qt.UTC)
                    submitted_at_local = submitted_at_utc.toLocalTime()
                    self.dr_table.setItem(row_position, 3, QTableWidgetItem(submitted_at_local.toString("HH:mm dd/MM/yyyy")))
                    stt += 1
                
                for school in not_submitted:
                    row_position = self.dr_table.rowCount()
                    self.dr_table.insertRow(row_position)
                    self.dr_table.setItem(row_position, 0, QTableWidgetItem(str(stt)))
                    self.dr_table.setItem(row_position, 1, QTableWidgetItem(school['name']))
                    status_item = QTableWidgetItem("Chưa thực hiện")
                    status_item.setForeground(QColor("red"))
                    self.dr_table.setItem(row_position, 2, status_item)
                    stt += 1
                
                self.dr_table.resizeColumnsToContents()
            else:
                QMessageBox.critical(self, "Lỗi API", f"Không thể tải dữ liệu báo cáo.\nLỗi: {response.text}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

    def load_schools(self):
        try:
            response = requests.get(f"{API_URL}/schools/")
            if response.status_code == 200:
                self.schools_list_widget.clear()
                for school in response.json():
                    list_item = QListWidgetItem()
                    custom_widget = SchoolListItemWidget(school['id'], school['name'], school['api_key'], parent=self.schools_list_widget)
                    list_item.setSizeHint(custom_widget.sizeHint())
                    self.schools_list_widget.addItem(list_item)
                    self.schools_list_widget.setItemWidget(list_item, custom_widget)
        except requests.exceptions.ConnectionError:
            print("Lỗi kết nối khi tải danh sách trường.") 

    def add_new_school(self):
        school_name = self.school_name_input.text().strip()
        if not school_name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên trường.")
            return
        try:
            response = requests.post(f"{API_URL}/schools/", json={"name": school_name})
            if response.status_code == 200:
                QMessageBox.information(self, "Thành công", f"Đã thêm trường '{school_name}' thành công.")
                self.school_name_input.clear()
                self.load_schools()
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể thêm trường.\nLỗi: {response.json().get('detail', response.text)}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

    def add_new_school_year(self):
        name = self.sy_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên năm học.")
            return
        payload = {"name": name, "start_date": self.sy_start_date_input.date().toString("yyyy-MM-dd"), "end_date": self.sy_end_date_input.date().toString("yyyy-MM-dd")}
        try:
            response = requests.post(f"{API_URL}/school_years/", json=payload)
            if response.status_code == 200:
                QMessageBox.information(self, "Thành công", f"Đã thêm năm học '{name}' thành công.")
                self.sy_name_input.clear()
                self.load_school_years()
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể thêm năm học.\nLỗi: {response.json().get('detail', response.text)}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

    def load_school_years(self):
        try:
            response = requests.get(f"{API_URL}/school_years/")
            if response.status_code == 200:
                selectors = [self.ft_school_year_selector, self.ft_filter_sy_selector, self.dr_school_year_selector]
                for selector in selectors:
                    selector.clear()
                self.school_years_list_widget_tab.clear()
                self.ft_filter_sy_selector.addItem("Tất cả", userData=None)
                
                for sy in response.json():
                    item_text = f"ID {sy['id']}: {sy['name']} ({sy['start_date']} - {sy['end_date']})"
                    list_item = QListWidgetItem(item_text)
                    list_item.setData(Qt.UserRole, sy['id'])
                    self.school_years_list_widget_tab.addItem(list_item)
                    for selector in [self.ft_school_year_selector, self.dr_school_year_selector, self.ft_filter_sy_selector]:
                        selector.addItem(sy['name'], userData=sy['id'])
        except requests.exceptions.ConnectionError:
            print("Lỗi kết nối khi tải danh sách năm học.")

    def load_file_tasks(self):
        school_year_id = self.ft_filter_sy_selector.currentData()
        params = {}
        if school_year_id:
            params['school_year_id'] = school_year_id
        try:
            response = requests.get(f"{API_URL}/file-tasks/", params=params)
            if response.status_code == 200:
                self.file_tasks_list_widget.clear()
                self.fr_task_selector.clear()
                for task in response.json():
                    deadline_local = QDateTime.fromString(task['deadline'], "yyyy-MM-dd'T'HH:mm:ss")
                    deadline_str = deadline_local.toString("HH:mm dd/MM/yyyy")
                    
                    list_item = QListWidgetItem()
                    custom_widget = ListItemWidget(task['id'], task['title'], deadline_str)
                    list_item.setSizeHint(custom_widget.sizeHint())
                    self.file_tasks_list_widget.addItem(list_item)
                    self.file_tasks_list_widget.setItemWidget(list_item, custom_widget)
                    self.fr_task_selector.addItem(f"ID {task['id']}: {task['title']}", userData=task['id'])
        except requests.exceptions.ConnectionError:
            print("Lỗi kết nối khi tải danh sách công việc nộp file.")

    def add_new_file_task(self):
        school_year_id = self.ft_school_year_selector.currentData()
        title = self.ft_title_input.text().strip()
        content = self.ft_content_input.toPlainText().strip()
        if not title or not content or not school_year_id:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ thông tin.")
            return

        deadline_local = self.ft_deadline_input.dateTime()
        payload = {"title": title, "content": content, "deadline": deadline_local.toString("yyyy-MM-dd'T'HH:mm:ss"), "school_year_id": school_year_id}
        
        try:
            response = requests.post(f"{API_URL}/file-tasks/", json=payload)
            if response.status_code == 200:
                QMessageBox.information(self, "Thành công", "Đã ban hành yêu cầu mới.")
                self.ft_title_input.clear()
                self.ft_content_input.clear()
                self.load_file_tasks()
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể tạo yêu cầu.\nLỗi: {response.json().get('detail', response.text)}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

    def load_data_reports(self):
        try:
            response = requests.get(f"{API_URL}/data-reports/")
            if response.status_code == 200:
                self.data_reports_list_widget.clear()
                self.dr_report_selector.clear()
                for report in response.json():
                    deadline_local = QDateTime.fromString(report['deadline'], "yyyy-MM-dd'T'HH:mm:ss")
                    deadline_str = deadline_local.toString("HH:mm dd/MM/yyyy")

                    list_item = QListWidgetItem()
                    custom_widget = ListItemWidget(report['id'], report['title'], deadline_str)
                    list_item.setSizeHint(custom_widget.sizeHint())
                    self.data_reports_list_widget.addItem(list_item)
                    self.data_reports_list_widget.setItemWidget(list_item, custom_widget)
                    self.dr_report_selector.addItem(f"ID {report['id']}: {report['title']}", userData=report['id'])
        except requests.exceptions.ConnectionError:
            print("Lỗi kết nối khi tải danh sách báo cáo nhập liệu.")

    def add_new_data_report(self):
        school_year_id = self.dr_school_year_selector.currentData()
        title = self.dr_title_input.text().strip()
        template_url = self.dr_template_url_input.text().strip()
        
        if not all([title, school_year_id, template_url]):
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ Tiêu đề, URL và chọn Năm học.")
            return

        deadline_local = self.dr_deadline_input.dateTime()
        payload = {
            "title": title, 
            "deadline": deadline_local.toString("yyyy-MM-dd'T'HH:mm:ss"), 
            "school_year_id": school_year_id, 
            "template_url": template_url
        }
        try:
            response = requests.post(f"{API_URL}/data-reports/", json=payload)
            if response.status_code == 200:
                QMessageBox.information(self, "Thành công", "Đã ban hành báo cáo nhập liệu mới.")
                self.dr_title_input.clear()
                self.dr_template_url_input.clear()
                self.load_data_reports()
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể tạo báo cáo.\nLỗi: {response.json().get('detail', response.text)}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Lỗi kết nối", "Không thể kết nối đến server backend.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AdminWindow()
    window.show()
    sys.exit(app.exec())
