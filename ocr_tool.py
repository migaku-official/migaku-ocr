import copy
import io
import os
import pathlib
import platform
import re
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from threading import Thread
from typing import Any, Optional, cast

import pykakasi
import pyperclip  # type: ignore
import pyscreenshot as ImageGrab
import pytesseract  # type: ignore
import toml
import typer
from appdirs import user_config_dir  # type: ignore
from notifypy import Notify  # type: ignore
from PIL import Image, ImageOps
from pynput import keyboard  # type: ignore
from PyQt5.QtCore import QBuffer, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QIcon, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    },
    "enable_global_hotkeys": False,
    "ocr_settings": {"grayscale": False},
}

global_config_dict: dict[str, Any] = {}

key_dict = {
    Qt.Key_0: "0",
    Qt.Key_1: "1",
    Qt.Key_2: "2",
    Qt.Key_3: "3",
    Qt.Key_4: "4",
    Qt.Key_5: "5",
    Qt.Key_6: "6",
    Qt.Key_7: "7",
    Qt.Key_8: "8",
    Qt.Key_9: "9",
    Qt.Key_Escape: "ESCAPE",
    Qt.Key_Backspace: "BACKSPACE",
    Qt.Key_Return: "RETURN",
    Qt.Key_Enter: "ENTER",
    Qt.Key_Insert: "INS",
    Qt.Key_Delete: "DEL",
    Qt.Key_Pause: "PAUSE",
    Qt.Key_Print: "PRINT",
    Qt.Key_Home: "HOME",
    Qt.Key_End: "END",
    Qt.Key_Left: "LEFT",
    Qt.Key_Up: "UP",
    Qt.Key_Right: "RIGHT",
    Qt.Key_Down: "DOWN",
    Qt.Key_PageUp: "PGUP",
    Qt.Key_PageDown: "PGDOWN",
    Qt.Key_Comma: ",",
    Qt.Key_Underscore: "_",
    Qt.Key_Minus: "-",
    Qt.Key_Period: ".",
    Qt.Key_Slash: "/",
    Qt.Key_Colon: ":",
    Qt.Key_Semicolon: ";",
    Qt.Key_F1: "F1",
    Qt.Key_F2: "F2",
    Qt.Key_F3: "F3",
    Qt.Key_F4: "F4",
    Qt.Key_F5: "F5",
    Qt.Key_F6: "F6",
    Qt.Key_F7: "F7",
    Qt.Key_F8: "F8",
    Qt.Key_F9: "F9",
    Qt.Key_F10: "F10",
    Qt.Key_F11: "F11",
    Qt.Key_F12: "F12",
    Qt.Key_A: "A",
    Qt.Key_B: "B",
    Qt.Key_C: "C",
    Qt.Key_D: "D",
    Qt.Key_E: "E",
    Qt.Key_F: "F",
    Qt.Key_G: "G",
    Qt.Key_H: "H",
    Qt.Key_I: "I",
    Qt.Key_J: "J",
    Qt.Key_K: "K",
    Qt.Key_L: "L",
    Qt.Key_M: "M",
    Qt.Key_N: "N",
    Qt.Key_O: "O",
    Qt.Key_P: "P",
    Qt.Key_Q: "Q",
    Qt.Key_R: "R",
    Qt.Key_S: "S",
    Qt.Key_T: "T",
    Qt.Key_U: "U",
    Qt.Key_V: "V",
    Qt.Key_W: "W",
    Qt.Key_X: "X",
    Qt.Key_Y: "Y",
    Qt.Key_Z: "Z",
}


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Migaku OCR")
        self.setWindowFlags(Qt.Dialog)

        def add_main_window_buttons():
            selection_ocr_button = QPushButton("Selection OCR")
            selection_ocr_button.clicked.connect(take_single_screenshot)

            show_persistent_window_button = QPushButton("Show Persistent Window")
            show_persistent_window_button.clicked.connect(show_persistent_screenshot_window)

            persistent_window_ocr_button = QPushButton("Persistent Window OCR")
            persistent_window_ocr_button.setIcon(QIcon("ocr_icon.png"))
            persistent_window_ocr_button.clicked.connect(take_screenshot_from_persistent_window)

            hotkey_config_button = QPushButton("Configure Hotkeys")
            hotkey_config_button.clicked.connect(show_hotkey_config)

            layout = QVBoxLayout()
            layout.addWidget(selection_ocr_button)
            layout.addWidget(show_persistent_window_button)
            layout.addWidget(persistent_window_ocr_button)
            layout.addWidget(hotkey_config_button)
            self.setLayout(layout)

        add_main_window_buttons()


def show_hotkey_config():
    global hotkey_window
    hotkey_window = HotKeySettingsWindow()
    hotkey_window.show()


