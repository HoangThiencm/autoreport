import sys
import os
import webbrowser
import json
import re
from typing import Callable, List, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QMessageBox, QLineEdit, QLabel,
    QTabWidget, QTextEdit, QDateTimeEdit, QComboBox, QFrame, QGridLayout,
    QListWidgetItem, QDateEdit, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QInputDialog, QDialog,
    QDialogButtonBox, QCheckBox, QAbstractItemView, QToolBar, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtCore import QDateTime, Qt, QDate, QTime, QUrl, QTimeZone, QByteArray, QUrlQuery, QFile, QIODevice
from PySide6.QtGui import QIcon, QColor, QFont, QPixmap, QPainter, QAction
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply, QHttpMultiPart, QHttpPart 

import clipboard
from spreadsheet_widget import SpreadsheetWidget, ColumnSpec

API_URL = "https://auto-report-backend.onrender.com"

def handle_api_error(self, status_code, response_text, context_message):
    detail = response_text
    try:
        error_data = json.loads(response_text)
        detail = error_data.get('detail', response_text)
    except json.JSONDecodeError:
        pass
    QMessageBox.critical(self, "Lỗi", f"{context_message}\nLỗi từ server (Code: {status_code}): {detail}")

class Paginator:
    def __init__(self, page_size=20):
        self.page = 1
        self.page_size = page_size
        self.has_next = False

    def next(self):
        if self.has_next:
            self.page += 1

    def prev(self):
        if self.page > 1:
            self.page -= 1

    @property
    def skip(self):
        return (self.page - 1) * self.page_size

    @property
    def limit(self):
        return self.page_size

    def mark_result(self, count):
        self.has_next = (count >= self.page_size)

class DataReportListItemWidget(QWidget):
    def __init__(self, report_id, title, deadline, schema, template_data, is_locked, attachment_url, parent=None):
        super().__init__(parent)
        self.report_id = report_id
        self.title = title
        self.deadline_str = deadline
        self.columns_schema = schema
        self.template_data = template_data
        self.is_locked = is_locked
        self.attachment_url = attachment_url
        
        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        
        title_text = f"<b>ID {report_id}: {title}</b>"
        if self.attachment_url:
            title_text += " 📎"
        self.title_label = QLabel(title_text)
        
        self.deadline_label = QLabel(f"Hạn chót: {deadline}")
        self.deadline_label.setStyleSheet("color: #666; font-weight: normal;")
        
        top_layout.addWidget(self.title_label, 1)
        top_layout.addWidget(self.deadline_label)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.lock_checkbox = QCheckBox("Khóa")
        self.lock_checkbox.setChecked(self.is_locked)
        self.lock_checkbox.toggled.connect(self.toggle_lock_status)
        button_layout.addWidget(self.lock_checkbox)
        
        self.edit_button = QPushButton("Sửa")
        self.delete_button = QPushButton("Xóa")
        self.edit_button.setStyleSheet("background-color: #f39c12; padding: 5px 10px; font-size: 14px;")
        self.delete_button.setStyleSheet("background-color: #e74c3c; padding: 5px 10px; font-size: 14px;")
        
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        
        layout.addLayout(top_layout)
        layout.addLayout(button_layout)
        
        self.delete_button.clicked.connect(self.delete_report)
        self.edit_button.clicked.connect(self.edit_report)

    def delete_report(self):
        main_window = self.window()
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc muốn xóa báo cáo '{self.title}' không? \nHành động này không thể hoàn tác.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            main_window.api_delete(f"/data-reports/{self.report_id}", 
                                   on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã xóa báo cáo."), main_window.load_data_reports()),
                                   on_error=lambda s, e: handle_api_error(self, s, e, "Không thể xóa báo cáo."))

    def edit_report(self):
        main_window = self.window()
        dialog = QDialog(self)
        dialog.setWindowTitle("Chỉnh sửa Báo cáo & Biểu mẫu")
        dialog.setMinimumWidth(600)
        layout = QGridLayout(dialog)
        
        layout.addWidget(QLabel("Tiêu đề:"), 0, 0)
        title_edit = QLineEdit(self.title)
        layout.addWidget(title_edit, 0, 1)
        
        layout.addWidget(QLabel("Hạn chót:"), 1, 0)
        deadline_edit = QDateTimeEdit(QDateTime.fromString(self.deadline_str, "HH:mm dd/MM/yyyy"))
        deadline_edit.setCalendarPopup(True)
        deadline_edit.setDisplayFormat("HH:mm dd/MM/yyyy")
        layout.addWidget(deadline_edit, 1, 1)

        design_button = QPushButton("Sửa thiết kế biểu mẫu...")
        layout.addWidget(design_button, 2, 1)

        layout.addWidget(QLabel("File đính kèm:"), 3, 0)
        attachment_layout = QHBoxLayout()
        temp_attachment_url = self.attachment_url
        attachment_label = QLabel(os.path.basename(temp_attachment_url) if temp_attachment_url else "Chưa có file.")
        attachment_layout.addWidget(attachment_label, 1)

        def select_new_attachment():
            nonlocal temp_attachment_url
            file_path, _ = QFileDialog.getOpenFileName(dialog, "Chọn file đính kèm mới")
            if not file_path:
                return
            attachment_label.setText("Đang tải lên...")
            
            def on_success(data, headers):
                temp_attachment_url = data.get("file_url")
                attachment_label.setText(f"Mới: {os.path.basename(file_path)}")
                QMessageBox.information(dialog, "Thành công", "Đã tải file mới. Thay đổi sẽ được lưu khi nhấn 'OK'.")
            
            def on_error(s, e):
                attachment_label.setText("Lỗi tải lên.")
                handle_api_error(dialog, s, e, "Không thể tải file.")
            
            main_window.api_upload_file("/admin/upload-attachment", file_path, on_success, on_error)

        attachment_btn = QPushButton("Chọn file khác...")
        attachment_btn.clicked.connect(select_new_attachment)
        attachment_layout.addWidget(attachment_btn)
        layout.addLayout(attachment_layout, 3, 1)

        temp_schema = self.columns_schema
        temp_data = self.template_data

        def open_editor():
            nonlocal temp_schema, temp_data
            designer = GridDesignDialog(temp_schema, temp_data, dialog)
            if designer.exec():
                temp_schema = designer.get_schema()
                temp_data = designer.get_data()
                QMessageBox.information(dialog, "Đã lưu tạm", f"Đã cập nhật thiết kế ({len(temp_schema)} cột). Thay đổi sẽ được áp dụng khi bạn nhấn 'OK'.")
        
        design_button.clicked.connect(open_editor)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box, 4, 0, 1, 2)
        
        if dialog.exec():
            payload = {
                "title": title_edit.text().strip(),
                "deadline": deadline_edit.dateTime().toString("yyyy-MM-dd'T'HH:mm:ss"),
                "columns_schema": temp_schema,
                "template_data": temp_data,
                "attachment_url": temp_attachment_url 
            }
            main_window.api_put(f"/data-reports/{self.report_id}", payload,
                                on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã cập nhật báo cáo."), main_window.load_data_reports()),
                                on_error=lambda s, e: handle_api_error(self, s, e, "Không thể cập nhật báo cáo."))

    def toggle_lock_status(self, checked):
        main_window = self.window()
        payload = {"is_locked": checked}
        self.lock_checkbox.setDisabled(True)

        def on_success(d, h):
            self.is_locked = checked
            self.lock_checkbox.setDisabled(False)
        
        def on_error(s, e):
            handle_api_error(self, s, e, "Lỗi cập nhật trạng thái.")
            self.lock_checkbox.toggled.disconnect()
            self.lock_checkbox.setChecked(not checked)
            self.lock_checkbox.toggled.connect(self.toggle_lock_status)
            self.lock_checkbox.setDisabled(False)

        main_window.api_put(f"/data-reports/{self.report_id}", payload, on_success, on_error)

class FileTaskListItemWidget(QWidget):
    def __init__(self, task_id, title, content, deadline, school_year_id, is_locked, attachment_url, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.title = title
        self.content = content
        self.deadline_str = deadline
        self.school_year_id = school_year_id
        self.is_locked = is_locked
        self.attachment_url = attachment_url 

        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.title_label = QLabel(f"<b>ID {task_id}: {title}</b>")
        self.deadline_label = QLabel(f"Hạn chót: {deadline}")
        self.deadline_label.setStyleSheet("color: #666; font-weight: normal;")
        top_layout.addWidget(self.title_label, 1)
        top_layout.addWidget(self.deadline_label)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.lock_checkbox = QCheckBox("Khóa")
        self.lock_checkbox.setChecked(self.is_locked)
        self.lock_checkbox.toggled.connect(self.toggle_lock_status)
        button_layout.addWidget(self.lock_checkbox)
        
        self.edit_button = QPushButton("Sửa")
        self.delete_button = QPushButton("Xóa")
        self.edit_button.setStyleSheet("background-color: #f39c12; padding: 5px 10px; font-size: 14px;")
        self.delete_button.setStyleSheet("background-color: #e74c3c; padding: 5px 10px; font-size: 14px;")
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        
        layout.addLayout(top_layout)
        layout.addLayout(button_layout)
        self.delete_button.clicked.connect(self.delete_task)
        self.edit_button.clicked.connect(self.edit_task)

    def delete_task(self):
        main_window = self.window()
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc muốn xóa yêu cầu '{self.title}' không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            main_window.api_delete(f"/file-tasks/{self.task_id}", 
                                   on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã xóa yêu cầu."), main_window.load_file_tasks()), 
                                   on_error=lambda s, e: handle_api_error(self, s, e, "Không thể xóa yêu cầu."))
    
    def edit_task(self):
        main_window = self.window()
        dialog = QDialog(self)
        dialog.setWindowTitle("Chỉnh sửa Yêu cầu")
        dialog.setMinimumWidth(500)
        layout = QGridLayout(dialog)
        layout.addWidget(QLabel("Tiêu đề:"), 0, 0)
        title_edit = QLineEdit(self.title)
        layout.addWidget(title_edit, 0, 1)
        layout.addWidget(QLabel("Nội dung:"), 1, 0)
        content_edit = QTextEdit(self.content)
        layout.addWidget(content_edit, 1, 1)
        layout.addWidget(QLabel("Hạn chót:"), 2, 0)
        deadline_edit = QDateTimeEdit(QDateTime.fromString(self.deadline_str, "HH:mm dd/MM/yyyy"))
        deadline_edit.setCalendarPopup(True)
        deadline_edit.setDisplayFormat("HH:mm dd/MM/yyyy")
        layout.addWidget(deadline_edit, 2, 1)

        layout.addWidget(QLabel("File đính kèm:"), 3, 0)
        attachment_layout = QHBoxLayout()
        temp_attachment_url = self.attachment_url
        attachment_label = QLabel(os.path.basename(temp_attachment_url) if temp_attachment_url else "Chưa có file.")
        attachment_layout.addWidget(attachment_label, 1)
        
        def select_new_attachment():
            nonlocal temp_attachment_url
            file_path, _ = QFileDialog.getOpenFileName(dialog, "Chọn file đính kèm mới")
            if not file_path:
                return
            attachment_label.setText("Đang tải lên...")
            
            def on_success(data, headers):
                temp_attachment_url = data.get("file_url")
                attachment_label.setText(f"Mới: {os.path.basename(file_path)}")
                QMessageBox.information(dialog, "Thành công", "Đã tải file mới. Thay đổi sẽ được lưu khi nhấn 'OK'.")
            def on_error(s, e):
                attachment_label.setText("Lỗi tải lên.")
                handle_api_error(dialog, s, e, "Không thể tải file.")
            main_window.api_upload_file("/admin/upload-attachment", file_path, on_success, on_error)

        attachment_btn = QPushButton("Chọn file khác...")
        attachment_btn.clicked.connect(select_new_attachment)
        attachment_layout.addWidget(attachment_btn)
        layout.addLayout(attachment_layout, 3, 1)

        layout.addWidget(QLabel("Năm học:"), 4, 0)
        sy_selector = QComboBox()
        for i in range(main_window.ft_school_year_selector.count()):
            sy_selector.addItem(main_window.ft_school_year_selector.itemText(i), main_window.ft_school_year_selector.itemData(i))
            if main_window.ft_school_year_selector.itemData(i) == self.school_year_id:
                sy_selector.setCurrentIndex(i)
        layout.addWidget(sy_selector, 4, 1)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box, 5, 0, 1, 2)

        if dialog.exec():
            if not all([title_edit.text().strip(), content_edit.toPlainText().strip(), sy_selector.currentData()]):
                QMessageBox.warning(self, "Lỗi", "Vui lòng điền đủ thông tin.")
                return
            payload = {
                "title": title_edit.text().strip(), 
                "content": content_edit.toPlainText().strip(), 
                "deadline": deadline_edit.dateTime().toString("yyyy-MM-dd'T'HH:mm:ss"), 
                "school_year_id": sy_selector.currentData(),
                "attachment_url": temp_attachment_url
            }
            main_window.api_put(f"/file-tasks/{self.task_id}", payload, 
                                on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã cập nhật yêu cầu."), main_window.load_file_tasks()), 
                                on_error=lambda s, e: handle_api_error(self, s, e, "Không thể cập nhật yêu cầu."))

    def toggle_lock_status(self, checked):
        main_window = self.window()
        payload = {"is_locked": checked}
        self.lock_checkbox.setDisabled(True)

        def on_success(d, h):
            self.is_locked = checked
            self.lock_checkbox.setDisabled(False)

        def on_error(s, e):
            handle_api_error(self, s, e, "Lỗi cập nhật trạng thái.")
            self.lock_checkbox.toggled.disconnect()
            self.lock_checkbox.setChecked(not checked)
            self.lock_checkbox.toggled.connect(self.toggle_lock_status)
            self.lock_checkbox.setDisabled(False)

        main_window.api_put(f"/file-tasks/{self.task_id}", payload, on_success, on_error)

