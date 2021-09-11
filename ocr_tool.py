import io
import os
import pathlib
import platform
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from threading import Thread
from typing import Optional, cast

import pykakasi
import pyperclip  # type: ignore
import pyscreenshot as ImageGrab
import pytesseract  # type: ignore
import toml
import typer
from appdirs import user_config_dir
from notifypy import Notify  # type: ignore
from PIL import Image, ImageOps
from pynput import keyboard  # type: ignore
from PyQt5.QtCore import QBuffer, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

closed_persistent_window_x1 = 0
closed_persistent_window_y1 = 0
closed_persistent_window_x2 = 0
closed_persistent_window_y2 = 0

default_settings = {
    "hotkeys": {
        "single_screenshot_hotkey": "<ctrl>+<alt>+Q",
        "persistent_window_hotkey": "<ctrl>+<alt>+W",
        "persistent_screenshot_hotkey": "<ctrl>+<alt>+E",
    }
}

global_config_dict = {}


class PersistentWindow(QWidget):
    def __init__(self, x=0, y=0, w=400, h=200, overlay=None):
        super().__init__()
        self.setWindowTitle("Migaku OCR")

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        )

        self.is_resizing = False
        self.is_moving = False

        self.move(x, y)
        self.resize(w, h)
        self.setMouseTracking(True)
        self.original_cursor_x = 0
        self.original_cursor_y = 0
        self.original_window_x = 0
        self.original_window_y = 0
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        innerWidget = QWidget()
        innerWidget.setObjectName("innerWidget")
        innerWidget.setStyleSheet(
            """
                QWidget#innerWidget {
                    border: 2px solid rgba(255, 255, 255, 0.08);

                }
                QWidget#innerWidget::hover {
                    border: 1px solid rgb(255, 255, 255);
                }
            """
        )
        middleWidget = QWidget()
        middleWidget.setObjectName("middleWidget")
        middleWidget.setStyleSheet(
            """
                QWidget#middleWidget {
                    border: 2px solid rgba(0, 0, 0, 0.3);

                }
                QWidget#middleWidget::hover {
                    border: 2px solid rgb(0, 0, 0);
                }
            """
        )
        middleLayout = QHBoxLayout()
        middleWidget.setLayout(middleLayout)
        middleLayout.setContentsMargins(0, 0, 0, 0)
        innerLayout = QHBoxLayout()
        ocrButton = QPushButton()
        ocrButton.setIcon(QIcon("ocr_icon.png"))
        ocrButton.clicked.connect(take_screenshot_from_persistent_window)
        ocrButton.setStyleSheet(
            """
                QPushButton {
                    background-color: white;
                    padding: 0px;
                }
            """
        )

        self.ocrButton = ocrButton
        innerLayout.setContentsMargins(1, 1, 1, 1)
        ocrButton.hide()

        middleLayout.addWidget(innerWidget)
        innerLayout.addWidget(ocrButton, alignment=Qt.AlignRight | Qt.AlignBottom)
        innerWidget.setLayout(innerLayout)
        layout.addWidget(middleWidget)
        self.setLayout(layout)

    def mousePressEvent(self, evt):
        super().mousePressEvent(evt)

        if evt.button() == Qt.LeftButton:
            self.is_moving = True
            cursor_position = QCursor.pos()
            self.original_cursor_x = cursor_position.x()
            self.original_cursor_y = cursor_position.y()
            window_position = self.pos()
            self.original_window_x = window_position.x()
            self.original_window_y = window_position.y()
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)

        if evt.button() == Qt.RightButton:
            self.drag_x = evt.globalX()
            self.drag_y = evt.globalY()
            self.drag_w = self.width()
            self.drag_h = self.height()
            self.is_resizing = True

    def enterEvent(self, event):
        self.ocrButton.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.ocrButton.hide()
        super().leaveEvent(event)

    def mouseMoveEvent(self, evt):
        super().mouseMoveEvent(evt)

        if self.is_moving:
            position = QCursor.pos()
            distance_x = self.original_cursor_x - position.x()
            distance_y = self.original_cursor_y - position.y()
            new_x = self.original_window_x - distance_x
            new_y = self.original_window_y - distance_y
            self.move(new_x, new_y)

        if self.is_resizing:
            w = max(50, self.drag_w + evt.globalX() - self.drag_x)
            h = max(50, self.drag_h + evt.globalY() - self.drag_y)
            self.resize(w, h)
            self.overlay = QPixmap(w, h)
            self.overlay.fill(Qt.transparent)

    def mouseReleaseEvent(self, evt):
        super().mouseReleaseEvent(evt)
        self.is_moving = False
        self.is_resizing = False
        QApplication.restoreOverrideCursor()

    def accept(self):

        self.res_x = self.x()
        self.res_y = self.y()
        self.res_w = self.width()
        self.res_h = self.height()
        self.res_overlay = self.overlay
        super().accept()

    def keyPressEvent(self, evt):

        if evt.key() in [Qt.Key_Return, Qt.Key_Enter]:
            global closed_persistent_window_x1
            global closed_persistent_window_y1
            global closed_persistent_window_x2
            global closed_persistent_window_y2
            closed_persistent_window_x1 = self.x()
            closed_persistent_window_y1 = self.y()
            closed_persistent_window_x2 = closed_persistent_window_x1 + self.width()
            closed_persistent_window_y2 = closed_persistent_window_y1 + self.height()

            self.close()

        if evt.key() in [Qt.Key_Escape]:
            self.close()