class HotKeySettingsWindow(QWidget):
    def __init__(self):
        super().__init__()

        global main_hotkey_qobject
        try:
            main_hotkey_qobject.manager.hotkey.stop()
        except AttributeError:
            pass

        self.original_config = copy.deepcopy(global_config_dict)

        self.setWindowTitle("Migaku OCR Hotkey Settings")
        self.setWindowFlags(Qt.Dialog)
        layout = QVBoxLayout()

        self.hotkeyCheckBox = QCheckBox("Enable Global Hotkeys")
        self.hotkeyCheckBox.setChecked(global_config_dict["enable_global_hotkeys"])
        self.hotkeyCheckBox.stateChanged.connect(self.checkboxToggl)

        layout.addWidget(self.hotkeyCheckBox)
        singleScreenshotHotkeyField = HotKeyField("single_screenshot_hotkey", "Single screenshot OCR")
        layout.addWidget(singleScreenshotHotkeyField)
        persistentWindowHotkeyField = HotKeyField("persistent_window_hotkey", "Spawn persistent window")
        layout.addWidget(persistentWindowHotkeyField)
        persistentScreenshotHotkeyField = HotKeyField("persistent_screenshot_hotkey", "Persistent window OCR")
        layout.addWidget(persistentScreenshotHotkeyField)

        buttonLayout = QHBoxLayout()
        layout.addLayout(buttonLayout)
        self.okButton = QPushButton("OK")
        self.okButton.clicked.connect(self.saveClose)
        buttonLayout.addWidget(self.okButton)
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.cancelClose)
        buttonLayout.addWidget(self.cancelButton)
        self.setLayout(layout)

    def checkboxToggl(self, state):
        global_config_dict["enable_global_hotkeys"] = True if state == Qt.Checked else False

    def saveClose(self):
        save_config()
        self.close()

    def cancelClose(self):
        global global_config_dict
        global_config_dict = self.original_config
        self.close()

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)

        global main_hotkey_qobject
        main_hotkey_qobject = MainHotkeyQObject()


class HotKeyField(QWidget):
    def __init__(self, hotkey_functionality: str, hotkey_name: str):
        super().__init__()
        hotkey_label = QLabel(hotkey_name)
        layout = QHBoxLayout()
        layout.addWidget(hotkey_label)

        self.keyEdit = KeySequenceLineEdit(hotkey_functionality)
        layout.addWidget(self.keyEdit)

        self.clearButton = QPushButton("Clear")
        self.clearButton.clicked.connect(self.keyEdit.clear)
        layout.addWidget(self.clearButton)

        self.setLayout(layout)


class KeySequenceLineEdit(QLineEdit):
    def __init__(self, hotkey_functionality: str):
        super().__init__()
        self.modifiers: Qt.KeyboardModifiers = Qt.NoModifier
        self.key: Qt.Key = Qt.Key_unknown
        self.keysequence = QKeySequence()
        self.hotkey_functionality = hotkey_functionality
        self.setText(self.getQtText(global_config_dict["hotkeys"][self.hotkey_functionality]))

    def clear(self):
        self.setText("")
        global_config_dict["hotkeys"][self.hotkey_functionality] = ""

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.modifiers = event.modifiers()
        self.key = event.key()
        self.updateKeySequence()
        self.updateConfig()

    def updateConfig(self):
        global_config_dict["hotkeys"][self.hotkey_functionality] = self.getPynputText()

    def updateKeySequence(self):
        self.keysequence = (
            QKeySequence(self.modifiers) if self.key not in key_dict else QKeySequence(self.modifiers | self.key)
        )
        self.updateText()

    def updateText(self):
        self.setText(self.keysequence.toString())

    def getPynputText(self):
        def upper_repl(match):
            return match.group(1).upper()

        qt_string: str = self.keysequence.toString()
        tmp = qt_string.lower()
        tmp = re.sub(r"shift\+(\w)", upper_repl, tmp)
        tmp = re.sub(r"(f\d{1,2})", r"<\1>", tmp)
        tmp = tmp.replace("ctrl", "<ctrl>")
        tmp = tmp.replace("alt", "<alt>")
        tmp = tmp.replace("meta", "<cmd>")
        return tmp

    def getQtText(self, pynputText):
        tmp = re.sub(r"([A-Z])", lambda match: "Shift+" + match.group(1).lower(), pynputText)
        tmp = re.sub(r"<f(\d{1,2})>", r"F\1", tmp)
        tmp = re.sub(r"([a-z])$", lambda match: match.group(1).upper(), tmp)
        tmp = tmp.replace("<ctrl>", "Ctrl")
        tmp = tmp.replace("<alt>", "Alt")
        tmp = tmp.replace("<cmd>", "Meta")
        return tmp