class GridDesignDialog(QDialog):
    def __init__(self, schema=None, data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thiết kế biểu mẫu (1000 hàng x 30 cột)")
        self.resize(1100, 620)

        if schema:
            cols = [ColumnSpec(**c) for c in schema]
        else:
            cols = [ColumnSpec(name=f"col_{i+1:02d}", title=f"Cột {i+1}") for i in range(30)]

        v = QVBoxLayout(self)
        self.sheet = SpreadsheetWidget(columns=cols, rows=1000, parent=self)
        
        if data:
            self.sheet.set_data(data)
            
        v.addWidget(self.sheet)

        tb = QToolBar()
        act_from_row1 = QAction("Sinh cột từ hàng 1", self)
        act_clear_row1 = QAction("Xóa hàng 1", self)
        tb.addAction(act_from_row1)
        tb.addAction(act_clear_row1)
        v.addWidget(tb)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Lưu & Đóng")
        v.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        def _slug(s: str, fallback: str):
            s = s.strip().lower()
            s = re.sub(r"\W+", "_", s)
            return s or fallback

        def use_row1_as_header():
            for c, col in enumerate(self.sheet.columns):
                it = self.sheet.model.item(0, c)
                title = (it.text().strip() if it else "") or col.title
                col.title = title
                col.name = _slug(title, f"col_{c+1:02d}")
                self.sheet.model.setHeaderData(c, Qt.Horizontal, col.title)
            self.sheet.model.removeRow(0)
            QMessageBox.information(self, "Hoàn tất", "Đã cập nhật tên cột và xóa hàng 1.")

        def clear_first_row():
            for c in range(self.sheet.model.columnCount()):
                it = self.sheet.model.item(0, c)
                if it:
                    it.setText("")

        act_from_row1.triggered.connect(use_row1_as_header)
        act_clear_row1.triggered.connect(clear_first_row)
        
    def get_schema(self):
        for i, col in enumerate(self.sheet.columns):
            col.width = self.sheet.view.columnWidth(i)
        return [col.__dict__ for col in self.sheet.columns]    
    
    def get_data(self):
        return self.sheet.to_records()

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
        QMessageBox.information(self, "Thành công", "Đã sao chép API Key!")
    
    def delete_school(self):
        main_window = self.window()
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc muốn xóa trường '{self.name_label.text().strip('<b></b>')}' không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            main_window.api_delete(f"/schools/{self.school_id}", 
                                   on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã xóa trường."), main_window.load_schools()), 
                                   on_error=lambda s, e: handle_api_error(self, s, e, "Không thể xóa trường."))

class SchoolYearListItemWidget(QWidget):
    def __init__(self, sy_id, name, start_date, end_date, parent=None):
        super().__init__(parent)
        self.sy_id = sy_id
        self.name = name
        self.start_date = start_date
        self.end_date = end_date
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        self.info_label = QLabel(f"<b>{name}</b> ({start_date} - {end_date})")
        self.edit_button = QPushButton("Sửa")
        self.delete_button = QPushButton("Xóa")
        self.edit_button.setStyleSheet("background-color: #f39c12; padding: 5px 10px; font-size: 14px;")
        self.delete_button.setStyleSheet("background-color: #e74c3c; padding: 5px 10px; font-size: 14px;")
        layout.addWidget(self.info_label, 1)
        layout.addWidget(self.edit_button)
        layout.addWidget(self.delete_button)
        self.delete_button.clicked.connect(self.delete_year)
        self.edit_button.clicked.connect(self.edit_year)
    
    def delete_year(self):
        main_window = self.window()
        reply = QMessageBox.question(self, 'Xác nhận xóa', f"Bạn có chắc muốn xóa năm học '{self.name}' không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            main_window.api_delete(f"/school_years/{self.sy_id}", 
                                   on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã xóa năm học."), main_window.load_school_years()), 
                                   on_error=lambda s, e: handle_api_error(self, s, e, "Không thể xóa năm học."))
    
    def edit_year(self):
        main_window = self.window()
        dialog = QDialog(self)
        dialog.setWindowTitle("Chỉnh sửa Năm học")
        layout = QGridLayout(dialog)
        layout.addWidget(QLabel("Tên Năm học:"), 0, 0)
        name_edit = QLineEdit(self.name)
        layout.addWidget(name_edit, 0, 1)
        layout.addWidget(QLabel("Ngày bắt đầu:"), 1, 0)
        start_date_edit = QDateEdit(QDate.fromString(self.start_date, "yyyy-MM-dd"))
        start_date_edit.setCalendarPopup(True)
        start_date_edit.setDisplayFormat("dd/MM/yyyy")
        layout.addWidget(start_date_edit, 1, 1)
        layout.addWidget(QLabel("Ngày kết thúc:"), 2, 0)
        end_date_edit = QDateEdit(QDate.fromString(self.end_date, "yyyy-MM-dd"))
        end_date_edit.setCalendarPopup(True)
        start_date_edit.setDisplayFormat("dd/MM/yyyy")
        layout.addWidget(end_date_edit, 2, 1)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box, 3, 0, 1, 2)
        if dialog.exec():
            if not name_edit.text().strip():
                QMessageBox.warning(self, "Lỗi", "Tên năm học không được để trống.")
                return
            payload = {"name": name_edit.text().strip(), "start_date": start_date_edit.date().toString("yyyy-MM-dd"), "end_date": end_date_edit.date().toString("yyyy-MM-dd")}
            main_window.api_put(f"/school_years/{self.sy_id}", payload, 
                                on_success=lambda d, h: (QMessageBox.information(self, "Thành công", "Đã cập nhật năm học."), main_window.load_school_years()), 
                                on_error=lambda s, e: handle_api_error(self, s, e, "Không thể cập nhật năm học."))

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