typer_app = typer.Typer()


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

persistent_window: Optional[PersistentWindow] = None


@typer_app.command()
def execute_order66(key_combination: Optional[str] = typer.Argument(None)):
    load_config()
    main_hotkey_qobject = MainHotkeyQObject()

    # this allows for ctrl-c to close the application
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    icon = QIcon("migaku_icon.png")

    tray = QSystemTrayIcon()
    tray.setIcon(icon)
    tray.setVisible(True)
    menu = QMenu()

    quit = QAction("Quit")
    quit.triggered.connect(app.quit)
    menu.addAction(quit)

    tray.setContextMenu(menu)

    sys.exit(app.exec_())


def load_config():
    config_dir = user_config_dir("migaku-ocr")
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
    config_file = os.path.join(config_dir, "config.toml")
    global global_config_dict
    try:
        with open(config_file, "r") as f:
            config_text = f.read()
        global_config_dict = toml.loads(config_text)
    except FileNotFoundError:
        print("no config file exists, loading default values")
        global default_settings
        global_config_dict = default_settings


def save_config():
    config_dir = user_config_dir("migaku-ocr")
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
    config_file = os.path.join(config_dir, "config.toml")
    global global_config_dict
    with open(config_file, "w") as f:
        config_text = f.read()
    global_config_dict = toml.loads(config_text)


class MainHotkeyQObject(QObject):
    def __init__(self):
        super().__init__()

        manager = KeyBoardManager(self)
        manager.single_screenshot_signal.connect(take_screenshot)
        manager.persistent_window_signal.connect(show_persistent_screenshot_window)
        manager.persistent_screenshot_signal.connect(
            take_screenshot_from_persistent_window
        )
        manager.start()


class KeyBoardManager(QObject):
    single_screenshot_signal = pyqtSignal()
    persistent_window_signal = pyqtSignal()
    persistent_screenshot_signal = pyqtSignal()

    def start(self):
        global global_config_dict
        hotkey_config = global_config_dict["hotkeys"]
        hotkey_dict = {}
        if hotkey_config["single_screenshot_hotkey"]:
            hotkey_dict[
                hotkey_config["single_screenshot_hotkey"]
            ] = self.single_screenshot_signal.emit
        if hotkey_config["persistent_window_hotkey"]:
            hotkey_dict[
                hotkey_config["persistent_window_hotkey"]
            ] = self.persistent_window_signal.emit
        if hotkey_config["persistent_screenshot_hotkey"]:
            hotkey_dict[
                hotkey_config["persistent_screenshot_hotkey"]
            ] = self.persistent_screenshot_signal.emit

        print(hotkey_dict)
        hotkey = keyboard.GlobalHotKeys(hotkey_dict)
        hotkey.start()


def take_screenshot_from_persistent_window():
    global persistent_window
    global closed_persistent_window_x1
    global closed_persistent_window_y1
    global closed_persistent_window_x2
    global closed_persistent_window_y2
    if not persistent_window and (
        not closed_persistent_window_x1
        and not closed_persistent_window_y1
        and not closed_persistent_window_x2
        and not closed_persistent_window_y2
    ):
        print(
            "persistent window not initialized yet or persistent_window location not saved"
        )
    else:
        if persistent_window:
            x1 = persistent_window.x()
            y1 = persistent_window.y()
            x2 = x1 + persistent_window.width()
            y2 = y1 + persistent_window.height()
        else:
            x1 = closed_persistent_window_x1
            y1 = closed_persistent_window_y1
            x2 = closed_persistent_window_x2
            y2 = closed_persistent_window_y2
        image = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        if persistent_window and persistent_window.ocrButton.isVisible():
            button = persistent_window.ocrButton
            x1 = button.x()
            y1 = button.y()
            width = button.width()
            height = button.height()
            color = image.getpixel((x1 - 1, y1 + height - 2))
            for x in range(width):
                for y in range(height):
                    image.putpixel((x1 + x, y1 + y), color)
        image = ImageOps.grayscale(image)
        image.save("test.png")

        process = Thread(target=start_ocr, args=(image,))
        process.start()


def show_persistent_screenshot_window():
    global persistent_window
    persistent_window = PersistentWindow()
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
    QApplication.restoreOverrideCursor()


def start_ocr(image):
    text = process_image(image)
    process_text(text)


def process_image(image):
    image = ImageOps.grayscale(image)
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

    for (f, t) in [(" ", ""), ("いぃ", "い"), ("\n", "")]:
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
