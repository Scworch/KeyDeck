import sys
import math
import psutil
import ctypes
from PyQt6 import QtWidgets, QtCore, QtGui

user32 = ctypes.windll.user32

class ProgressButton(QtWidgets.QPushButton):
    progressChanged = QtCore.pyqtSignal(float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress = 1.0

    def getProgress(self):
        return self._progress

    def setProgress(self, value: float):
        self._progress = max(0.0, min(1.0, value))
        self.update()
        self.progressChanged.emit(self._progress)

    progress = QtCore.pyqtProperty(float, fget=getProgress, fset=setProgress)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        rect = self.rect()
        fill_w = rect.width() * self._progress
        painter.fillRect(
            QtCore.QRectF(rect.x(), rect.y(), fill_w, rect.height()),
            QtGui.QColor(0, 180, 0, 180)
        )
        painter.end()
        super().paintEvent(event)

class GTAFreezerMinimal(QtWidgets.QWidget):
    TOTAL_SECONDS = 8

    def __init__(self):
        super().__init__()
        self.is_running = False
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.init_ui()

    def init_ui(self):
        btn_size = QtCore.QSize(280, 80)
        self.setFixedSize(btn_size)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        self.freeze_button = ProgressButton("Очистить сессию")
        self.freeze_button.setFixedSize(btn_size)
        font = QtGui.QFont()
        font.setPointSize(12)
        self.freeze_button.setFont(font)

        self.freeze_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover, QPushButton:pressed, QPushButton:checked {
                background: transparent;
            }
        """)

        self.freeze_button.clicked.connect(self.freeze_gta)
        layout.addWidget(self.freeze_button)

    def find_gta_process(self):
        for proc in psutil.process_iter(['pid','name']):
            if proc.info['name'] == 'GTA5_Enhanced.exe':
                return psutil.Process(proc.info['pid'])
        return None

    def focus_gta_window(self, pid):
        hwnds = []
        def cb(hwnd, _):
            tid, cur = ctypes.c_ulong(), ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(cur))
            if user32.IsWindowVisible(hwnd) and cur.value == pid:
                hwnds.append(hwnd)
            return True
        WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUM(cb), 0)
        if hwnds:
            user32.ShowWindow(hwnds[0], 9)
            user32.SetForegroundWindow(hwnds[0])

    def freeze_gta(self):
        if self.is_running:
            return
        self.is_running = True

        self.gta_proc = self.find_gta_process()
        if not self.gta_proc:
            self.freeze_button.setText("GTA5_Enhanced.exe не найден")
            return

        self.freeze_button.setText("Очистка сессии...")
        QtCore.QCoreApplication.processEvents()
        try:
            self.gta_proc.suspend()
        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            self.freeze_button.setText(f"Ошибка: {e}")
            return

        QtCore.QTimer.singleShot(500, self.start_animation)

    def start_animation(self):
        self.anim = QtCore.QPropertyAnimation(self.freeze_button, b"progress", self)
        self.anim.setDuration(self.TOTAL_SECONDS * 1000)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.freeze_button.progressChanged.connect(self.update_text)
        self.anim.finished.connect(self.finish_freeze)
        self.anim.start()

    def update_text(self, progress: float):
        secs = max(0, math.ceil(progress * self.TOTAL_SECONDS))
        self.freeze_button.setText(f"{secs} сек")

    def finish_freeze(self):
        try:
            self.gta_proc.resume()
        except Exception:
            pass
        self.freeze_button.setText("Готово!")
        self.freeze_button.setProgress(0.0)
        QtCore.QTimer.singleShot(500, self.focus_and_close)

    def focus_and_close(self):
        self.focus_gta_window(self.gta_proc.pid)
        self.close()

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = GTAFreezerMinimal()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
