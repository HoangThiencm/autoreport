# spreadsheet_widget.py
from __future__ import annotations
import csv
import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QToolBar, QFileDialog, QMessageBox,
    QTableView, QApplication, QStyledItemDelegate, QStyle, QComboBox, QSizePolicy, QHeaderView
)
from PySide6.QtGui import QTextDocument, QAbstractTextDocumentLayout, QStandardItemModel, QStandardItem
try:
    import openpyxl
    _XLSX_OK = True
except ImportError:
    _XLSX_OK = False

class WordWrapDelegate(QStyledItemDelegate):
    """
    Một delegate tùy chỉnh để vẽ văn bản trong ô với chức năng tự động xuống dòng (word wrap).
    """
    def paint(self, painter, option, index):
        # Sao chép style option để tùy chỉnh
        options = QStyle.QStyleOptionViewItem(option)
        self.initStyleOption(options, index)

        painter.save()

        # Sử dụng QTextDocument để xử lý việc layout và xuống dòng của văn bản
        doc = QTextDocument()
        doc.setHtml(options.text)
        # Đặt chiều rộng cho văn bản, đây là mấu chốt để tự động xuống dòng
        doc.setTextWidth(options.rect.width()) 

        # Xóa văn bản khỏi option gốc để lớp cha không vẽ lại nó
        options.text = ""
        
        # Vẽ nền, vùng chọn, v.v... của ô bằng lớp cha
        style = options.widget.style() if options.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, options, painter)

        # Thiết lập context để vẽ văn bản
        ctx = QAbstractTextDocumentLayout.PaintContext()

        # Di chuyển painter đến góc trên bên trái của ô
        painter.translate(options.rect.left(), options.rect.top())
        
        # Vẽ văn bản đã được xử lý xuống dòng
        doc.documentLayout().draw(painter, ctx)

        painter.restore()

@dataclass
class ColumnSpec:
    """Định nghĩa một cột trong bảng tính."""
    name: str
    title: str
    dtype: str = "str"
    required: bool = False
    enum: Optional[List[str]] = None
    pattern: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    width: Optional[int] = None
    placeholder: Optional[str] = None

class EnumDelegate(QStyledItemDelegate):
    """Delegate để tạo ComboBox cho các cột có kiểu 'enum'."""
    def __init__(self, options: List[str], parent=None):
        super().__init__(parent)
        self.options = options

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems([""] + self.options)
        return cb

    def setEditorData(self, editor, index):
        val = index.data(Qt.EditRole) or ""
        i = editor.findText(val)
        editor.setCurrentIndex(i if i >= 0 else 0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)