class PersistentWindow(QWidget):
    def __init__(self, x=0, y=0, w=400, h=200):
        super().__init__()
        self.setWindowTitle("Migaku OCR")

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)

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
                    border: 1px solid rgba(255, 255, 255, 0.08);

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
                    border: 1px solid rgba(0, 0, 0, 0.3);

                }
                QWidget#middleWidget::hover {
                    border: 1px solid rgb(0, 0, 0);
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

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

        if event.button() == Qt.LeftButton:
            self.is_moving = True
            cursor_position = QCursor.pos()
            self.original_cursor_x = cursor_position.x()
            self.original_cursor_y = cursor_position.y()
            window_position = self.pos()
            self.original_window_x = window_position.x()
            self.original_window_y = window_position.y()
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)

        if event.button() == Qt.RightButton:
            self.drag_x = event.globalX()
            self.drag_y = event.globalY()
            self.drag_w = self.width()
            self.drag_h = self.height()
            self.is_resizing = True

    def enterEvent(self, event):
        self.ocrButton.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.ocrButton.hide()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

        if self.is_moving:

            def make_window_follow_cursor():
                position = QCursor.pos()
                distance_x = self.original_cursor_x - position.x()
                distance_y = self.original_cursor_y - position.y()
                new_x = self.original_window_x - distance_x
                new_y = self.original_window_y - distance_y
                self.move(new_x, new_y)

            make_window_follow_cursor()

        if self.is_resizing:

            def make_size_follow_cursor():
                w = max(50, self.drag_w + event.globalX() - self.drag_x)
                h = max(50, self.drag_h + event.globalY() - self.drag_y)
                self.resize(w, h)
                self.overlay = QPixmap(w, h)
                self.overlay.fill(Qt.transparent)

            make_size_follow_cursor()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.is_moving = False
        self.is_resizing = False
        QApplication.restoreOverrideCursor()

    def keyPressEvent(self, event):

        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            global closed_persistent_window_x1
            global closed_persistent_window_y1
            global closed_persistent_window_x2
            global closed_persistent_window_y2
            closed_persistent_window_x1 = self.x()
            closed_persistent_window_y1 = self.y()
            closed_persistent_window_x2 = closed_persistent_window_x1 + self.width()
            closed_persistent_window_y2 = closed_persistent_window_y1 + self.height()

            self.close()

        if event.key() in [Qt.Key_Escape]:
            self.close()


typer_app = typer.Typer()


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

persistent_window: Optional[PersistentWindow] = None


@typer_app.command()
def execute_order66(key_combination: Optional[str] = typer.Argument(None)):
    load_config()
    global main_hotkey_qobject
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

    openMain = QAction("Open Migaku OCR Main Window")
    openMain.triggered.connect(show_main_window)
    quit = QAction("Quit")
    quit.triggered.connect(app.quit)

    menu.addAction(openMain)
    menu.addAction(quit)

    tray.setContextMenu(menu)

    show_main_window()

    sys.exit(app.exec_())


def show_main_window():
    global main_window
    main_window = MainWindow()
    main_window.show()


def load_config():
    config_dir = user_config_dir("migaku-ocr")
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
    config_file = os.path.join(config_dir, "config.toml")
    global global_config_dict
    global_config_dict = default_settings
    try:
        with open(config_file, "r") as f:
            config_text = f.read()
        # merge default config and user config, user config has precedence; python3.9+ only
        global_config_dict = global_config_dict | toml.loads(config_text)
    except FileNotFoundError:
        print("no config file exists, loading default values")


def save_config():
    config_dir = user_config_dir("migaku-ocr")
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
    config_file = os.path.join(config_dir, "config.toml")
    global global_config_dict
    with open(config_file, "w") as f:
        toml.dump(global_config_dict, f)


class MainHotkeyQObject(QObject):
    def __init__(self):
        super().__init__()

        if global_config_dict["enable_global_hotkeys"]:
            self.manager = KeyBoardManager(self)
            self.manager.single_screenshot_signal.connect(take_single_screenshot)
            self.manager.persistent_window_signal.connect(show_persistent_screenshot_window)
            self.manager.persistent_screenshot_signal.connect(take_screenshot_from_persistent_window)
            self.manager.start()


class KeyBoardManager(QObject):
    single_screenshot_signal = pyqtSignal()
    persistent_window_signal = pyqtSignal()
    persistent_screenshot_signal = pyqtSignal()

    def start(self):
        global global_config_dict
        hotkey_config = global_config_dict["hotkeys"]
        # this puts the the user hotkeys into the following format: https://tinyurl.com/vzs2a2rd
        hotkey_dict = {}
        if hotkey_config["single_screenshot_hotkey"]:
            hotkey_dict[hotkey_config["single_screenshot_hotkey"]] = self.single_screenshot_signal.emit
        if hotkey_config["persistent_window_hotkey"]:
            hotkey_dict[hotkey_config["persistent_window_hotkey"]] = self.persistent_window_signal.emit
        if hotkey_config["persistent_screenshot_hotkey"]:
            hotkey_dict[hotkey_config["persistent_screenshot_hotkey"]] = self.persistent_screenshot_signal.emit

        self.hotkey = keyboard.GlobalHotKeys(hotkey_dict)
        self.hotkey.start()


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
        print("persistent window not initialized yet or persistent_window location not saved")
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

        process = Thread(target=start_ocr, args=(image,))
        process.start()


def show_persistent_screenshot_window():
    global persistent_window
    persistent_window = PersistentWindow()
    persistent_window.show()


def take_single_screenshot():
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


def start_ocr(image: Image.Image):
    text = process_image(image)
    process_text(text)


def process_image(image: Image.Image):
    if global_config_dict["ocr_settings"]["grayscale"]:
        image = ImageOps.grayscale(image)
    image.save("debug.png")
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
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)  # type: ignore
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