class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.network_manager = QNetworkAccessManager(self)
        self.setWindowTitle("Bảng điều khiển cho Quản trị viên")
        if os.path.exists('baocao.ico'):
            self.setWindowIcon(QIcon('baocao.ico'))
        self.setGeometry(100, 100, 1400, 850)
        self.setFont(QFont("Segoe UI", 10))
        
        self.setStyleSheet("""
            QMainWindow { background-color: #f4f6f9; }
            QFrame#card { background-color: white; border-radius: 8px; border: 1px solid #dfe4ea; padding: 20px; margin: 10px; }
            QLineEdit, QTextEdit, QDateTimeEdit, QComboBox, QDateEdit { 
                border: 1px solid #ced4da; border-radius: 5px; padding: 10px; 
                font-size: 11pt; background-color: #ffffff;
            }
            QPushButton { 
                background-color: #3498db; color: white; border: none; 
                padding: 12px 18px; border-radius: 5px; 
                font-weight: bold; font-size: 11pt; 
            }
            QPushButton:hover { background-color: #2980b9; } 
            QPushButton:disabled { background-color: #bdc3c7; }
            QLabel { color: #34495e; font-size: 11pt; } 
            QLabel#main_title { font-size: 28px; font-weight: bold; color: #e74c3c; }
            QLabel#subtitle { font-size: 20px; font-weight: bold; color: #e74c3c; margin-bottom: 20px; }
            QListWidget, QTableWidget, QTreeWidget, QTableView { 
                border: 1px solid #dfe4ea; border-radius: 5px; 
                background-color: #ffffff; font-size: 11pt;
            }
            QHeaderView::section { 
                background-color: #e9ecef; color: #495057; 
                padding: 10px; font-size: 10pt; font-weight: bold; border: none;
            }
            QTabBar::tab { font-size: 11pt; padding: 12px 20px; font-weight: bold;} 
            QTabWidget::pane { border: none; }
        """)
        
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.current_report_schema = []
        self.current_report_data = []
        
        self.school_groups = {}
        self._all_schools_cache = []
        self._custom_selected_school_ids = set()
        self._ft_custom_selected_school_ids = set() 
        self._school_year_cache = []

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
            response_data = bytes(reply.readAll()).decode('utf-8')
            if 200 <= status_code < 300:
                try:
                    on_success(json.loads(response_data) if response_data else {}, {})
                except json.JSONDecodeError:
                    on_error(status_code, "Lỗi giải mã JSON.")
            else:
                on_error(status_code, response_data)
        else:
            on_error(0, f"Lỗi mạng: {reply.errorString()}")
        reply.deleteLater()

    def api_get(self, endpoint: str, on_success: Callable, on_error: Callable, params: dict = None):
        url = QUrl(f"{API_URL}{endpoint}")
        if params:
            query = QUrlQuery()
            for k, v in params.items():
                if v is not None:
                    query.addQueryItem(k, str(v))
            url.setQuery(query)
        req = QNetworkRequest(url)
        reply = self.network_manager.get(req)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_post(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable):
        req = QNetworkRequest(QUrl(f"{API_URL}{endpoint}"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        reply = self.network_manager.post(req, payload)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_put(self, endpoint: str, data: dict, on_success: Callable, on_error: Callable):
        req = QNetworkRequest(QUrl(f"{API_URL}{endpoint}"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        reply = self.network_manager.put(req, payload)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_delete(self, endpoint: str, on_success: Callable, on_error: Callable):
        req = QNetworkRequest(QUrl(f"{API_URL}{endpoint}"))
        reply = self.network_manager.deleteResource(req)
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def api_download(self, endpoint: str, on_success: Callable, on_error: Callable):
        req = QNetworkRequest(QUrl(f"{API_URL}{endpoint}"))
        reply = self.network_manager.get(req)
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

    def api_upload_file(self, endpoint: str, file_path: str, on_success: Callable, on_error: Callable):
        url = QUrl(f"{API_URL}{endpoint}")
        req = QNetworkRequest(url)

        multi_part = QHttpMultiPart(QHttpMultiPart.FormDataType)
        
        file_part = QHttpPart()
        file_name = os.path.basename(file_path)
        try:
            file_name_ascii = file_name.encode('ascii').decode('utf-8')
        except UnicodeEncodeError:
            from unidecode import unidecode
            file_name_ascii = unidecode(file_name)

        file_part.setHeader(QNetworkRequest.ContentDispositionHeader, f'form-data; name="file"; filename="{file_name_ascii}"')
        
        file_device = QFile(file_path)
        if not file_device.open(QIODevice.ReadOnly):
            on_error(0, "Không thể mở file để đọc.")
            return
            
        file_part.setBodyDevice(file_device)
        file_device.setParent(multi_part)
        
        multi_part.append(file_part)
        
        reply = self.network_manager.post(req, multi_part)
        multi_part.setParent(reply)
        
        reply.finished.connect(lambda: self._handle_reply(reply, on_success, on_error))

    def load_all_initial_data(self):
        self.load_dashboard_stats()
        self.load_school_years()
        self.load_schools()
        self.load_file_tasks()
        self.load_data_reports()
        self.load_report_file_tasks_list()
        self.load_report_data_reports_list()

    def load_report_file_tasks_list(self):
        def on_success(data, _):
            self.fr_task_selector.clear()
            self.fr_task_selector.addItem("--- Vui lòng chọn một yêu cầu ---", userData=None)
            sorted_tasks = sorted(data, key=lambda x: x.get('deadline', ''), reverse=True)
            for task in sorted_tasks:
                self.fr_task_selector.addItem(f"ID {task['id']}: {task['title']}", userData=task['id'])

        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể tải danh sách yêu cầu nộp file.")
            self.fr_task_selector.clear()
            self.fr_task_selector.addItem("Lỗi khi tải danh sách", userData=None)

        self.api_get("/file-tasks/", on_success, on_error, params={"limit": 1000})


    def load_report_data_reports_list(self):
        def on_success(data, _):
            self.dr_report_selector.clear()
            self.dr_report_selector.addItem("--- Vui lòng chọn một báo cáo ---", userData=None)
            sorted_reports = sorted(data, key=lambda x: x.get('deadline', ''), reverse=True)
            for report in sorted_reports:
                self.dr_report_selector.addItem(f"ID {report['id']}: {report['title']}", userData=report['id'])

        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể tải danh sách báo cáo nhập liệu.")
            self.dr_report_selector.clear()
            self.dr_report_selector.addItem("Lỗi khi tải danh sách", userData=None)
            
        self.api_get("/data-reports/", on_success, on_error, params={"limit": 1000})

    def create_main_dashboard(self):
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(40, 20, 40, 20)

        header_frame = QFrame()
        header_layout = QVBoxLayout(header_frame)
        main_title = QLabel("HỆ THỐNG QUẢN LÝ BÁO CÁO GIÁO DỤC")
        main_title.setObjectName("main_title")
        subtitle = QLabel("PHÒNG VĂN HOÁ - XÃ HỘI PHƯỜNG HỐ NAI - TỈNH ĐỒNG NAI")
        subtitle.setObjectName("subtitle")
        header_layout.addWidget(main_title, alignment=Qt.AlignCenter)
        header_layout.addWidget(subtitle, alignment=Qt.AlignCenter)
        layout.addWidget(header_frame)
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        self.stats_overdue_ft = self._create_stat_card("Yêu cầu Nộp file quá hạn", "0")
        self.stats_overdue_dr = self._create_stat_card("Yêu cầu Nhập liệu quá hạn", "0")
        self.stats_total_schools = self._create_stat_card("Tổng số trường", "0")
        self.stats_active_year = self._create_stat_card("Năm học hiện tại", "N/A")

        stats_layout.addWidget(self.stats_overdue_ft)
        stats_layout.addWidget(self.stats_overdue_dr)
        stats_layout.addWidget(self.stats_total_schools)
        stats_layout.addWidget(self.stats_active_year)
        layout.addLayout(stats_layout)

        dashboard_layout = QGridLayout()
        dashboard_layout.setSpacing(25)
        cards_info = [
            ("QUẢN LÝ NĂM HỌC", "Tạo và quản lý các năm học.", lambda: self.stacked_widget.setCurrentWidget(self.school_years_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3498db" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-calendar"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>'),
            ("QUẢN LÝ NHÀ TRƯỜNG", "Thêm trường và cấp mã API.", lambda: self.stacked_widget.setCurrentWidget(self.schools_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#2ecc71" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-home"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'),
            ("BÁO CÁO NỘP FILE", "Ban hành yêu cầu nộp văn bản.", lambda: self.stacked_widget.setCurrentWidget(self.file_tasks_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#9b59b6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-file-plus"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="12" y1="18" x2="12" y2="12"></line><line x1="9" y1="15" x2="15" y2="15"></line></svg>'),
            ("BÁO CÁO NHẬP LIỆU", "Thiết kế biểu mẫu nhập liệu.", lambda: self.stacked_widget.setCurrentWidget(self.data_reports_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e67e22" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-edit-3"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>'),
            ("XEM BÁO CÁO", "Theo dõi và tải về các báo cáo.", lambda: self.stacked_widget.setCurrentWidget(self.report_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1abc9c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-pie-chart"><path d="M21.21 15.89A10 10 0 1 1 8.11 2.99"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>'),
            ("CÀI ĐẶT", "Các chức năng quản trị hệ thống.", lambda: self.stacked_widget.setCurrentWidget(self.settings_tab), '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e74c3c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-settings"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>')
        ]
        for i, (title, desc, action, icon) in enumerate(cards_info):
            card = DashboardCard(icon, title, desc)
            card.clicked.connect(action)
            dashboard_layout.addWidget(card, i // 3, i % 3)
        layout.addLayout(dashboard_layout)
        layout.addStretch(1)

        refresh_button = QPushButton("Làm mới trang")
        refresh_button.clicked.connect(self.load_all_initial_data)
        layout.addWidget(refresh_button, alignment=Qt.AlignCenter)

    def _create_stat_card(self, title, initial_value):
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(120)
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; color: #555;")
        value_label = QLabel(initial_value)
        value_label.setObjectName("valueLabel")
        value_label.setStyleSheet("font-size: 36px; font-weight: bold; color: #e74c3c;")
        layout.addWidget(title_label)
        layout.addWidget(value_label, alignment=Qt.AlignCenter)
        return card
        
    def load_dashboard_stats(self):
        def on_success(data, h):
            self.stats_overdue_ft.findChild(QLabel, "valueLabel").setText(str(data.get('overdue_file_tasks', 0)))
            self.stats_overdue_dr.findChild(QLabel, "valueLabel").setText(str(data.get('overdue_data_reports', 0)))
            self.stats_total_schools.findChild(QLabel, "valueLabel").setText(str(data.get('total_schools', 0)))
            self.stats_active_year.findChild(QLabel, "valueLabel").setText(data.get('active_school_year_name', 'N/A'))
        
        def on_error(s, e):
             handle_api_error(self, s, e, "Không thể tải dữ liệu dashboard.")
        
        self.api_get("/admin/dashboard-stats", on_success, on_error)

    def create_school_years_tab(self):
        layout = QVBoxLayout(self.school_years_tab)
        back_button = QPushButton("⬅️ Quay lại")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        
        main_splitter = QHBoxLayout()
        layout.addLayout(main_splitter)

        form_card = QFrame()
        form_card.setObjectName("card")
        form_layout = QVBoxLayout(form_card)
        form_layout.addWidget(QLabel("<b>Tạo Năm học mới</b>"))
        self.sy_name_input = QLineEdit()
        self.sy_name_input.setPlaceholderText("Ví dụ: Năm học 2025-2026")
        self.sy_start_date_input = QDateEdit(QDate.currentDate())
        self.sy_start_date_input.setCalendarPopup(True)
        self.sy_start_date_input.setDisplayFormat("dd/MM/yyyy") 
        self.sy_end_date_input = QDateEdit(QDate.currentDate().addYears(1))
        self.sy_end_date_input.setCalendarPopup(True)
        self.sy_end_date_input.setDisplayFormat("dd/MM/yyyy")
        self.add_sy_button = QPushButton("Thêm Năm học")
        form_layout.addWidget(QLabel("Tên Năm học:"))
        form_layout.addWidget(self.sy_name_input)
        form_layout.addWidget(QLabel("Ngày bắt đầu:"))
        form_layout.addWidget(self.sy_start_date_input)
        form_layout.addWidget(QLabel("Ngày kết thúc:"))
        form_layout.addWidget(self.sy_end_date_input)
        form_layout.addSpacing(15)
        form_layout.addWidget(self.add_sy_button)
        form_layout.addStretch()
        
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("<b>Danh sách các Năm học</b>"))
        self.school_years_list_widget_tab = QListWidget() 
        list_layout.addWidget(self.school_years_list_widget_tab)
        
        main_splitter.addWidget(form_card, 1)
        main_splitter.addWidget(list_card, 2)
        
        self.add_sy_button.clicked.connect(self.add_new_school_year)

    def create_schools_tab(self):
        layout = QVBoxLayout(self.schools_tab)
        back_button = QPushButton("⬅️ Quay lại")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        
        main_splitter = QHBoxLayout()
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        main_splitter.addWidget(left_widget, 2)

        input_card = QFrame()
        input_card.setObjectName("card")
        input_layout = QGridLayout(input_card)
        input_layout.addWidget(QLabel("<b>Thêm Trường học Mới</b>"), 0, 0, 1, 2)
        input_layout.addWidget(QLabel("Tên trường:"), 1, 0)
        self.school_name_input = QLineEdit()
        self.school_name_input.setPlaceholderText("Nhập tên trường mới...")
        input_layout.addWidget(self.school_name_input, 1, 1)
        self.add_school_button = QPushButton("Thêm Trường")
        input_layout.addWidget(self.add_school_button, 2, 1, alignment=Qt.AlignRight)
        left_layout.addWidget(input_card)

        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("<b>Danh sách Trường học và API Key</b>"))
        self.schools_list_widget = QListWidget()
        list_layout.addWidget(self.schools_list_widget)
        left_layout.addWidget(list_card)
        
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        main_splitter.addWidget(right_widget, 1)

        group_card = QFrame()
        group_card.setObjectName("card")
        group_layout = QVBoxLayout(group_card)
        group_layout.addWidget(QLabel("<b>Quản lý Nhóm trường học</b>"))

        self.groups_tree = QTreeWidget()
        self.groups_tree.setHeaderLabels(["Nhóm và các trường thành viên"])
        self.groups_tree.setAlternatingRowColors(True)
        group_layout.addWidget(self.groups_tree)

        group_buttons_layout = QHBoxLayout()
        btn_addg = QPushButton("Thêm")
        btn_addg.clicked.connect(self._group_add)
        btn_editg = QPushButton("Sửa")
        btn_editg.clicked.connect(self._group_rename)
        btn_addmem = QPushButton("Thành viên")
        btn_addmem.clicked.connect(self._group_add_members)
        btn_delg = QPushButton("Xóa")
        btn_delg.clicked.connect(self._group_delete)
        group_buttons_layout.addWidget(btn_addg)
        group_buttons_layout.addWidget(btn_editg)
        group_buttons_layout.addWidget(btn_addmem)
        group_buttons_layout.addWidget(btn_delg)
        group_layout.addLayout(group_buttons_layout)
        right_layout.addWidget(group_card)
        
        layout.addLayout(main_splitter)
        
        self.add_school_button.clicked.connect(self.add_new_school)


    def select_ft_attachment(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file đính kèm")
        if not file_path:
            return

        self.ft_attachment_label.setText("Đang tải lên...")
        
        def on_success(data, headers):
            self.ft_attachment_url = data.get("file_url")
            file_name = os.path.basename(file_path)
            self.ft_attachment_label.setText(f"Đã đính kèm: {file_name}")
            self.ft_attachment_label.setStyleSheet("font-style: normal; color: green;")
            QMessageBox.information(self, "Thành công", "Đã tải file đính kèm lên thành công.")

        def on_error(s, e):
            self.ft_attachment_label.setText("Lỗi tải lên.")
            self.ft_attachment_label.setStyleSheet("font-style: italic; color: red;")
            handle_api_error(self, s, e, "Không thể tải file lên.")

        self.api_upload_file("/admin/upload-attachment", file_path, on_success, on_error)
       
    def create_data_reports_tab(self):
        layout = QVBoxLayout(self.data_reports_tab)
        back_button = QPushButton("⬅️ Quay lại")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        
        main_splitter = QHBoxLayout()
        layout.addLayout(main_splitter)

        design_card = QFrame()
        design_card.setObjectName("card")
        main_splitter.addWidget(design_card, 2)
        design_layout = QGridLayout(design_card)
        design_layout.addWidget(QLabel("<b>Ban hành Báo cáo Nhập liệu</b>"), 0, 0, 1, 2)
        
        design_layout.addWidget(QLabel("Năm học:"), 1, 0)
        self.dr_school_year_selector = QComboBox()
        design_layout.addWidget(self.dr_school_year_selector, 1, 1)
        
        design_layout.addWidget(QLabel("Tiêu đề báo cáo:"), 2, 0)
        self.dr_title_input = QLineEdit()
        design_layout.addWidget(self.dr_title_input, 2, 1)
        
        self.design_schema_button = QPushButton("Thiết kế Bảng nhập liệu")
        self.design_schema_button.clicked.connect(self.open_schema_designer)
        design_layout.addWidget(self.design_schema_button, 3, 1)

        self.dr_design_status_label = QLabel("Trạng thái thiết kế: Chưa có.")
        self.dr_design_status_label.setStyleSheet("font-style: italic; color: #6c757d;")
        design_layout.addWidget(self.dr_design_status_label, 4, 1)

        design_layout.addWidget(QLabel("Hạn chót:"), 5, 0)
        self.dr_deadline_input = QDateTimeEdit(QDateTime.currentDateTime().addDays(7))
        self.dr_deadline_input.setCalendarPopup(True)
        self.dr_deadline_input.setDisplayFormat("HH:mm dd/MM/yyyy")
        design_layout.addWidget(self.dr_deadline_input, 5, 1)

        design_layout.addWidget(QLabel("File đính kèm:"), 6, 0)
        dr_attachment_layout = QHBoxLayout()
        self.dr_attachment_label = QLabel("Chưa có file.")
        self.dr_attachment_label.setStyleSheet("font-style: italic; color: #888;")
        dr_attachment_button = QPushButton("Chọn File...")
        dr_attachment_button.clicked.connect(self.select_dr_attachment)
        dr_attachment_layout.addWidget(self.dr_attachment_label, 1)
        dr_attachment_layout.addWidget(dr_attachment_button)
        design_layout.addLayout(dr_attachment_layout, 6, 1)
        self.dr_attachment_url = None

        design_layout.addWidget(QLabel("Phát hành cho:"), 7, 0)
        scope_row = QHBoxLayout()
        design_layout.addLayout(scope_row, 7, 1)

        self.scope_selector = QComboBox()
        self.scope_selector.addItems(["Tất cả trường", "Theo nhóm", "Chọn trường"])
        scope_row.addWidget(self.scope_selector)

        self.group_selector = QComboBox()
        self.group_selector.setVisible(False)
        scope_row.addWidget(self.group_selector)

        self.pick_schools_btn = QPushButton("Chọn...")
        self.pick_schools_btn.setVisible(False)
        scope_row.addWidget(self.pick_schools_btn)

        self.scope_selector.currentIndexChanged.connect(self._on_scope_change)
        self.pick_schools_btn.clicked.connect(self._pick_schools_dialog)

        self.add_dr_button = QPushButton("Ban hành Báo cáo")
        self.add_dr_button.clicked.connect(self.add_new_data_report)
        design_layout.addWidget(self.add_dr_button, 8, 1, alignment=Qt.AlignRight)
        
        list_card = QFrame()
        list_card.setObjectName("card")
        main_splitter.addWidget(list_card, 3)
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("<b>Danh sách đã ban hành</b>"))
        self.data_reports_list_widget = QListWidget()
        list_layout.addWidget(self.data_reports_list_widget)

    def select_dr_attachment(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file đính kèm cho báo cáo")
        if not file_path:
            return

        self.dr_attachment_label.setText("Đang tải lên...")
        
        def on_success(data, headers):
            self.dr_attachment_url = data.get("file_url")
            file_name = os.path.basename(file_path)
            self.dr_attachment_label.setText(f"Đã đính kèm: {file_name}")
            self.dr_attachment_label.setStyleSheet("font-style: normal; color: green;")
            QMessageBox.information(self, "Thành công", "Đã tải file đính kèm lên thành công.")

        def on_error(s, e):
            self.dr_attachment_label.setText("Lỗi tải lên.")
            self.dr_attachment_label.setStyleSheet("font-style: italic; color: red;")
            handle_api_error(self, s, e, "Không thể tải file lên.")

        self.api_upload_file("/admin/upload-attachment", file_path, on_success, on_error)
        
    def _create_paginated_list_tab(self, page_size="20"):
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)

        top_layout = QHBoxLayout()
        filter_sy_selector = QComboBox()
        top_layout.addWidget(QLabel("Lọc theo năm học:"))
        top_layout.addWidget(filter_sy_selector, 1)
        reload_button = QPushButton("Làm mới")
        top_layout.addWidget(reload_button)
        layout.addLayout(top_layout)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(list_widget, 1)

        pag_layout = QHBoxLayout()
        prev_button = QPushButton("◀ Trước")
        next_button = QPushButton("Tiếp ▶")
        info_label = QLabel("Trang 1")
        size_selector = QComboBox()
        size_selector.addItems(["10", "20", "50"])
        size_selector.setCurrentText(page_size)

        pag_layout.addWidget(prev_button)
        pag_layout.addWidget(next_button)
        pag_layout.addSpacing(15)
        pag_layout.addWidget(QLabel("Kích thước trang:"))
        pag_layout.addWidget(size_selector)
        pag_layout.addStretch(1)
        pag_layout.addWidget(info_label)
        layout.addLayout(pag_layout)

        return {
            "tab": tab_widget,
            "filter_sy_selector": filter_sy_selector,
            "reload_button": reload_button,
            "list_widget": list_widget,
            "prev_button": prev_button,
            "next_button": next_button,
            "info_label": info_label,
            "size_selector": size_selector,
            "pager": Paginator(page_size=int(size_selector.currentText()))
        }

    def create_report_tab(self):
        layout = QVBoxLayout(self.report_tab)
        
        top_layout = QHBoxLayout()
        back_button = QPushButton("⬅️ Quay lại Trang chủ")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        top_layout.addWidget(back_button, alignment=Qt.AlignLeft)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        self.file_report_tab = QWidget()
        self.data_report_tab = QWidget()
        self.summary_tab = QWidget()

        tabs.addTab(self.file_report_tab, "Theo dõi Báo cáo Nộp File")
        tabs.addTab(self.data_report_tab, "Theo dõi Báo cáo Nhập liệu")
        tabs.addTab(self.summary_tab, "Tổng hợp theo kỳ hạn")

        self.create_file_report_ui()
        self.create_data_report_ui()
        self._create_compliance_summary_panel_into(QVBoxLayout(self.summary_tab))

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
        self.fr_remind_button.clicked.connect(lambda: self.send_reminder_handler("file"))
        control_layout.addWidget(self.fr_remind_button)
        self.fr_refresh_button = QPushButton("Làm mới")
        self.fr_refresh_button.clicked.connect(self.load_file_task_report)
        control_layout.addWidget(self.fr_refresh_button)
        self.fr_download_button = QPushButton("Tải tất cả file")
        self.fr_download_button.clicked.connect(self.download_all_files)
        control_layout.addWidget(self.fr_download_button)
        layout.addWidget(control_card)

        report_card = QFrame()
        report_card.setObjectName("card")
        report_layout = QVBoxLayout(report_card)
        self.fr_title_label = QLabel("<b>Báo cáo chi tiết</b>")
        report_layout.addWidget(self.fr_title_label)
        self.fr_table = QTableWidget()
        self.fr_table.setColumnCount(5)
        self.fr_table.setHorizontalHeaderLabels(["STT", "Tên trường", "Trạng thái", "Thời gian nộp", "Hành động"])
        
        header = self.fr_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.fr_table.verticalHeader().setDefaultSectionSize(40)
        self.fr_table.verticalHeader().setVisible(False)

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
        self.dr_remind_button.clicked.connect(lambda: self.send_reminder_handler("data"))
        control_layout.addWidget(self.dr_remind_button)
        self.dr_refresh_button = QPushButton("Làm mới")
        self.dr_refresh_button.clicked.connect(self.load_data_entry_report)
        control_layout.addWidget(self.dr_refresh_button)
        self.dr_view_data_button = QPushButton("Xem & Sửa dữ liệu")
        self.dr_view_data_button.clicked.connect(self.view_and_edit_submitted_data)
        control_layout.addWidget(self.dr_view_data_button)
        self.dr_export_excel_button = QPushButton("Xuất Excel Tổng hợp")
        self.dr_export_excel_button.setStyleSheet("background-color: #16a085;")
        self.dr_export_excel_button.clicked.connect(self.export_data_report_excel)
        control_layout.addWidget(self.dr_export_excel_button)
        layout.addWidget(control_card)

        report_card = QFrame()
        report_card.setObjectName("card")
        report_layout = QVBoxLayout(report_card)
        self.dr_title_label = QLabel("<b>Báo cáo chi tiết</b>")
        report_layout.addWidget(self.dr_title_label)
        self.dr_table = QTableWidget()
        self.dr_table.setColumnCount(4)
        self.dr_table.setHorizontalHeaderLabels(["STT", "Tên trường", "Trạng thái", "Thời gian hoàn thành"])
        
        dr_header = self.dr_table.horizontalHeader()
        dr_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        dr_header.setSectionResizeMode(1, QHeaderView.Stretch)
        dr_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        dr_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.dr_table.verticalHeader().setDefaultSectionSize(40)
        self.dr_table.verticalHeader().setVisible(False)
        
        self.dr_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dr_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        report_layout.addWidget(self.dr_table)
        layout.addWidget(report_card)

    def create_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        back_button = QPushButton("⬅️ Quay lại")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)
        danger_zone_card = QFrame()
        danger_zone_card.setObjectName("card")
        danger_zone_card.setStyleSheet("#card { border: 2px solid #e74c3c; }")
        danger_layout = QVBoxLayout(danger_zone_card)
        danger_layout.addWidget(QLabel("<b>🔴 KHU VỰC NGUY HIỂM</b>"))
        danger_layout.addWidget(QLabel("Các hành động dưới đây không thể hoàn tác. Hãy chắc chắn trước khi thực hiện."))
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
        def on_success(d, h): 
            QMessageBox.information(self, "Thành công", f"Đã thêm năm học '{name}'.")
            self.sy_name_input.clear()
            self.load_school_years()
            self.add_sy_button.setDisabled(False)
            self.add_sy_button.setText("Thêm Năm học")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Không thể thêm năm học.")
            self.add_sy_button.setDisabled(False)
            self.add_sy_button.setText("Thêm Năm học")
        self.api_post("/school_years/", payload, on_success, on_error)

    def load_school_years(self):
        def on_success(data, headers):
            selectors = [self.ft_school_year_selector, self.ft_filter_sy_selector, self.dr_school_year_selector, self.sy_for_summary]
            for selector in selectors:
                selector.clear()
            self.school_years_list_widget_tab.clear()
            self.ft_filter_sy_selector.addItem("Tất cả", userData=None)
            for sy in data:
                widget = SchoolYearListItemWidget(sy['id'], sy['name'], sy['start_date'], sy['end_date'])
                item = QListWidgetItem()
                item.setSizeHint(widget.sizeHint())
                self.school_years_list_widget_tab.addItem(item)
                self.school_years_list_widget_tab.setItemWidget(item, widget)
                for selector in selectors:
                    selector.addItem(sy['name'], userData=sy['id'])
        self.api_get("/school_years/", on_success, lambda s, e: QMessageBox.critical(self, "Lỗi", f"Không thể tải năm học: {e}"))

    def add_new_school(self):
        school_name = self.school_name_input.text().strip()
        if not school_name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên trường.")
            return
        self.add_school_button.setDisabled(True)
        self.add_school_button.setText("Đang thêm...")
        def on_success(d, h): 
            QMessageBox.information(self, "Thành công", f"Đã thêm trường '{school_name}'.")
            self.school_name_input.clear()
            self.load_schools()
            self.add_school_button.setDisabled(False)
            self.add_school_button.setText("Thêm Trường")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Không thể thêm trường.")
            self.add_school_button.setDisabled(False)
            self.add_school_button.setText("Thêm Trường")
        self.api_post("/schools/", {"name": school_name}, on_success, on_error)

    def load_schools(self):
        def on_success(data, headers):
            self._all_schools_cache = data[:]
            self.schools_list_widget.clear()
            for school in data:
                item = QListWidgetItem()
                widget = SchoolListItemWidget(school['id'], school['name'], school['api_key'])
                item.setSizeHint(widget.sizeHint())
                self.schools_list_widget.addItem(item)
                self.schools_list_widget.setItemWidget(item, widget)
            self.load_school_groups_ui()
        self.api_get("/schools/", on_success, lambda s,e: QMessageBox.critical(self,"Lỗi",f"Không thể tải trường học: {e}"))

    def add_new_file_task(self):
        school_year_id = self.ft_school_year_selector.currentData()
        title = self.ft_title_input.text().strip()
        content = self.ft_content_input.toPlainText().strip()
        if not all([title, content, school_year_id]):
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đủ thông tin.")
            return

        target_school_ids = None
        mode = self.ft_scope_selector.currentText()
        if mode == "Theo nhóm":
            gname = self.ft_group_selector.currentText()
            target_school_ids = self.school_groups.get(gname, [])
            if not target_school_ids: 
                QMessageBox.warning(self, "Nhóm rỗng", "Nhóm được chọn chưa có trường nào.")
                return
        elif mode == "Chọn trường":
            if not self._ft_custom_selected_school_ids: 
                QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn ít nhất một trường.")
                return
            target_school_ids = sorted(list(self._ft_custom_selected_school_ids))

        self.add_ft_button.setDisabled(True)
        self.add_ft_button.setText("Đang phát hành...")
        payload = {
            "title": title, "content": content,
            "deadline": self.ft_deadline_input.dateTime().toString("yyyy-MM-dd'T'HH:mm:ss"),
            "school_year_id": school_year_id,
            "target_school_ids": target_school_ids,
            "attachment_url": self.ft_attachment_url
        }

        def on_success(d, h):
            QMessageBox.information(self, "Thành công", "Đã ban hành yêu cầu mới.")
            self.ft_title_input.clear()
            self.ft_content_input.clear()
            self._ft_custom_selected_school_ids.clear()
            self.ft_attachment_url = None
            self.ft_attachment_label.setText("Chưa có file.")
            self.ft_attachment_label.setStyleSheet("font-style: italic; color: #888;")
            self.load_file_tasks()
            self.add_ft_button.setDisabled(False)
            self.add_ft_button.setText("Phát hành Yêu cầu")

        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể tạo yêu cầu.")
            self.add_ft_button.setDisabled(False)
            self.add_ft_button.setText("Phát hành Yêu cầu")

        self.api_post("/file-tasks/", payload, on_success, on_error)
        
    def load_file_tasks(self):
        school_year_id = self.ft_filter_sy_selector.currentData()
        params = {"school_year_id": school_year_id, "limit": 1000}

        def on_ok(data, _):
            self.file_tasks_list_widget.clear()
            for t in data:
                deadline_str = QDateTime.fromString(t['deadline'].replace('T', ' '), "yyyy-MM-dd HH:mm:ss").toString("HH:mm dd/MM/yyyy") if t.get('deadline') else "N/A"
                w = FileTaskListItemWidget(
                    task_id=t['id'],
                    title=t['title'],
                    content=t.get('content', ""),
                    deadline=deadline_str,
                    school_year_id=t['school_year_id'],
                    is_locked=t.get('is_locked', False),
                    attachment_url=t.get('attachment_url')
                )
                item = QListWidgetItem(self.file_tasks_list_widget)
                item.setSizeHint(w.sizeHint())
                self.file_tasks_list_widget.addItem(item)
                self.file_tasks_list_widget.setItemWidget(item, w)

        def on_err(s, e):
            handle_api_error(self, s, e, "Không tải được danh sách Yêu cầu nộp file")

        self.api_get("/file-tasks/", on_ok, on_err, params=params)

    def add_new_data_report(self):
        school_year_id = self.dr_school_year_selector.currentData()
        title = self.dr_title_input.text().strip()
        if not all([title, school_year_id]): 
            QMessageBox.warning(self,"Thiếu thông tin","Vui lòng nhập Tiêu đề và chọn Năm học.")
            return
        if not self.current_report_schema:
            QMessageBox.warning(self,"Thiếu thiết kế","Vui lòng thiết kế biểu mẫu.")
            return

        target_school_ids = None
        mode = self.scope_selector.currentText()
        if mode == "Theo nhóm":
            gname = self.group_selector.currentText()
            target_school_ids = self.school_groups.get(gname, [])
            if not target_school_ids:
                QMessageBox.warning(self,"Nhóm rỗng","Nhóm chưa có trường.")
                return
        elif mode == "Chọn trường":
            if not self._custom_selected_school_ids:
                QMessageBox.warning(self,"Chưa chọn","Hãy chọn ít nhất một trường.")
                return
            target_school_ids = sorted(list(self._custom_selected_school_ids))

        payload = {
            "title": title,
            "deadline": self.dr_deadline_input.dateTime().toString("yyyy-MM-dd'T'HH:mm:ss"),
            "school_year_id": school_year_id,
            "columns_schema": self.current_report_schema,
            "template_data": self.current_report_data,
            "target_school_ids": target_school_ids,
            "attachment_url": self.dr_attachment_url
        }

        self.add_dr_button.setDisabled(True)
        self.add_dr_button.setText("Đang ban hành...")
        def on_success(d, h):
            QMessageBox.information(self, "Thành công", "Đã ban hành báo cáo mới.")
            self.dr_title_input.clear()
            self.current_report_schema = []
            self.current_report_data = []
            self._custom_selected_school_ids = set()
            self.dr_attachment_url = None
            self.dr_attachment_label.setText("Chưa có file.")
            self.dr_attachment_label.setStyleSheet("font-style: italic; color: #888;")
            
            self.dr_design_status_label.setText("Trạng thái thiết kế: Chưa có.")
            self.dr_design_status_label.setStyleSheet("font-style: italic; color: #6c757d;")
            self.load_data_reports()
            self.add_dr_button.setDisabled(False)
            self.add_dr_button.setText("Ban hành Báo cáo")
        def on_error(s,e):
            handle_api_error(self, s, e, "Không thể tạo báo cáo.")
            self.add_dr_button.setDisabled(False)
            self.add_dr_button.setText("Ban hành Báo cáo")
        self.api_post("/data-reports/", payload, on_success, on_error)
       
    def load_data_reports(self):
        school_year_id = self.dr_school_year_selector.currentData()
        params = {
            "school_year_id": school_year_id,
            "limit": 1000
        }

        def on_ok(data, _):
            self.data_reports_list_widget.clear()
            for r in data:
                deadline_str = QDateTime.fromString(r['deadline'].replace('T', ' '), "yyyy-MM-dd HH:mm:ss").toString("HH:mm dd/MM/yyyy") if r.get('deadline') else "N/A"
                w = DataReportListItemWidget(
                    report_id=r['id'],
                    title=r['title'],
                    deadline=deadline_str,
                    schema=r.get('columns_schema', []),
                    template_data=r.get('template_data'),
                    is_locked=r.get('is_locked', False),
                    attachment_url=r.get('attachment_url')
                )
                it = QListWidgetItem(self.data_reports_list_widget)
                it.setSizeHint(w.sizeHint())
                self.data_reports_list_widget.addItem(it)
                self.data_reports_list_widget.setItemWidget(it, w)
                
        def on_err(s, e):
            handle_api_error(self, s, e, "Không tải được danh sách Báo cáo nhập liệu")

        self.api_get("/data-reports/", on_ok, on_err, params=params)

    def load_file_task_report(self):
        task_id = self.fr_task_selector.currentData()
        if task_id is None:
            self.fr_table.setRowCount(0)
            self.fr_title_label.setText("Vui lòng chọn một yêu cầu")
            return
        self.fr_refresh_button.setDisabled(True)
        self.fr_refresh_button.setText("Đang tải...")
        def on_success(data, h):
            self.fr_title_label.setText(f"<b>Báo cáo chi tiết cho: {data.get('task', {}).get('title', '')}</b>")
            submitted = data.get('submitted_schools', [])
            not_submitted = data.get('not_submitted_schools', [])
            all_schools = submitted + not_submitted
            self.fr_table.setRowCount(len(all_schools))
            for i, school in enumerate(all_schools):
                is_submitted = 'submitted_at' in school
                stt = QTableWidgetItem(str(i + 1))
                name = QTableWidgetItem(school['name'])
                status = QTableWidgetItem("Đã nộp" if is_submitted else "Chưa nộp")
                status.setForeground(QColor("green" if is_submitted else "red"))
                time_str = QDateTime.fromString(school['submitted_at'], "yyyy-MM-dd'T'HH:mm:ss").toLocalTime().toString("HH:mm dd/MM/yyyy") if is_submitted else ""
                time = QTableWidgetItem(time_str)
                self.fr_table.setItem(i, 0, stt)
                self.fr_table.setItem(i, 1, name)
                self.fr_table.setItem(i, 2, status)
                self.fr_table.setItem(i, 3, time)

                if is_submitted:
                    btn = QPushButton("Xem file")
                    file_url = school.get('file_url', '')
                    btn.clicked.connect(lambda _, url=file_url: webbrowser.open(url))
                    self.fr_table.setCellWidget(i, 4, btn)
            self.fr_refresh_button.setDisabled(False)
            self.fr_refresh_button.setText("Làm mới")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Không thể tải báo cáo.")
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
        def on_success(data, h):
            self.dr_title_label.setText(f"<b>Báo cáo chi tiết cho: {data.get('report', {}).get('title', '')}</b>")
            submitted = data.get('submitted_schools', [])
            not_submitted = data.get('not_submitted_schools', [])
            all_schools = submitted + not_submitted
            self.dr_table.setRowCount(len(all_schools))
            
            for i, school in enumerate(all_schools):
                stt_item = QTableWidgetItem(str(i + 1))
                stt_item.setData(Qt.UserRole, school['id'])
                name_item = QTableWidgetItem(school['name'])
                
                is_submitted = 'submitted_at' in school
                status_item = QTableWidgetItem("Đã hoàn thành" if is_submitted else "Chưa thực hiện")
                status_item.setForeground(QColor("green" if is_submitted else "red"))
                
                time_str = QDateTime.fromString(school.get('submitted_at', ''), "yyyy-MM-dd'T'HH:mm:ss").toLocalTime().toString("HH:mm dd/MM/yyyy") if is_submitted else ""
                time_item = QTableWidgetItem(time_str)
                
                self.dr_table.setItem(i, 0, stt_item)
                self.dr_table.setItem(i, 1, name_item)
                self.dr_table.setItem(i, 2, status_item)
                self.dr_table.setItem(i, 3, time_item)
                
            self.dr_refresh_button.setDisabled(False)
            self.dr_refresh_button.setText("Làm mới")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Không thể tải báo cáo.")
            self.dr_refresh_button.setDisabled(False)
            self.dr_refresh_button.setText("Làm mới")
        self.api_get(f"/data-reports/{report_id}/status", on_success, on_error)

    def view_and_edit_submitted_data(self):
        report_id = self.dr_report_selector.currentData()
        if report_id is None:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một báo cáo.")
            return
        selected_rows = self.dr_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một trường từ bảng.")
            return
        
        row_index = selected_rows[0].row()
        school_id = self.dr_table.item(row_index, 0).data(Qt.UserRole)
        school_name = self.dr_table.item(row_index, 1).text()

        def on_schema_success(schema_data, h):
            columns = [ColumnSpec(**col) for col in schema_data.get("columns_schema", [])]
            
            def on_data_success(submission_data, h):
                dialog = QDialog(self)
                dialog.setWindowTitle(f"Dữ liệu của: {school_name}")
                dialog.setMinimumSize(900, 600)
                layout = QVBoxLayout(dialog)
                
                sheet = SpreadsheetWidget(columns, dialog)
                sheet.set_data(submission_data.get("data", []))
                
                def handle_save(records):
                    payload = {"data": records}
                    
                    def on_admin_update_success(d, h):
                        QMessageBox.information(dialog, "Thành công", "Đã cập nhật dữ liệu cho trường.")
                        self.load_data_entry_report()
                        dialog.accept()

                    def on_admin_update_error(s, e):
                        handle_api_error(dialog, s, e, "Không thể cập nhật dữ liệu.")

                    self.api_put(f"/admin/data-submissions/{report_id}/{school_id}", payload, 
                                 on_admin_update_success, on_admin_update_error)

                sheet.saved.connect(handle_save)
                layout.addWidget(sheet)
                dialog.exec()
            
            def on_data_error(s,e):
                handle_api_error(self, s, e, "Lỗi tải dữ liệu nộp.")
            self.api_get(f"/data-reports/{report_id}/submission/{school_id}", on_data_success, on_data_error)

        def on_schema_error(s, e): 
            handle_api_error(self, s, e, "Không thể tải cấu trúc biểu mẫu.")
        
        self.api_get(f"/data-reports/{report_id}/schema", on_schema_success, on_schema_error)

    def send_reminder_handler(self, task_type):
        task_id = self.fr_task_selector.currentData() if task_type == "file" else self.dr_report_selector.currentData()
        button = self.fr_remind_button if task_type == "file" else self.dr_remind_button
        if task_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một yêu cầu.")
            return
        reply = QMessageBox.question(self, 'Xác nhận', "Gửi nhắc nhở đến tất cả các trường chưa nộp?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        button.setDisabled(True)
        button.setText("Đang gửi...")
        def on_success(d, h): 
            QMessageBox.information(self, "Thành công", d.get("message", "Đã gửi."))
            button.setDisabled(False)
            button.setText("Gửi nhắc nhở")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Lỗi gửi nhắc nhở.")
            button.setDisabled(False)
            button.setText("Gửi nhắc nhở")
        self.api_post(f"/admin/remind/{task_type}/{task_id}", {}, on_success, on_error)

    def download_all_files(self):
        task_id = self.fr_task_selector.currentData()
        if task_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn yêu cầu.")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Lưu file ZIP", f"task_{task_id}.zip", "ZIP Files (*.zip)")
        if not save_path:
            return
        self.fr_download_button.setDisabled(True)
        self.fr_download_button.setText("Đang tải...")
        def on_success(data_bytes):
            try:
                with open(save_path, 'wb') as f:
                    f.write(data_bytes)
                QMessageBox.information(self, "Thành công", f"Đã lưu file ZIP tại:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể ghi file: {e}")
            self.fr_download_button.setDisabled(False)
            self.fr_download_button.setText("Tải tất cả file")
        def on_error(s, e):
            if s == 404:
                QMessageBox.information(self, "Thông báo", "Không có file nào được nộp.")
            else:
                handle_api_error(self, s, e, "Không thể tải file.")
            self.fr_download_button.setDisabled(False)
            self.fr_download_button.setText("Tải tất cả file")
        self.api_download(f"/file-tasks/{task_id}/download-all", on_success, on_error)

    def export_data_report_excel(self):
        report_id = self.dr_report_selector.currentData()
        if report_id is None:
            QMessageBox.warning(self, "Chưa chọn", "Vui lòng chọn một báo cáo để xuất file.")
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "Lưu file Excel", f"tong_hop_bao_cao_{report_id}.xlsx", "Excel Files (*.xlsx)")
        if not save_path:
            return

        self.dr_export_excel_button.setDisabled(True)
        self.dr_export_excel_button.setText("Đang xuất...")

        def on_success(data_bytes):
            try:
                with open(save_path, 'wb') as f:
                    f.write(data_bytes)
                QMessageBox.information(self, "Thành công", f"Đã lưu file Excel tổng hợp tại:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể ghi file: {e}")
            finally:
                self.dr_export_excel_button.setDisabled(False)
                self.dr_export_excel_button.setText("Xuất Excel Tổng hợp")

        def on_error(s, e):
            if s == 404:
                 QMessageBox.information(self, "Thông báo", "Chưa có trường nào nộp dữ liệu cho báo cáo này.")
            else:
                handle_api_error(self, s, e, "Không thể xuất file Excel.")
            self.dr_export_excel_button.setDisabled(False)
            self.dr_export_excel_button.setText("Xuất Excel Tổng hợp")

        self.api_download(f"/data-reports/{report_id}/export-excel", on_success, on_error)
        
    def handle_reset_database(self):
        password, ok = QInputDialog.getText(self, "Yêu cầu Mật khẩu", "Nhập mật khẩu quản trị:", QLineEdit.Password)
        if not ok or not password:
            return
        confirm_text, ok = QInputDialog.getText(self, "Xác nhận Lần cuối", 'Hành động này sẽ xóa TẤT CẢ dữ liệu. Để xác nhận, gõ "XOA DU LIEU":')
        if not ok or confirm_text != "XOA DU LIEU":
            QMessageBox.warning(self, "Đã hủy", "Chuỗi xác nhận không chính xác.")
            return
        self.reset_db_button.setDisabled(True)
        self.reset_db_button.setText("Đang xóa...")
        def on_success(d, h): 
            QMessageBox.information(self, "Thành công", "Đã xóa toàn bộ dữ liệu.")
            self.load_all_initial_data()
            self.reset_db_button.setDisabled(False)
            self.reset_db_button.setText("Xóa Toàn Bộ Dữ Liệu")
        def on_error(s, e): 
            handle_api_error(self, s, e, "Lỗi xóa dữ liệu.")
            self.reset_db_button.setDisabled(False)
            self.reset_db_button.setText("Xóa Toàn Bộ Dữ Liệu")
        self.api_post("/admin/reset-database", {"password": password}, on_success, on_error)

    def open_schema_designer(self):
        dlg = GridDesignDialog(self.current_report_schema, self.current_report_data, self)
        if dlg.exec():
            self.current_report_schema = dlg.get_schema()
            self.current_report_data = dlg.get_data() 
            num_cols = len(self.current_report_schema)
            num_rows = len(self.current_report_data)
            self.dr_design_status_label.setText(f"Trạng thái: Đã lưu ({num_cols} cột, {num_rows} dòng dữ liệu).")
            self.dr_design_status_label.setStyleSheet("font-style: italic; color: green;")

    def load_school_groups_ui(self):
        path = "school_groups.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.school_groups = json.load(f) or {}
            except Exception:
                self.school_groups = {}
        else:
            self.school_groups = {}
        
        self.group_selector.clear()
        self.ft_group_selector.clear()
        for gname in sorted(self.school_groups.keys()): 
            self.group_selector.addItem(gname)
            self.ft_group_selector.addItem(gname)
        self.update_groups_view()

    def update_groups_view(self):
        self.groups_tree.clear()
        school_map = {s['id']: s['name'] for s in self._all_schools_cache}
        sorted_group_names = sorted(self.school_groups.keys())

        for gname in sorted_group_names:
            school_ids = self.school_groups[gname]
            group_item = QTreeWidgetItem(self.groups_tree)
            group_item.setText(0, f"{gname} ({len(school_ids)} trường)")
            group_item.setFont(0, QFont("Segoe UI", 10, QFont.Bold))
            member_schools = sorted([school_map.get(sid, f"ID không xác định: {sid}") for sid in school_ids])
            for school_name in member_schools:
                school_item = QTreeWidgetItem(group_item)
                school_item.setText(0, school_name)
        self.groups_tree.expandAll()

    def _save_school_groups(self):
        with open("school_groups.json", "w", encoding="utf-8") as f:
            json.dump(self.school_groups, f, ensure_ascii=False, indent=2)

    def _on_scope_change(self, idx):
        mode = self.scope_selector.currentText()
        self.group_selector.setVisible(mode == "Theo nhóm")
        self.pick_schools_btn.setVisible(mode == "Chọn trường")

    def _pick_schools_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Chọn trường")
        v = QVBoxLayout(dlg)
        listw = QListWidget()
        v.addWidget(listw)

        id_map = {}
        for s in self._all_schools_cache:
            item = QListWidgetItem(s['name'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if s['id'] in self._custom_selected_school_ids:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            listw.addItem(item)
            id_map[s['name']] = s['id']

        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btn)
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        
        if dlg.exec():
            self._custom_selected_school_ids.clear()
            for i in range(listw.count()):
                item = listw.item(i)
                if item.checkState() == Qt.Checked:
                    school_name = item.text()
                    school_id = id_map.get(school_name)
                    if school_id:
                        self._custom_selected_school_ids.add(school_id)
            
            QMessageBox.information(self, "Đã chọn", f"Bạn đã chọn {len(self._custom_selected_school_ids)} trường.")

    def create_file_tasks_tab(self):
        layout = QVBoxLayout(self.file_tasks_tab)
        back_button = QPushButton("⬅️ Quay lại")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.dashboard_tab))
        layout.addWidget(back_button, alignment=Qt.AlignLeft)

        main_splitter = QHBoxLayout()
        layout.addLayout(main_splitter)

        form_card = QFrame()
        form_card.setObjectName("card")
        main_splitter.addWidget(form_card, 2)
        form_layout = QGridLayout(form_card)
        form_layout.addWidget(QLabel("<b>Ban hành Yêu cầu Nộp File</b>"), 0, 0, 1, 2)

        form_layout.addWidget(QLabel("Năm học:"), 1, 0)
        self.ft_school_year_selector = QComboBox()
        form_layout.addWidget(self.ft_school_year_selector, 1, 1)

        form_layout.addWidget(QLabel("Tiêu đề:"), 2, 0)
        self.ft_title_input = QLineEdit()
        form_layout.addWidget(self.ft_title_input, 2, 1)

        form_layout.addWidget(QLabel("Nội dung/Yêu cầu:"), 3, 0)
        self.ft_content_input = QTextEdit()
        self.ft_content_input.setPlaceholderText("Nhập chi tiết yêu cầu tại đây...")
        form_layout.addWidget(self.ft_content_input, 3, 1)

        form_layout.addWidget(QLabel("Hạn chót:"), 4, 0)
        self.ft_deadline_input = QDateTimeEdit(QDateTime.currentDateTime().addDays(7))
        self.ft_deadline_input.setCalendarPopup(True)
        self.ft_deadline_input.setDisplayFormat("HH:mm dd/MM/yyyy")
        form_layout.addWidget(self.ft_deadline_input, 4, 1)

        form_layout.addWidget(QLabel("File đính kèm:"), 5, 0)
        ft_attachment_layout = QHBoxLayout()
        self.ft_attachment_label = QLabel("Chưa có file.")
        self.ft_attachment_label.setStyleSheet("font-style: italic; color: #888;")
        ft_attachment_button = QPushButton("Chọn File...")
        ft_attachment_button.clicked.connect(self.select_ft_attachment)
        ft_attachment_layout.addWidget(self.ft_attachment_label, 1)
        ft_attachment_layout.addWidget(ft_attachment_button)
        form_layout.addLayout(ft_attachment_layout, 5, 1)
        self.ft_attachment_url = None

        form_layout.addWidget(QLabel("Phát hành cho:"), 6, 0)
        scope_row = QHBoxLayout()
        form_layout.addLayout(scope_row, 6, 1)

        self.ft_scope_selector = QComboBox()
        self.ft_scope_selector.addItems(["Tất cả trường", "Theo nhóm", "Chọn trường"])
        scope_row.addWidget(self.ft_scope_selector)

        self.ft_group_selector = QComboBox()
        self.ft_group_selector.setVisible(False)
        scope_row.addWidget(self.ft_group_selector)

        self.ft_pick_schools_btn = QPushButton("Chọn...")
        self.ft_pick_schools_btn.setVisible(False)
        scope_row.addWidget(self.ft_pick_schools_btn)

        self.ft_scope_selector.currentIndexChanged.connect(self._on_ft_scope_change)
        self.ft_pick_schools_btn.clicked.connect(self._ft_pick_schools_dialog)

        self.add_ft_button = QPushButton("Phát hành Yêu cầu")
        form_layout.addWidget(self.add_ft_button, 7, 1, alignment=Qt.AlignRight)
        self.add_ft_button.clicked.connect(self.add_new_file_task)

        list_card = QFrame()
        list_card.setObjectName("card")
        main_splitter.addWidget(list_card, 3)
        list_layout = QVBoxLayout(list_card)
        
        list_header_layout = QHBoxLayout()
        list_header_layout.addWidget(QLabel("<b>Danh sách đã ban hành</b>"))
        list_header_layout.addStretch()
        list_header_layout.addWidget(QLabel("Lọc theo năm học:"))
        self.ft_filter_sy_selector = QComboBox()
        self.ft_filter_sy_selector.currentIndexChanged.connect(self.load_file_tasks)
        list_header_layout.addWidget(self.ft_filter_sy_selector)
        
        list_layout.addLayout(list_header_layout)
        self.file_tasks_list_widget = QListWidget()
        list_layout.addWidget(self.file_tasks_list_widget)


    def _on_ft_scope_change(self, idx):
        mode = self.ft_scope_selector.currentText()
        self.ft_group_selector.setVisible(mode == "Theo nhóm")
        self.ft_pick_schools_btn.setVisible(mode == "Chọn trường")

    def _ft_pick_schools_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Chọn trường cho Yêu cầu nộp file")
        v = QVBoxLayout(dlg)
        listw = QListWidget()
        v.addWidget(listw)

        id_map = {}
        for s in self._all_schools_cache:
            item = QListWidgetItem(s['name'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if s['id'] in self._ft_custom_selected_school_ids:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            listw.addItem(item)
            id_map[s['name']] = s['id']

        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btn)
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        
        if dlg.exec():
            self._ft_custom_selected_school_ids.clear()
            for i in range(listw.count()):
                item = listw.item(i)
                if item.checkState() == Qt.Checked:
                    school_id = id_map.get(item.text())
                    if school_id:
                        self._ft_custom_selected_school_ids.add(school_id)

            QMessageBox.information(self, "Đã chọn", f"Bạn đã chọn {len(self._ft_custom_selected_school_ids)} trường.")

    def _group_add(self):
        name, ok = QInputDialog.getText(self, "Tên nhóm", "Nhập tên nhóm:")
        if not ok or not name.strip():
            return
        if name in self.school_groups:
            QMessageBox.warning(self,"Trùng","Nhóm đã tồn tại.")
            return
        self.school_groups[name] = []
        self._save_school_groups()
        self.load_school_groups_ui()

    def _group_rename(self):
        if not self.school_groups:
            return
        old, ok = QInputDialog.getItem(self, "Chọn nhóm", "Nhóm:", list(self.school_groups.keys()), 0, False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Đổi tên", "Tên mới:", text=old)
        if not ok or not new.strip():
            return
        if new in self.school_groups:
            QMessageBox.warning(self,"Trùng","Tên nhóm đã có.")
            return
        self.school_groups[new] = self.school_groups.pop(old)
        self._save_school_groups()
        self.load_school_groups_ui()

    def _group_add_members(self):
        if not self.school_groups:
            QMessageBox.information(self,"Chưa có nhóm","Hãy tạo nhóm trước.")
            return
        gname, ok = QInputDialog.getItem(self, "Chọn nhóm", "Nhóm:", list(self.school_groups.keys()), 0, False)
        if not ok:
            return
        
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Thêm/bớt trường cho nhóm '{gname}'")
        v = QVBoxLayout(dlg)
        listw = QListWidget()
        v.addWidget(listw)

        current_members = set(self.school_groups.get(gname, []))
        id_map = {}
        for s in self._all_schools_cache:
            item = QListWidgetItem(s['name'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if s['id'] in current_members:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            listw.addItem(item)
            id_map[s['name']] = s['id']
            
        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btn)
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        
        if dlg.exec():
            selected_ids = set()
            for i in range(listw.count()):
                item = listw.item(i)
                if item.checkState() == Qt.Checked:
                    school_id = id_map.get(item.text())
                    if school_id:
                        selected_ids.add(school_id)

            self.school_groups[gname] = sorted(list(selected_ids))
            self._save_school_groups()
            self.load_school_groups_ui()
            QMessageBox.information(self, "Thành công", f"Đã cập nhật thành viên cho nhóm '{gname}'.")

    def _group_delete(self):
        if not self.school_groups: return
        gname, ok = QInputDialog.getItem(self, "Xóa nhóm", "Nhóm:", list(self.school_groups.keys()), 0, False)
        if not ok: return
        if QMessageBox.question(self,"Xác nhận",f"Xóa nhóm '{gname}'?")==QMessageBox.Yes:
            self.school_groups.pop(gname, None)
            self._save_school_groups(); self.load_school_groups_ui()
            
    def _create_compliance_summary_panel_into(self, parent_layout):
        card = QFrame(objectName="card"); parent_layout.addWidget(card)
        v = QVBoxLayout(card)
        v.addWidget(QLabel("<b>BÁO CÁO TỔNG HỢP THEO KỲ HẠN</b>"))

        row = QHBoxLayout()
        self.cb_kind = QComboBox(); self.cb_kind.addItems(["Cả hai", "Nộp file", "Nhập liệu"])
        self.cb_period = QComboBox(); self.cb_period.addItems(["Tháng hiện tại", "Học kỳ 1", "Học kỳ 2", "Toàn năm học", "Tùy chọn..."])
        self.sy_for_summary = QComboBox()

        self.dt_start = QDateTimeEdit(); self.dt_start.setCalendarPopup(True); self.dt_start.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.dt_end   = QDateTimeEdit(); self.dt_end.setCalendarPopup(True);   self.dt_end.setDisplayFormat("dd/MM/yyyy HH:mm")
        
        self.cb_period.currentIndexChanged.connect(self._update_summary_datetime_widgets)
        self.sy_for_summary.currentIndexChanged.connect(self._update_summary_datetime_widgets)

        row.addWidget(QLabel("Loại:")); row.addWidget(self.cb_kind)
        row.addSpacing(10)
        row.addWidget(QLabel("Kỳ hạn:")); row.addWidget(self.cb_period)
        row.addSpacing(10)
        row.addWidget(QLabel("Năm học:")); row.addWidget(self.sy_for_summary, 1)
        row.addSpacing(10)
        row.addWidget(QLabel("Từ:")); row.addWidget(self.dt_start)
        row.addWidget(QLabel("Đến:")); row.addWidget(self.dt_end)
        v.addLayout(row)

        self.btn_summary = QPushButton("Tổng hợp"); self.btn_summary.clicked.connect(self.run_compliance_summary)
        v.addWidget(self.btn_summary, alignment=Qt.AlignRight)

        def _make_table(title):
            box = QFrame(objectName="card")
            lay = QVBoxLayout(box)
            lay.addWidget(QLabel(f"<b>{title}</b>"))
            tbl = QTableWidget(0, 5)
            tbl.setHorizontalHeaderLabels(["STT", "Trường", "Giao", "Đúng hạn", "Trễ / Không nộp"])
            tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            lay.addWidget(tbl)
            v.addWidget(box)
            return tbl

        self.tbl_ontime  = _make_table("ĐÚNG HẠN")
        self.tbl_late    = _make_table("TRỄ HẠN")
        self.tbl_missing = _make_table("KHÔNG BÁO CÁO")

        def on_ok(data, _):
            self._school_year_cache = data
            self.sy_for_summary.clear()
            for sy in data: self.sy_for_summary.addItem(sy['name'], sy['id'])
            self._update_summary_datetime_widgets()
        self.api_get("/school_years/", on_ok, lambda s,e: None)

    def _update_summary_datetime_widgets(self):
        import datetime as _dt
        import calendar

        sel = self.cb_period.currentText()
        sy_id = self.sy_for_summary.currentData()
        
        is_custom = (sel == "Tùy chọn...")
        self.dt_start.setEnabled(is_custom)
        self.dt_end.setEnabled(is_custom)
        if is_custom:
            return

        start_dt_py, end_dt_py = None, None

        if sel == "Tháng hiện tại":
            today = _dt.date.today()
            start_dt_py = _dt.datetime(today.year, today.month, 1, 0, 0, 0)
            _, last_day = calendar.monthrange(today.year, today.month)
            end_dt_py = _dt.datetime(today.year, today.month, last_day, 23, 59, 59)
        else:
            if sy_id is None or not self._school_year_cache:
                return
            
            sy_info = next((x for x in self._school_year_cache if x["id"] == sy_id), None)
            if not sy_info:
                return

            sy_start = _dt.datetime.fromisoformat(sy_info['start_date'] + "T00:00:00")
            sy_end = _dt.datetime.fromisoformat(sy_info['end_date'] + "T23:59:59")
            start_dt_py, end_dt_py = sy_start, sy_end

            if sel == "Toàn năm học":
                pass
            elif sel == "Học kỳ 1":
                hk1_end = _dt.datetime(sy_start.year, 12, 31, 23, 59, 59)
                end_dt_py = min(hk1_end, sy_end)
            elif sel == "Học kỳ 2":
                hk2_year = sy_start.year + 1 if sy_start.month >= 8 else sy_start.year
                hk2_start = _dt.datetime(hk2_year, 1, 1, 0, 0, 0)
                start_dt_py = max(hk2_start, sy_start)
        
        if start_dt_py and end_dt_py:
            local_tz = QTimeZone.systemTimeZone()
            start_qdt = QDateTime(
                QDate(start_dt_py.year, start_dt_py.month, start_dt_py.day),
                QTime(start_dt_py.hour, start_dt_py.minute, start_dt_py.second),
                local_tz
            )
            end_qdt = QDateTime(
                QDate(end_dt_py.year, end_dt_py.month, end_dt_py.day),
                QTime(end_dt_py.hour, end_dt_py.minute, end_dt_py.second),
                local_tz
            )
            self.dt_start.setDateTime(start_qdt)
            self.dt_end.setDateTime(end_qdt)
            
    def run_compliance_summary(self):
        sy_id = self.sy_for_summary.currentData()
        kind_map = {"Cả hai": "both", "Nộp file": "file", "Nhập liệu": "data"}
        kind = kind_map.get(self.cb_kind.currentText(), "both")

        import datetime as _dt
        import calendar

        # Hàm nội bộ để gửi request, GIỮ NGUYÊN logic — CHỈ sửa format thời gian sang UTC có 'Z'
        def _send_request(start_qdt: QDateTime, end_qdt: QDateTime):
            # Chuyển đổi QDateTime sang UTC
            start_utc = start_qdt.toTimeZone(QTimeZone.utc())
            end_utc = end_qdt.toTimeZone(QTimeZone.utc())

            # ✅ Sửa tại đây: định dạng ISO-8601 có hậu tố 'Z' để backend parse UTC chính xác
            start_str = start_utc.toString("yyyy-MM-dd'T'HH:mm:ss'Z'")
            end_str = end_utc.toString("yyyy-MM-dd'T'HH:mm:ss'Z'")

            params = {"kind": kind, "start": start_str, "end": end_str}
            if sy_id is not None:
                params["school_year_id"] = sy_id

            self.btn_summary.setDisabled(True); self.btn_summary.setText("Đang tổng hợp...")

            def on_ok(data, _):
                def _fill(tbl, items):
                    tbl.setRowCount(len(items))
                    for i, it in enumerate(items, 1):
                        tbl.setItem(i - 1, 0, QTableWidgetItem(str(i)))
                        tbl.setItem(i - 1, 1, QTableWidgetItem(it['name']))
                        tbl.setItem(i - 1, 2, QTableWidgetItem(str(it['assigned_count'])))
                        tbl.setItem(i - 1, 3, QTableWidgetItem(str(it['ontime_count'])))
                        tbl.setItem(i - 1, 4, QTableWidgetItem(f"{it['late_count']} / {it['missing_count']}"))
                self.tbl_ontime.setRowCount(0); self.tbl_late.setRowCount(0); self.tbl_missing.setRowCount(0)
                _fill(self.tbl_ontime, data.get("ontime", []))
                _fill(self.tbl_late, data.get("late", []))
                _fill(self.tbl_missing, data.get("missing", []))
                self.btn_summary.setDisabled(False); self.btn_summary.setText("Tổng hợp")

            def on_err(s, e):
                handle_api_error(self, s, e, "Không thể tổng hợp.")
                self.btn_summary.setDisabled(False); self.btn_summary.setText("Tổng hợp")

            self.api_get("/admin/compliance-summary", on_ok, on_err, params=params)

        # LUỒNG CHÍNH: Xác định khoảng thời gian
        sel = self.cb_period.currentText()
        if sel == "Tùy chọn...":
            # Lấy QDateTime trực tiếp từ widget (local time), _send_request sẽ tự chuyển UTC
            start_qdt = self.dt_start.dateTime()
            end_qdt = self.dt_end.dateTime()
            _send_request(start_qdt, end_qdt)
        else:
            if sy_id is None and sel != "Tháng hiện tại":
                QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng chọn Năm học khi sử dụng các kỳ hạn định sẵn.")
                return

            # Lấy thông tin năm học khi cần
            def on_ok(sy_list, _):
                sy_info = None
                if sy_id is not None:
                    for it in sy_list:
                        if it["id"] == sy_id:
                            sy_info = it
                            break

                # Tính start/end (Python datetime, local) cho các kỳ hạn
                if sel == "Tháng hiện tại":
                    today = _dt.date.today()
                    start_dt_py = _dt.datetime(today.year, today.month, 1, 0, 0, 0)
                    _, last_day = calendar.monthrange(today.year, today.month)
                    end_dt_py = _dt.datetime(today.year, today.month, last_day, 23, 59, 59)
                else:  # Các trường hợp còn lại đều cần sy_info
                    sy_start = _dt.datetime.fromisoformat(sy_info['start_date'] + "T00:00:00")
                    sy_end = _dt.datetime.fromisoformat(sy_info['end_date'] + "T23:59:59")
                    start_dt_py, end_dt_py = sy_start, sy_end

                    if sel == "Toàn năm học":
                        pass
                    elif sel == "Học kỳ 1":
                        hk1_end = _dt.datetime(sy_start.year, 12, 31, 23, 59, 59)
                        end_dt_py = min(hk1_end, sy_end)
                    elif sel == "Học kỳ 2":
                        hk2_year = sy_start.year + 1 if sy_start.month >= 8 else sy_start.year
                        hk2_start = _dt.datetime(hk2_year, 1, 1, 0, 0, 0)
                        start_dt_py = max(hk2_start, sy_start)

                # Đổi Python datetime -> QDateTime (LOCAL), _send_request sẽ chuyển UTC
                local_tz = QTimeZone.systemTimeZone()

                start_qdate = QDate(start_dt_py.year, start_dt_py.month, start_dt_py.day)
                start_qtime = QTime(start_dt_py.hour, start_dt_py.minute, start_dt_py.second)
                start_qdt = QDateTime(start_qdate, start_qtime, local_tz)

                end_qdate = QDate(end_dt_py.year, end_dt_py.month, end_dt_py.day)
                end_qtime = QTime(end_dt_py.hour, end_dt_py.minute, end_dt_py.second)
                end_qdt = QDateTime(end_qdate, end_qtime, local_tz)

                _send_request(start_qdt, end_qdt)

            def on_error(s, e):
                handle_api_error(self, s, e, "Không thể tải danh sách Năm học.")
                # Kể cả khi có lỗi, vẫn thử tải danh sách công việc để tránh màn hình trống
                self.load_file_tasks()
                self.load_data_reports()

            # Lấy danh sách năm học, rồi tính range và gọi tổng hợp
            self.api_get("/school_years/", on_ok, on_error)

    def _fill_school_year_comboboxes(self):
        def on_ok(data, _):
            self.ft_school_year_selector.clear()
            self.dr_school_year_selector.clear()
            self.ft_filter_sy_selector.clear()
            
            self.ft_filter_sy_selector.addItem("Tất cả", None)
            
            for sy in data:
                self.ft_school_year_selector.addItem(sy['name'], sy['id'])
                self.dr_school_year_selector.addItem(sy['name'], sy['id'])
                self.ft_filter_sy_selector.addItem(sy['name'], sy['id'])
            
            self.load_file_tasks()
            self.load_data_reports()

        def on_error(s, e):
            handle_api_error(self, s, e, "Không thể tải danh sách Năm học.")
            self.load_file_tasks()
            self.load_data_reports()

        self.api_get("/school_years/", on_ok, on_error)
        
    def _change_ft_page_size(self):
        self.ft_pager.page_size = int(self.ft_size.currentText())
        self.ft_pager.page = 1
        self.load_file_tasks()

    def _change_dr_page_size(self):
        self.dr_pager.page_size = int(self.dr_size.currentText())
        self.dr_pager.page = 1
        self.load_data_reports()

    def _reload_ft(self):
        self.ft_pager.page = 1
        self.load_file_tasks()

    def _reload_dr(self):
        self.dr_pager.page = 1
        self.load_data_reports()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AdminWindow()
    window.show()
    sys.exit(app.exec())

