import io
import os
import platform
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from threading import Thread
from typing import Optional, cast

import pykakasi
import pyperclip  # type: ignore
import pytesseract  # type: ignore
import typer
from notifypy import Notify  # type: ignore
from PIL import Image
from pynput import keyboard  # type: ignore
from PyQt5.QtCore import QBuffer, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PyQt5.QtWidgets import QApplication, QDialog, QGridLayout, QLabel, QWidget

from giant_mess.vncards import OcrAreaDlg

typer_app = typer.Typer()


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
persistent_window: Optional[OcrAreaDlg] = None


@typer_app.command()
def execute_order66(key_combination: Optional[str] = typer.Argument(None)):
    main_hotkey_qobject = MainHotkeyQObject()
    # this allows for ctrl-c to close the application
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec_())


class MainHotkeyQObject(QObject):
    def __init__(self):
        super().__init__()

        manager = KeyBoardManager(self)
        manager.single_screenshot_signal.connect(take_screenshot)
        manager.persistent_screenshot_signal.connect(persistent_screenshot_window)
        manager.start()


class KeyBoardManager(QObject):
    single_screenshot_signal = pyqtSignal()
    persistent_screenshot_signal = pyqtSignal()

    def start(self):
        hotkey = keyboard.GlobalHotKeys(
            {
                "<ctrl>+<alt>+1": self.single_screenshot_signal.emit,
                "<ctrl>+<alt>+2": self.persistent_screenshot_signal.emit,
            },
        )
        hotkey.start()


def persistent_screenshot_window():
    print("persistent start")

    class OcrAreaDlg(QWidget):
        def __init__(self, x=0, y=0, w=400, h=200, overlay=None):
            super().__init__()
            self.setStyleSheet("background:transparent;")
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
            )

            self.is_resizing = False

            self.move(x, y)
            self.resize(w, h)

            if overlay is None:
                self.overlay = QPixmap(w, h)
                self.overlay.fill(Qt.transparent)
            else:
                self.overlay = overlay

        def mousePressEvent(self, evt):
            super().mousePressEvent(evt)

            if evt.button() == Qt.RightButton:
                self.drag_x = evt.globalX()
                self.drag_y = evt.globalY()
                self.drag_w = self.width()
                self.drag_h = self.height()
                self.is_resizing = True

        def mouseMoveEvent(self, evt):
            super().mouseMoveEvent(evt)

            if self.is_resizing:
                w = max(50, self.drag_w + evt.globalX() - self.drag_x)
                h = max(50, self.drag_h + evt.globalY() - self.drag_y)
                self.resize(w, h)
                self.overlay = QPixmap(w, h)
                self.overlay.fill(Qt.transparent)

        def mouseReleaseEvent(self, evt):
            super().mouseReleaseEvent(evt)

            self.is_resizing = False

        def accept(self):

            self.res_x = self.x()
            self.res_y = self.y()
            self.res_w = self.width()
            self.res_h = self.height()
            self.res_overlay = self.overlay
            super().accept()

        def keyPressEvent(self, evt):

            # if evt.key() in [Qt.Key_Return, Qt.Key_Enter]:
            #     self.accept()

            if evt.key() in [Qt.Key_Escape]:
                self.close()

    global persistent_window
    persistent_window = OcrAreaDlg()
    persistent_window.show()


def take_screenshot():
    QApplication.setOverrideCursor(Qt.CrossCursor)
    ex = SelectorWidget(app)
    ex.show()
    ex.activateWindow()
    if ex.exec() == QDialog.Accepted:
        if ex.selectedPixmap:
            image = convert_qpixmap_to_pil_image(ex.selectedPixmap)
            process = Thread(target=start_ocr, args=(image,))
            process.start()


def start_ocr(image):
    text = process_image(image)
    process_text(text)


def process_image(image):
    # image = ImageOps.grayscale(image)
    width, height = image.size
    language = ""
    if platform.system() == "Windows":
        path = os.path.abspath("tesseract/tesseract.exe")
        pytesseract.pytesseract.tesseract_cmd = path
    if width > height:
        language = "jpn"
        tesseract_config = "--oem 1 --psm 6"
    else:
        language = "jpn_vert"
        tesseract_config = "--oem 1 --psm 5"
    text = pytesseract.image_to_string(image, lang=language, config=tesseract_config)
    text = cast(str, text)
    text = text.strip()

    for (f, t) in [(" ", ""), ("いぃ", "い")]:
        text = text.replace(f, t)
    print(text)
    return text


def process_text(text: str):
    if text:
        pyperclip.copy(text)
        with ThreadPoolExecutor() as executor:
            hiragana_thread = executor.submit(convert_to_hiragana, text)
            hiragana = hiragana_thread.result(7)

            final_text = f"{hiragana}"

            notification = Notify()
            notification.title = text
            notification.message = final_text
            notification.icon = ""
            notification.send(block=False)


def grab_screenshot(app: QApplication):
    desktop_pixmap = QPixmap(QApplication.desktop().size())
    painter = QPainter(desktop_pixmap)
    for screen in app.screens():
        painter.drawPixmap(  # type: ignore
            screen.geometry().topLeft(),
            screen.grabWindow(0),  # type: ignore
        )
    return desktop_pixmap


class SelectorWidget(QDialog):
    def __init__(self, app: QApplication):
        # super(Qt.FramelessWindowHint, self).__init__()
        super(SelectorWidget, self).__init__()
        if platform.system() == "Linux":
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.X11BypassWindowManagerHint  # type: ignore
            )
        elif platform.system() == "Windows":
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool  # type: ignore
            )
        elif platform.system() == "Darwin":
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowFullscreenButtonHint  # type: ignore
            )

        self.setGeometry(QApplication.desktop().geometry())
        self.desktopPixmap = grab_screenshot(app)
        label = QLabel()
        label.setPixmap(self.desktopPixmap)
        self.grid = QGridLayout()
        self.grid.addWidget(label, 1, 1)
        self.selectedRect = QRect()
        self.selectedPixmap = None

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key_Escape]:
            self.reject()

    def mousePressEvent(self, event: QMouseEvent):
        self.selectedRect.setTopLeft(event.globalPos())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.selectedRect.setBottomRight(event.globalPos())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.selectedPixmap = self.desktopPixmap.copy(self.selectedRect.normalized())
        self.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.desktopPixmap)
        path = QPainterPath()
        painter.fillPath(path, QColor.fromRgb(255, 255, 255, 200))
        painter.setPen(Qt.red)
        painter.drawRect(self.selectedRect)


def convert_qpixmap_to_pil_image(pixmap: QPixmap):
    q_image = pixmap.toImage()
    buffer = QBuffer()
    buffer.open(QBuffer.ReadWrite)
    q_image.save(buffer, "PNG")
    return Image.open(io.BytesIO(buffer.data()))


def convert_to_hiragana(text):
    kks = pykakasi.kakasi()
    result = kks.convert(text)
    result_str = ""
    for item in result:
        result_str += item["hira"]
    return result_str


if __name__ == "__main__":
    typer_app()
