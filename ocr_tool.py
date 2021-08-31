import io
import os
import platform
from concurrent.futures.thread import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import Optional, cast

import pykakasi
import pyperclip  # type: ignore
import pytesseract  # type: ignore
import typer
from notifypy import Notify  # type: ignore
from PIL import Image
from pynput import keyboard  # type: ignore
from PyQt5.QtCore import QBuffer, QRect, Qt
from PyQt5.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PyQt5.QtWidgets import QApplication, QDialog, QGridLayout, QLabel

typer_app = typer.Typer()

deepl_api_key = ""
app = QApplication([])
enclosure_queue: Queue = Queue()


@typer_app.command()
def execute_order66(
    key_combination: Optional[str] = typer.Argument(None),
    deepl_api_key_parameter: Optional[str] = typer.Argument(None),
):
    global deepl_api_key
    if type(deepl_api_key_parameter) == str:
        deepl_api_key = deepl_api_key_parameter
    hotkey: Optional[keyboard.GlobalHotKeys] = None
    if not key_combination:
        hotkey = keyboard.GlobalHotKeys({"<ctrl>+<alt>+1": on_activate_h})
    if hotkey:
        hotkey.start()

    process_queue(enclosure_queue)


def process_queue(queue):
    while True:
        print("queue:" + queue.get())
        take_screenshot()
        queue.task_done()


def take_screenshot():
    QApplication.setOverrideCursor(Qt.CrossCursor)
    ex = SelectorWidget(app)
    ex.show()
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
        if event.key() == Qt.Key_Escape:
            self.close()

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


def on_activate_h():
    print("got hotkey")
    enclosure_queue.put("stub")


if __name__ == "__main__":
    typer_app()