class SpreadsheetWidget(QWidget):
    """Widget bảng tính kiểu Excel với các chức năng validate, copy/paste, import/export."""
    saved = Signal(list)

    def __init__(self, columns: List[ColumnSpec], parent=None, rows: int = 20):
        super().__init__(parent)
        self.columns = columns
        self._invalid_cells: set[tuple[int, int]] = set()
        self._setup_ui(rows)

    def _setup_ui(self, rows: int):
        """
        Thiết lập UI cho bảng tính + thanh công cụ.
        - Giữ nguyên các action hiện có.
        - THÊM nút "Lưu & Nộp" lớn màu xanh để dễ thấy hơn.
        """
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolBar, QPushButton, QSizePolicy, QTableView, QHeaderView
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction, QKeySequence, QStandardItemModel

        # Layout gốc
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        tb = QToolBar("Toolbar")
        act_add = QAction("Thêm dòng", self)
        act_del = QAction("Xóa dòng", self)
        act_copy = QAction("Sao chép", self, shortcut=QKeySequence.Copy)
        act_paste = QAction("Dán", self, shortcut=QKeySequence.Paste)
        act_import_csv = QAction("Nhập CSV", self)
        act_export_csv = QAction("Xuất CSV", self)
        act_export_xlsx = QAction("Xuất XLSX", self)
        act_validate = QAction("Kiểm tra dữ liệu", self)
        self.act_save = QAction("Lưu dữ liệu", self, shortcut=QKeySequence.Save)

        # Nhóm action bên trái
        tb.addAction(act_add); tb.addAction(act_del)
        tb.addSeparator()
        tb.addAction(act_copy); tb.addAction(act_paste)
        tb.addSeparator()
        tb.addAction(act_import_csv); tb.addAction(act_export_csv)

        # Kiểm tra hỗ trợ XLSX (nếu trong module có cờ _XLSX_OK)
        try:
            _XLSX_OK  # noqa: F821
            has_xlsx = bool(_XLSX_OK)
        except Exception:
            has_xlsx = False
        if has_xlsx:
            tb.addAction(act_export_xlsx)

        tb.addSeparator()
        tb.addAction(act_validate)

        # Spacer đẩy phần còn lại sang phải
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # NÚT LƯU LỚN MÀU XANH (nổi bật)
        save_btn = QPushButton("Lưu & Nộp")
        save_btn.setObjectName("primarySaveButton")
        save_btn.setMinimumHeight(44)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            "#primarySaveButton {"
            "  background-color: #16a34a;"
            "  color: white;"
            "  font-weight: 600;"
            "  padding: 8px 16px;"
            "  border-radius: 10px;"
            "}"
            "#primarySaveButton:hover { background-color: #15803d; }"
            "#primarySaveButton:pressed { background-color: #166534; }"
            "#primarySaveButton:disabled { background-color: #9ca3af; }"
        )
        tb.addWidget(save_btn)

        # Đặt toolbar lên layout
        layout.addWidget(tb)

        # Bảng + model
        self.view = QTableView(self)
        self.model = QStandardItemModel(0, len(self.columns), self)
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.view.setSelectionMode(QTableView.SelectionMode.ContiguousSelection)
        self.view.verticalHeader().setDefaultSectionSize(42)

        # Cho phép người dùng tự chỉnh độ rộng cột
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        layout.addWidget(self.view)

        # Tiêu đề cột + độ rộng mặc định (nếu có)
        for c, col in enumerate(self.columns):
            self.model.setHeaderData(c, Qt.Horizontal, col.title)
            if getattr(col, "width", None):
                self.view.setColumnWidth(c, col.width)

        # Khởi tạo số dòng ban đầu
        self.add_rows(rows, clear=False)

        # Delegate kiểu liệt kê cho cột enum (nếu có)
        for c, col in enumerate(self.columns):
            if getattr(col, "dtype", None) == "enum" and getattr(col, "enum", None):
                self.view.setItemDelegateForColumn(c, EnumDelegate(col.enum, self))

        # Kết nối hành động
        # === DÒNG ĐÃ SỬA LỖI ===
        act_add.triggered.connect(lambda: self.add_rows()) # Sửa lỗi không thêm được dòng
        # =======================
        act_del.triggered.connect(self.delete_selected_rows)
        act_copy.triggered.connect(self.copy_selection)
        act_paste.triggered.connect(self.paste_from_clipboard)
        act_import_csv.triggered.connect(self.import_csv)
        act_export_csv.triggered.connect(self.export_csv)
        if has_xlsx:
            act_export_xlsx.triggered.connect(self.export_xlsx)
        act_validate.triggered.connect(self.validate_all)

        # Giữ phím tắt Ctrl+S hoạt động (không cần hiện action nhỏ trên toolbar)
        self.addAction(self.act_save)
        self.act_save.triggered.connect(self._emit_save)

        # Nút lớn màu xanh -> lưu & nộp
        save_btn.clicked.connect(self._emit_save)
         
    def set_data(self, rows: List[Dict[str, Any]]):
        self.model.blockSignals(True)
        self.model.setRowCount(0)
        self.add_rows(len(rows) or 20, clear=True)
        for r, row_data in enumerate(rows):
            for c, col in enumerate(self.columns):
                val = row_data.get(col.name, "")
                it = self.model.item(r, c)
                if it:
                    it.setText("" if val is None else str(val))
        self.model.blockSignals(False)
        self.validate_all()

    def to_records(self) -> List[Dict[str, Any]]:
        out = []
        for r in range(self.model.rowCount()):
            row_data = {}
            is_empty_row = True
            for c, col in enumerate(self.columns):
                raw = self.model.item(r, c)
                v_str = (raw.text() if raw else "").strip()
                if v_str:
                    is_empty_row = False
                row_data[col.name] = self._coerce_value(v_str, col)
            if not is_empty_row:
                out.append(row_data)
        return out

    def _on_item_changed(self, item: QStandardItem):
        r, c = item.row(), item.column()
        col = self.columns[c]
        ok, tooltip = self._validate_value(item.text().strip(), col)
        self._mark_cell(r, c, ok, tooltip)

    def validate_all(self) -> bool:
        self._invalid_cells.clear()
        for r in range(self.model.rowCount()):
            for c, col in enumerate(self.columns):
                it = self.model.item(r, c)
                txt = (it.text() if it else "").strip()
                ok, tooltip = self._validate_value(txt, col)
                self._mark_cell(r, c, ok, tooltip)
        
        if self._invalid_cells:
            QMessageBox.warning(self, "Kiểm tra dữ liệu", f"Có {len(self._invalid_cells)} ô chưa hợp lệ (được tô màu).")
            return False
        return True

    def _mark_cell(self, r: int, c: int, ok: bool, tooltip: str = ""):
        it = self.model.item(r, c)
        if not it: return
        
        valid_color = self.palette().color(self.backgroundRole())
        invalid_color = QColor("#fff0f1")

        if ok:
            if (r, c) in self._invalid_cells: self._invalid_cells.remove((r, c))
            it.setBackground(valid_color)
            it.setToolTip("")
        else:
            self._invalid_cells.add((r, c))
            it.setBackground(invalid_color)
            it.setToolTip(tooltip or "Giá trị không hợp lệ")

    def _validate_value(self, s: str, col: ColumnSpec) -> tuple[bool, str]:
        if not s: return (False, "Ô này là bắt buộc.") if col.required else (True, "")
        if col.dtype == "int":
            try:
                v = int(s)
                if col.min is not None and v < col.min: return False, f"Giá trị phải >= {col.min}"
                if col.max is not None and v > col.max: return False, f"Giá trị phải <= {col.max}"
            except ValueError: return False, "Phải là một số nguyên."
        elif col.dtype == "float":
            try:
                v = float(s.replace(",", "."))
                if col.min is not None and v < col.min: return False, f"Giá trị phải >= {col.min}"
                if col.max is not None and v > col.max: return False, f"Giá trị phải <= {col.max}"
            except ValueError: return False, "Phải là một số thực."
        elif col.dtype == "date":
            if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) or re.fullmatch(r"\d{2}/\d{2}/\d{4}", s)):
                return False, "Định dạng ngày là YYYY-MM-DD hoặc DD/MM/YYYY."
        elif col.dtype == "enum":
            if col.enum and s not in col.enum: return False, "Vui lòng chọn một giá trị từ danh sách."
        if col.pattern and not re.fullmatch(col.pattern, s): return False, f"Không khớp mẫu: {col.pattern}"
        return True, ""

    def _coerce_value(self, s: str, col: ColumnSpec) -> Any:
        if s == "": return None
        try:
            if col.dtype == "int": return int(s)
            if col.dtype == "float": return float(s.replace(",", "."))
            if col.dtype == "date":
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
                    d, m, y = s.split("/")
                    return f"{y}-{m}-{d}"
                return s
        except (ValueError, TypeError): return s
        return s

    def add_rows(self, n: int = 1, clear: bool = False):
        if clear: self.model.setRowCount(0)
        r0 = self.model.rowCount()
        self.model.insertRows(r0, n)
        for r in range(r0, r0 + n):
            for c, col in enumerate(self.columns):
                it = QStandardItem("")
                it.setEditable(True)
                # SỬA 2: Xóa setPlaceholderText vì QStandardItem không có
                self.model.setItem(r, c, it)
    
    def delete_selected_rows(self):
        sel = self.view.selectionModel().selectedIndexes()
        if not sel: return
        rows = sorted({i.row() for i in sel}, reverse=True)
        for r in rows: self.model.removeRow(r)

    # SỬA 3: Copy theo khối chữ nhật kiểu Excel
    def copy_selection(self):
        sel = self.view.selectionModel().selectedIndexes()
        if not sel: return
        
        # Sắp xếp các ô đã chọn để tìm ra góc trên-trái và dưới-phải
        sel = sorted(sel, key=lambda i: (i.row(), i.column()))
        r0, c0 = sel[0].row(), sel[0].column()
        r1, c1 = sel[-1].row(), sel[-1].column()

        buf = io.StringIO()
        wr = csv.writer(buf, delimiter="\t", lineterminator="\n")
        
        # Lặp qua toàn bộ khối chữ nhật
        for r in range(r0, r1 + 1):
            row_data = []
            for c in range(c0, c1 + 1):
                it = self.model.item(r, c)
                row_data.append("" if it is None else it.text())
            wr.writerow(row_data)
            
        QApplication.clipboard().setText(buf.getvalue())

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if not text: return
        start_index = self.view.currentIndex()
        if not start_index.isValid(): start_index = self.model.index(0, 0)
        r0, c0 = start_index.row(), start_index.column()
        lines = [row for row in text.splitlines() if row] # Bỏ qua dòng trống
        
        if not lines: return

        # Tính toán số dòng và cột cần thiết
        num_paste_rows = len(lines)
        num_paste_cols = max(len(line.split("\t")) for line in lines)

        needed_rows = r0 + num_paste_rows - self.model.rowCount()
        if needed_rows > 0: self.add_rows(needed_rows)

        # Dán dữ liệu
        self.model.blockSignals(True)
        for i, line in enumerate(lines):
            values = line.split("\t")
            for j, value in enumerate(values):
                r, c = r0 + i, c0 + j
                if c < self.model.columnCount():
                    it = self.model.item(r, c)
                    if it:
                        it.setText(value.strip())
        self.model.blockSignals(False)
        self.validate_all()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file CSV", "", "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                # Đọc toàn bộ file vào list để xử lý header linh hoạt hơn
                data = list(csv.reader(f))
        except Exception as e:
            QMessageBox.critical(self, "Lỗi đọc file", f"Không thể đọc file CSV: {e}")
            return
        
        if not data: return
        
        # Kiểm tra header có khớp với title cột không
        header = [h.strip() for h in data[0]]
        col_titles = [c.title for c in self.columns]
        
        records_to_load = data
        if header == col_titles:
            # Nếu header khớp, bỏ qua dòng header
            records_to_load = data[1:]

        # Chuyển đổi dữ liệu sang list of dicts
        dict_data = [dict(zip([c.name for c in self.columns], row)) for row in records_to_load]
        self.set_data(dict_data)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Lưu file CSV", "", "CSV Files (*.csv)")
        if not path: return
        
        if self.validate_all() is False:
            if QMessageBox.question(self, "Dữ liệu chưa hợp lệ", "Vẫn còn lỗi. Bạn có muốn tiếp tục xuất file không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.No:
                return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([c.title for c in self.columns])
                records = self.to_records()
                for rec in records:
                    writer.writerow([rec.get(c.name, "") for c in self.columns])
            QMessageBox.information(self, "Thành công", "Đã xuất file CSV thành công.")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi ghi file", f"Không thể lưu file CSV: {e}")

    def export_xlsx(self):
        if not _XLSX_OK:
            QMessageBox.warning(self, "Thiếu thư viện", "Vui lòng cài 'openpyxl' để dùng chức năng này.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu file Excel", "", "Excel Files (*.xlsx)")
        if not path: return

        if self.validate_all() is False:
            if QMessageBox.question(self, "Dữ liệu chưa hợp lệ", "Vẫn còn lỗi. Bạn có muốn tiếp tục xuất file không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.No:
                return

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Data"
            ws.append([c.title for c in self.columns])
            records = self.to_records()
            for rec in records:
                # Đảm bảo giá trị là kiểu phù hợp cho Excel
                row_to_write = []
                for c in self.columns:
                    val = rec.get(c.name)
                    if val is None:
                        row_to_write.append("")
                    else:
                        row_to_write.append(val)
                ws.append(row_to_write)

            wb.save(path)
            QMessageBox.information(self, "Thành công", "Đã xuất file Excel thành công.")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi ghi file", f"Không thể lưu file Excel: {e}")

    def _emit_save(self):
        if self.validate_all():
            self.saved.emit(self.to_records())
        else:
            ret = QMessageBox.question(self, "Dữ liệu chưa hợp lệ", "Vẫn còn lỗi. Bạn có chắc muốn lưu không?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes: self.saved.emit(self.to_records())

