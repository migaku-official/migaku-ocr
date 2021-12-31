from __future__ import annotations


import copy
import io
import os
import pathlib
import platform
import re
import shutil
import math
import sys
from collections import deque
from concurrent.futures.thread import ThreadPoolExecutor
from shutil import which
from tempfile import NamedTemporaryFile
from typing import Any, Optional, cast

import numpy
import pykakasi
import pyperclip  # type: ignore
import pyscreenshot as ImageGrab  # type: ignore
import pytesseract  # type: ignore
import soundcard  # type: ignore
import tomli
import tomli_w
import typer
from appdirs import user_config_dir
from easyprocess import EasyProcess  # type: ignore
from loguru import logger
from notifypy import Notify  # type: ignore
from PIL import Image, ImageFilter, ImageOps
from PIL.ImageQt import ImageQt
from pynput import keyboard  # type: ignore
from PyQt5.QtCore import QBuffer, QObject, QRect, Qt, QThread, QTimer, pyqtBoundSignal, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QIcon, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from scipy.io import wavfile  # type: ignore

ffmpeg_command: Optional[str] = ""


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


if os.path.isfile(resource_path("./ffmpeg")):
    ffmpeg_command = resource_path("./ffmpeg")
if platform.system() == "Windows":
    ffmpeg_command = "ffmpeg.exe"


if not ffmpeg_command:
    ffmpeg_command = which("ffmpeg")

missing_program = ""
if not ffmpeg_command:
    missing_program = "ffmpeg"


unprocessed_image: Optional[Image.Image] = None
processed_image: Optional[Image.Image] = None

selected_mic = None

ocr_thread: Optional[QThread] = None
srs_screenshot_thread: Optional[QThread] = None
ocr_settings_window = None


class Rectangle:
    def __init__(self, x1=0, y1=0, x2=0, y2=0):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2


closed_persistent_window = Rectangle()


class Configuration:
    def __init__(self) -> None:
        default_settings = {
            "hotkeys": {
                "single_screenshot_hotkey": "<ctrl>+<alt>+Q",
                "persistent_window_hotkey": "<ctrl>+<alt>+W",
                "persistent_screenshot_hotkey": "<ctrl>+<alt>+E",
                "stop_recording_hotkey": "<ctrl>+<alt>+S",
            },
            "enable_global_hotkeys": False,
            "texthooker_mode": False,
            "enable_recording": False,
            "recording_seconds": 20,
            "enable_srs_image": True,
            "ocr_settings": {
                "grayscale": True,
                "upscale_amount": 2,
                "edge_enhance": True,
            },
        }
        self.config_dict: dict[str, Any]
        self.config_dict = self.load_config(default_settings)

    def load_config(self, default_settings) -> dict[str, Any]:
        config_dir = user_config_dir("migaku-ocr")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_file = os.path.join(config_dir, "config.toml")
        global_config_dict = default_settings
        try:
            with open(config_file, "r") as f:
                config_text = f.read()

            # from: https://stackoverflow.com/a/7205107
            def merge(a, b, path=None):
                "merges b into a"
                if path is None:
                    path = []
                for key in b:
                    if key in a:
                        if isinstance(a[key], dict) and isinstance(b[key], dict):
                            merge(a[key], b[key], path + [str(key)])
                        elif a[key] == b[key]:
                            pass  # same leaf value
                        else:
                            # a should win in case of conflict
                            pass
                    else:
                        a[key] = b[key]
                return a

            # merge default config and user config, user config has precedence
            global_config_dict = cast(dict, merge(tomli.loads(config_text), global_config_dict))
            logger.debug(global_config_dict)
        except FileNotFoundError:
            logger.info("no config file exists, loading default values")
        return global_config_dict

    def save_config(self):
        config_dir = user_config_dir("migaku-ocr")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_file = os.path.join(config_dir, "config.toml")
        with open(config_file, "wb") as f:
            tomli_w.dump(self.config_dict, f)


valid_keys = {
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
    def __init__(
        self,
        config: Configuration,
        master_object: MasterObject,
        srs_screenshot: SRSScreenshot,
        audio_worker: AudioWorker,
        main_hotkey_qobject: MainHotkeyQObject,
    ):
        super().__init__()
        self.setWindowTitle("Migaku OCR")
        self.setWindowFlags(Qt.Dialog)
        self.config = config
        self.srs_screenshot = srs_screenshot
        self.audio_worker = audio_worker
        self.main_hotkey_qobject = main_hotkey_qobject

        selection_ocr_button = QPushButton("Selection OCR")
        selection_ocr_button.clicked.connect(master_object.take_single_screenshot)

        show_persistent_window_button = QPushButton("Show Persistent Window")
        show_persistent_window_button.clicked.connect(master_object.show_persistent_screenshot_window)

        persistent_window_ocr_button = QPushButton("Persistent Window OCR")
        persistent_window_ocr_button.setIcon(QIcon("ocr_icon.png"))
        persistent_window_ocr_button.clicked.connect(master_object.take_screenshot_from_persistent_window)

        hotkey_config_button = QPushButton("Configure Hotkeys")
        hotkey_config_button.clicked.connect(self.show_hotkey_config)

        srs_screenshot_widget = QWidget()
        srs_screenshot_layout = QHBoxLayout()
        srs_screenshot_layout.setContentsMargins(0, 0, 0, 0)
        srs_screenshot_widget.setLayout(srs_screenshot_layout)

        srs_screenshot_checkbox = QCheckBox("SRS Screenshot 🛈")
        srs_screenshot_checkbox.setChecked(config.config_dict["enable_srs_image"])
        srs_screenshot_checkbox.setToolTip("A screenshot will be taken that can be added to your SRS cards")

        def srs_screenshot_checkbox_toggl(state):
            self.config.config_dict["enable_srs_image"] = True if state == Qt.Checked else False

        srs_screenshot_checkbox.stateChanged.connect(srs_screenshot_checkbox_toggl)
        self.texthooker_mode_checkbox = QCheckBox("Texthooker mode 🛈")
        self.texthooker_mode_checkbox.setChecked(config.config_dict["texthooker_mode"])

        def texthooker_mode_checkbox_toggl(state):
            self.config.config_dict["texthooker_mode"] = True if state == Qt.Checked else False
            if state == Qt.Checked:
                self.srs_screenshot.start_texthooker_mode()

        self.texthooker_mode_checkbox.stateChanged.connect(texthooker_mode_checkbox_toggl)
        self.texthooker_mode_checkbox.setToolTip("Screenshot is taken automatically on clipboard change")

        srs_screenshot_layout.addWidget(srs_screenshot_checkbox)
        srs_screenshot_layout.addWidget(self.texthooker_mode_checkbox)

        srs_image_location_button = QPushButton("Set Screenshot location for SRS image")
        srs_image_location_button.clicked.connect(srs_screenshot.set_srs_image_location)

        ocr_settings_button = QPushButton("Show OCR Settings")
        ocr_settings_button.clicked.connect(show_ocr_settings_window)

        self.recording_checkbox = QCheckBox("Enable Recording")
        self.recording_checkbox.setChecked(config.config_dict["enable_recording"])
        self.recording_checkbox.stateChanged.connect(self.recording_checkbox_toggl)

        save_icon = QApplication.style().standardIcon(QStyle.SP_DialogSaveButton)

        audio_save_button = QPushButton("Save Recording and send to Browser Extension")
        audio_save_button.setIcon(save_icon)
        audio_save_button.clicked.connect(audio_worker.save_audio_and_restart_recording)

        recording_layout = QHBoxLayout()
        recording_layout.setContentsMargins(0, 0, 0, 0)
        recording_layout.addWidget(self.recording_checkbox)
        recording_layout.addWidget(audio_save_button)
        recording_widget = QWidget()
        recording_widget.setLayout(recording_layout)

        recording_seconds_label = QLabel("Seconds to continuously record:")
        self.recording_seconds_spinbox = QSpinBox()
        self.recording_seconds_spinbox.setValue(config.config_dict["recording_seconds"])
        self.recording_seconds_spinbox.setMinimum(1)
        self.recording_seconds_spinbox.valueChanged.connect(self.spinbox_valuechange)

        recording_seconds_layout = QHBoxLayout()
        recording_seconds_layout.setContentsMargins(0, 0, 0, 0)
        recording_seconds_layout.addWidget(recording_seconds_label)
        recording_seconds_layout.addWidget(self.recording_seconds_spinbox)
        recording_seconds_widget = QWidget()
        recording_seconds_widget.setLayout(recording_seconds_layout)

        self.mics = soundcard.all_microphones(include_loopback=True)
        mic_names = [mic.name for mic in self.mics]
        self.mic_combobox = QComboBox()
        self.mic_combobox.addItems(mic_names)
        loopback = get_loopback_device(self.mics)
        if loopback:
            self.mic_combobox.setCurrentText(loopback.name)
        global selected_mic
        selected_mic = next(x for x in self.mics if x.name == self.mic_combobox.currentText())
        self.mic_combobox.activated[str].connect(self.mic_selection_change)

        if config.config_dict["enable_recording"]:
            self.audio_worker.save_audio_and_restart_recording()

        self.audio_peak_progressbar = QProgressBar()
        self.audio_peak_progressbar.setTextVisible(False)
        progressbar_style = """
        min-height: 10px;
        max-height: 10px;
        """
        self.audio_peak_progressbar.setStyleSheet(progressbar_style)
        self.update_audio_progressbar_in_thread()

        save_settings_button = QPushButton("Save Settings")
        save_settings_button.clicked.connect(config.save_config)

        layout = QVBoxLayout()
        layout.addWidget(selection_ocr_button)
        layout.addWidget(show_persistent_window_button)
        layout.addWidget(persistent_window_ocr_button)
        layout.addWidget(ocr_settings_button)
        layout.addWidget(hotkey_config_button)
        layout.addWidget(srs_screenshot_widget)
        layout.addWidget(srs_image_location_button)
        layout.addWidget(recording_widget)
        layout.addWidget(recording_seconds_widget)
        layout.addWidget(self.mic_combobox)
        layout.addWidget(self.audio_peak_progressbar)
        layout.addWidget(save_settings_button)
        self.setLayout(layout)

    def show_hotkey_config(self):
        # global, so it doesn't get garbage collected
        self.hotkey_window = HotKeySettingsWindow(self.config, self.main_hotkey_qobject)
        self.hotkey_window.show()

    def update_audio_progressbar_in_thread(self):
        self.update_audio_progress_thread = MainWindow.UpdateAudioProgressThread()
        self.update_audio_progress_thread.volume_signal.connect(self.update_volume_progressbar)
        self.update_audio_progress_thread.start()

    def update_volume_progressbar(self, volume: int):
        self.audio_peak_progressbar.setValue(volume)

    def recording_checkbox_toggl(self, state):
        self.config.config_dict["enable_recording"] = True if state == Qt.Checked else False
        if state == Qt.Checked:
            self.audio_worker.save_audio_and_restart_recording()
        else:
            self.audio_worker.stop_recording()

    def spinbox_valuechange(self):
        self.config.config_dict["recording_seconds"] = self.recording_seconds_spinbox.value()

    def mic_selection_change(self):
        global selected_mic
        mic_name = self.mic_combobox.currentText()
        selected_mic = next(x for x in self.mics if x.name == mic_name)
        self.update_audio_progress_thread.stop()
        self.update_audio_progress_thread.wait(1)
        self.update_audio_progressbar_in_thread()

    class UpdateAudioProgressThread(QThread):
        volume_signal = pyqtSignal([int])

        def __init__(self):
            QThread.__init__(self)
            self.stop_signal = False

        def run(self):
            samplerate = 48000
            global selected_mic
            loopback = selected_mic
            if not loopback:
                raise RuntimeError("No audio device set")
            with loopback.recorder(samplerate=samplerate) as rec:
                while not self.stop_signal:
                    data: numpy.ndarray
                    data = rec.record()
                    added_data = [abs(sum(instance)) for instance in data]
                    volume = int(math.ceil(numpy.mean(added_data) * 100))
                    self.volume_signal.emit(volume)

        def stop(self):
            self.stop_signal = True


class SRSScreenshot:
    def __init__(self, app, config: Configuration):
        self.app = app
        self.config = config
        self.srs_image_location = Rectangle()

    def set_srs_image_location(self):
        QApplication.setOverrideCursor(Qt.CrossCursor)
        selection_window = SelectorWidget(self.app)
        selection_window.show()
        selection_window.activateWindow()
        if selection_window.exec() == QDialog.Accepted:
            if selection_window.coordinates:
                self.srs_image_location.x1 = selection_window.coordinates.x1
                self.srs_image_location.y1 = selection_window.coordinates.y1
                self.srs_image_location.x2 = selection_window.coordinates.x2
                self.srs_image_location.y2 = selection_window.coordinates.y2
        QApplication.restoreOverrideCursor()

    def take_srs_screenshot(self):
        if not self.config.config_dict["enable_srs_image"]:
            # exit function if srs_image is disabled
            return
        if (
            not self.srs_image_location.x1
            and not self.srs_image_location.y1
            and not self.srs_image_location.x2
            and not self.srs_image_location.y2
        ):
            screen = QApplication.primaryScreen()
            size = screen.size()
            self.srs_image_location.x2 = size.width()
            self.srs_image_location.y2 = size.height()

        image = ImageGrab.grab(
            bbox=(
                self.srs_image_location.x1,
                self.srs_image_location.y1,
                self.srs_image_location.x2,
                self.srs_image_location.y2,
            )
        )
        if image:
            image.save("test.png")

    def trigger_srs_screenshot_on_clipboard_change(self):
        while True:
            pyperclip.waitForNewPaste()
            if not self.config.config_dict["texthooker_mode"]:
                break
            self.take_srs_screenshot()

    def take_srs_screenshot_in_thread(self):
        global srs_screenshot_thread
        srs_screenshot_thread = SRSScreenshot.SRSScreenshotThread(self, self.config)
        srs_screenshot_thread.start()

    class SRSScreenshotThread(QThread):
        def __init__(self, srs_screenshot: SRSScreenshot, config: Configuration):
            QThread.__init__(self)
            self.config = config
            self.srs_screenshot = srs_screenshot

        def run(self):
            self.srs_screenshot.take_srs_screenshot()

    def start_texthooker_mode(self):
        self.texthooker_mode_thread = SRSScreenshot.TexthookerModeThread(self, self.config)
        self.texthooker_mode_thread.start()

    class TexthookerModeThread(QThread):
        def __init__(self, srs_screenshot: SRSScreenshot, config: Configuration):
            QThread.__init__(self)
            self.srs_screenshot = srs_screenshot
            self.config = config

        def run(self):
            self.srs_screenshot.trigger_srs_screenshot_on_clipboard_change()


def show_ocr_settings_window():
    global ocr_settings_window
    ocr_settings_window = OCRSettingsWindow()
    ocr_settings_window.show()


class OCRSettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Migaku OCR Settings")
        self.setWindowFlags(Qt.Dialog)
        self.unprocessed_image_label = QLabel()
        self.processed_image_label = QLabel()

        layout = QHBoxLayout()
        left_side_layout = QVBoxLayout()
        right_side_layout = QVBoxLayout()

        global unprocessed_image
        if unprocessed_image:
            im = ImageQt(unprocessed_image).copy()
            pixmap = QPixmap.fromImage(im)
            self.unprocessed_image_label.setPixmap(pixmap)
        else:
            self.unprocessed_image_label.setText("No screenshot taken yet...")

        global processed_image
        if processed_image:
            im = ImageQt(processed_image).copy()
            pixmap = QPixmap.fromImage(im)
            self.processed_image_label.setPixmap(pixmap)
        else:
            self.processed_image_label.setText("...therefore there's nothing to process.")

        self.ocr_text_label = QLabel("This will show the resulting OCR text.")

        unprocessed_image_layout = QHBoxLayout()
        unprocessed_image_scrollarea = QScrollArea()
        unprocessed_image_scrollarea.setLayout(unprocessed_image_layout)
        unprocessed_image_scrollarea.setWidgetResizable(True)
        unprocessed_image_layout.addWidget(self.unprocessed_image_label)

        processed_image_layout = QHBoxLayout()
        processed_image_scrollarea = QScrollArea()
        processed_image_scrollarea.setLayout(processed_image_layout)
        processed_image_scrollarea.setWidgetResizable(True)
        processed_image_layout.addWidget(self.processed_image_label)

        left_side_layout.addWidget(unprocessed_image_scrollarea)
        left_side_layout.addWidget(processed_image_scrollarea)
        left_side_layout.addWidget(self.ocr_text_label)
        left_side_layout.addStretch()

        left_side_widget = QWidget()
        left_side_widget.setLayout(left_side_layout)
        layout.addWidget(left_side_widget)

        global global_config_dict

        def change_upscale_value(state):
            global_config_dict["ocr_settings"]["upscale_amount"] = state
            start_ocr_in_thread(unprocessed_image)

        def toogle_grayscale(state):
            global_config_dict["ocr_settings"]["grayscale"] = True if state == Qt.Checked else False
            start_ocr_in_thread(unprocessed_image)

        def toogle_sharpen(state):
            global_config_dict["ocr_settings"]["edge_enhance"] = True if state == Qt.Checked else False
            start_ocr_in_thread(unprocessed_image)

        upscale_spinbox = QSpinBox()
        upscale_spinbox.setValue(global_config_dict["ocr_settings"]["upscale_amount"])
        upscale_spinbox.setMinimum(1)
        upscale_spinbox.setMaximum(6)
        upscale_spinbox.valueChanged.connect(change_upscale_value)
        right_side_layout.addWidget(upscale_spinbox)

        grayscaleCheckBox = QCheckBox("Grayscale")
        grayscaleCheckBox.setChecked(global_config_dict["ocr_settings"]["grayscale"])
        grayscaleCheckBox.stateChanged.connect(toogle_grayscale)
        right_side_layout.addWidget(grayscaleCheckBox)

        sharpenCheckBox = QCheckBox("Sharpen Edges")
        sharpenCheckBox.setChecked(global_config_dict["ocr_settings"]["edge_enhance"])
        sharpenCheckBox.stateChanged.connect(toogle_sharpen)
        right_side_layout.addWidget(sharpenCheckBox)

        right_side_widget = QWidget()
        right_side_widget.setLayout(right_side_layout)
        layout.addWidget(right_side_widget)
        self.setLayout(layout)

    def refresh_unprocessed_image(self, image):
        im = ImageQt(image).copy()
        pixmap = QPixmap.fromImage(im)
        self.unprocessed_image_label.setPixmap(pixmap)

    def refresh_processed_image(self, image):
        im = ImageQt(image).copy()
        pixmap = QPixmap.fromImage(im)
        self.processed_image_label.setPixmap(pixmap)

    def refresh_ocr_text(self, text):
        self.ocr_text_label.setText(text)


class HotKeySettingsWindow(QWidget):
    def __init__(self, config: Configuration, main_hotkey_qobject):
        super().__init__()
        self.main_hotkey_qobject = main_hotkey_qobject
        self.config = config

        self.main_hotkey_qobject.stop()

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
        stopRecordingHotkeyField = HotKeyField("stop_recording_hotkey", "Stop recording")
        layout.addWidget(stopRecordingHotkeyField)

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
        self.config.save_config()
        self.close()

    def cancelClose(self):
        global global_config_dict
        global_config_dict = self.original_config
        self.close()

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)
        self.main_hotkey_qobject.start()


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
        self.modifiers: Qt.KeyboardModifiers = Qt.NoModifier  # type: ignore
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
        if self.key not in valid_keys:
            self.keysequence = QKeySequence(self.modifiers)
        else:
            self.keysequence = QKeySequence(self.modifiers | self.key)  # type: ignore
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
        tmp = tmp.replace("return", "<enter>")
        tmp = tmp.replace("backspace", "<backspace>")
        tmp = tmp.replace("pgdown", "page_down")
        tmp = tmp.replace("pgup", "page_up")
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
    def __init__(self, master_object: MasterObject, x=0, y=0, w=400, h=200):
        super().__init__()
        self.setWindowTitle("Migaku OCR")

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)  # type: ignore

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
        ocrButton.clicked.connect(master_object.take_screenshot_from_persistent_window)
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
        innerLayout.addWidget(ocrButton, alignment=Qt.AlignRight | Qt.AlignBottom)  # type: ignore
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
                # self.overlay = QPixmap(w, h)
                # self.overlay.fill(Qt.transparent)

            make_size_follow_cursor()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.is_moving = False
        self.is_resizing = False
        QApplication.restoreOverrideCursor()

    def keyPressEvent(self, event):

        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            global closed_persistent_window
            closed_persistent_window.x1 = self.x()
            closed_persistent_window.y1 = self.y()
            closed_persistent_window.x2 = closed_persistent_window.x1 + self.width()
            closed_persistent_window.y2 = closed_persistent_window.y1 + self.height()

            self.close()

        if event.key() in [Qt.Key_Escape]:
            self.close()


typer_app = typer.Typer()


@typer_app.command()
def execute_order66():
    global master_object
    master_object = MasterObject()


class MasterObject:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.config = Configuration()
        global global_config_dict
        global_config_dict = self.config.config_dict
        self.srs_screenshot = SRSScreenshot(self.app, self.config)
        self.audio_worker = AudioWorker()
        self.main_hotkey_qobject = MainHotkeyQObject(self.config, self, self.audio_worker)
        # this allows for ctrl-c to close the application
        timer = QTimer()
        timer.start(500)
        timer.timeout.connect(lambda: None)
        self.setup_tray()

        self.show_main_window()

        sys.exit(self.app.exec_())

    def setup_tray(self):
        icon = QIcon("migaku_icon.png")

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(icon)
        self.tray.setVisible(True)
        menu = QMenu()

        openMain = QAction("Open")
        openMain.triggered.connect(self.show_main_window)
        quit = QAction("Quit")
        quit.triggered.connect(self.app.quit)

        menu.addAction(openMain)
        menu.addAction(quit)

        self.tray.setContextMenu(menu)

    def show_main_window(self):
        self.main_window = MainWindow(
            self.config, self, self.srs_screenshot, self.audio_worker, self.main_hotkey_qobject
        )
        self.main_window.show()

    def take_single_screenshot(self):
        self.srs_screenshot.take_srs_screenshot_in_thread()
        QApplication.setOverrideCursor(Qt.CrossCursor)
        selector = SelectorWidget(self.app)
        selector.show()
        selector.activateWindow()
        if selector.exec() == QDialog.Accepted:
            if selector.selectedPixmap:
                image = convert_qpixmap_to_pil_image(selector.selectedPixmap)
                start_ocr_in_thread(image)
        QApplication.restoreOverrideCursor()

    def show_persistent_screenshot_window(self):
        self.persistent_window = PersistentWindow(self)
        self.persistent_window.show()

    def take_screenshot_from_persistent_window(self):
        self.srs_screenshot.take_srs_screenshot_in_thread()
        persistent_window = self.persistent_window
        global closed_persistent_window
        if not persistent_window and (
            not closed_persistent_window.x1
            and not closed_persistent_window.y1
            and not closed_persistent_window.x2
            and not closed_persistent_window.y2
        ):
            logger.warning("persistent window not initialized yet or persistent_window location not saved")
        else:
            if persistent_window:
                x1 = persistent_window.x()
                y1 = persistent_window.y()
                x2 = x1 + persistent_window.width()
                y2 = y1 + persistent_window.height()
            else:
                x1 = closed_persistent_window.x1
                y1 = closed_persistent_window.y1
                x2 = closed_persistent_window.x2
                y2 = closed_persistent_window.y2
            image = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            if image and persistent_window and persistent_window.ocrButton.isVisible():
                button = persistent_window.ocrButton
                x1 = button.x()
                y1 = button.y()
                width = button.width()
                height = button.height()
                color = image.getpixel((x1 - 1, y1 + height - 2))
                for x in range(width):
                    for y in range(height):
                        image.putpixel((x1 + x, y1 + y), color)

            start_ocr_in_thread(image)


class MainHotkeyQObject(QObject):
    def __init__(self, config: Configuration, master_object: MasterObject, audio_worker: AudioWorker):
        super().__init__()

        if config.config_dict["enable_global_hotkeys"]:
            logger.info("Started hotkeys")
            self.manager = KeyBoardManager(config)
            self.manager.single_screenshot_signal.connect(master_object.take_single_screenshot)
            self.manager.persistent_window_signal.connect(master_object.show_persistent_screenshot_window)
            self.manager.persistent_screenshot_signal.connect(master_object.take_screenshot_from_persistent_window)
            self.manager.stop_recording_signal.connect(audio_worker.stop_recording)
            self.start()

    def start(self):
        self.manager.start()

    def stop(self):
        try:
            self.manager.hotkey.stop()
        except AttributeError:
            pass


class KeyBoardManager(QObject):
    single_screenshot_signal = pyqtSignal()
    persistent_window_signal = pyqtSignal()
    persistent_screenshot_signal = pyqtSignal()
    stop_recording_signal = pyqtSignal()

    def __init__(self, config: Configuration):
        super().__init__()
        self.config = config

    def start(self):
        global global_config_dict
        hotkey_config = self.config.config_dict["hotkeys"]
        # this puts the the user hotkeys into the following format: https://tinyurl.com/vzs2a2rd
        hotkey_dict = {}
        if hotkey_config["single_screenshot_hotkey"]:
            hotkey_dict[hotkey_config["single_screenshot_hotkey"]] = self.single_screenshot_signal.emit
        if hotkey_config["persistent_window_hotkey"]:
            hotkey_dict[hotkey_config["persistent_window_hotkey"]] = self.persistent_window_signal.emit
        if hotkey_config["persistent_screenshot_hotkey"]:
            hotkey_dict[hotkey_config["persistent_screenshot_hotkey"]] = self.persistent_screenshot_signal.emit
        if hotkey_config["stop_recording_hotkey"]:
            hotkey_dict[hotkey_config["stop_recording_hotkey"]] = self.stop_recording_signal.emit

        self.hotkey = keyboard.GlobalHotKeys(hotkey_dict)
        self.hotkey.start()


class OCRThread(QThread):
    unprocessed_signal = pyqtSignal([Image.Image])
    processed_signal = pyqtSignal([Image.Image])
    ocr_text_signal = pyqtSignal([str])

    def __init__(self, image, parent=None):
        QThread.__init__(self, parent)
        self.image = image

    def run(self):
        start_ocr(self.image, self.unprocessed_signal, self.processed_signal, self.ocr_text_signal)


def start_ocr_in_thread(image):
    if image:
        global ocr_thread
        if ocr_thread:
            ocr_thread.wait()
        ocr_thread = OCRThread(image)
        ocr_thread.start()
        global ocr_settings_window
        if ocr_settings_window:
            ocr_thread.unprocessed_signal.connect(ocr_settings_window.refresh_unprocessed_image)
            ocr_thread.processed_signal.connect(ocr_settings_window.refresh_processed_image)
            ocr_thread.ocr_text_signal.connect(ocr_settings_window.refresh_ocr_text)


def start_ocr(
    image: Image.Image,
    unprocessed_signal: pyqtBoundSignal,
    processed_signal: pyqtBoundSignal,
    ocr_text_signal: pyqtBoundSignal,
):
    global unprocessed_image
    unprocessed_image = image.copy()
    unprocessed_signal.emit(unprocessed_image)

    image = process_image(image)

    processed_signal.emit(image)
    global processed_image
    processed_image = image

    text = do_ocr(image)
    ocr_text_signal.emit(text)
    process_text(text)


def process_image(image: Image.Image):
    upscale_amount = global_config_dict["ocr_settings"]["upscale_amount"]
    image = image.resize((image.width * upscale_amount, image.height * upscale_amount))
    if global_config_dict["ocr_settings"]["grayscale"]:
        image = ImageOps.grayscale(image)
    if global_config_dict["ocr_settings"]["edge_enhance"]:
        image = image.filter(ImageFilter.EDGE_ENHANCE)
    return image


def do_ocr(image: Image.Image):
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
    text = text.strip()

    for (f, t) in [(" ", ""), ("いぃ", "い"), ("\n", "")]:
        text = text.replace(f, t)
    logger.info(text)
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


def capture_desktop(app: QApplication):
    desktop_pixmap = QPixmap(QApplication.desktop().size())
    painter = QPainter(desktop_pixmap)
    for screen in app.screens():
        painter.drawPixmap(
            screen.geometry().topLeft(),
            screen.grabWindow(0),  # type: ignore
        )
    # painter.end()
    return desktop_pixmap


class SelectorWidget(QDialog):
    def __init__(self, app: QApplication):
        super().__init__()
        if platform.system() == "Linux":
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.X11BypassWindowManagerHint  # type: ignore
            )
        elif platform.system() == "Windows":
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)  # type: ignore
        elif platform.system() == "Darwin":
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowFullscreenButtonHint  # type: ignore
            )

        self.setGeometry(QApplication.desktop().geometry())
        self.desktopPixmap = capture_desktop(app)
        self.selectedRect = QRect()
        self.selectedPixmap = None

        self.coordinates = Rectangle()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key_Escape]:
            self.reject()

    def mousePressEvent(self, event: QMouseEvent):
        self.selectedRect.setTopLeft(event.globalPos())
        self.coordinates.x1 = event.globalX()
        self.coordinates.y1 = event.globalY()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.selectedRect.setBottomRight(event.globalPos())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.selectedPixmap = self.desktopPixmap.copy(self.selectedRect.normalized())
        self.coordinates.x2 = event.globalX()
        self.coordinates.y2 = event.globalY()
        self.accept()

    def paintEvent(self, _: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.desktopPixmap)
        path = QPainterPath()
        painter.fillPath(path, QColor.fromRgb(255, 255, 255, 200))
        painter.setPen(Qt.red)
        painter.drawRect(self.selectedRect)
        # painter.end()


def convert_qpixmap_to_pil_image(pixmap: QPixmap):
    q_image = pixmap.toImage()
    buffer = QBuffer()
    buffer.open(QBuffer.ReadWrite)
    q_image.save(buffer, "PNG")
    return Image.open(io.BytesIO(buffer.data()))  # type: ignore


def convert_to_hiragana(text):
    kks = pykakasi.kakasi()
    result = kks.convert(text)
    result_str = ""
    for item in result:
        result_str += item["hira"]
    return result_str


class AudioWorker:
    def __init__(self):
        self.audio_recorder_thread: Optional[AudioWorker.AudioRecorderThread] = None
        self.audio_processing_thread: Optional[AudioWorker.AudioProcessorThread] = None

    def save_audio_and_restart_recording(self):
        self.stop_recording()
        self._start_recording()

    def _start_recording(self):
        if self.audio_recorder_thread:
            self.stop_recording()
        self.audio_recorder_thread = AudioWorker.AudioRecorderThread(self)
        self.audio_recorder_thread.finished.connect(self._process_audio)
        self.audio_recorder_thread.start()

    def stop_recording(self) -> None:
        if self.audio_recorder_thread:
            self.audio_recorder_thread.stop_recording = True
            self.audio_recorder_thread.wait(3)

    def _process_audio(self, audio_deque):
        if self.audio_processing_thread:
            self.audio_processing_thread.wait(2)
        self.audio_processing_thread = AudioWorker.AudioProcessorThread(audio_deque)
        self.audio_processing_thread.start()

    class AudioRecorderThread(QThread):
        finished = pyqtSignal([deque])

        def __init__(self, audio_worker: AudioWorker, parent=None) -> None:
            QThread.__init__(self, parent)
            self.stop_recording = False
            self.audio_worker = audio_worker

        def run(self):
            self._record_audio()

        def _record_audio(self) -> None:
            logger.debug("Starting audio recording")
            samplerate = 48000
            global selected_mic
            loopback = selected_mic
            if not loopback:
                raise RuntimeError("No audio device set")

            audio_deque: deque = deque()
            logger.debug(f"selected mic: {loopback}")
            with loopback.recorder(samplerate=samplerate) as rec:
                while True:
                    if self.stop_recording:
                        break
                    data = rec.record(numframes=samplerate)
                    audio_deque.append(data)
                    if len(audio_deque) > global_config_dict["recording_seconds"]:
                        audio_deque.popleft()
            self.finished.emit(audio_deque)

    class AudioProcessorThread(QThread):
        def __init__(self, audio_deque):
            QThread.__init__(self)
            self.audio_deque = audio_deque

        def run(self):
            self._process_audio_data(self.audio_deque)

        def _process_audio_data(self, audio_deque: deque):
            logger.info("Processing audio")
            final_data = audio_deque[0]
            for count, audio in enumerate(audio_deque):
                if count == 0:
                    continue
                final_data = numpy.append(final_data, audio, axis=0)

            def strip_silent_audio(audio_data):
                def strip_silent_audio_generic(audio_data):
                    audio_counter = 0
                    for audio in audio_data:
                        is_silent = True
                        for single_channel_sound in audio:
                            if single_channel_sound:
                                is_silent = False
                        audio_counter += 1
                        if not is_silent:
                            break
                    return audio_counter

                def strip_silent_audio_beginning(audio_data):
                    audio_counter = strip_silent_audio_generic(audio_data)
                    return audio_data[audio_counter:]

                def strip_silent_audio_end(audio_data):
                    audio_counter = strip_silent_audio_generic(reversed(audio_data))
                    return audio_data[:-audio_counter]

                audio_data = strip_silent_audio_beginning(audio_data)
                audio_data = strip_silent_audio_end(audio_data)
                return audio_data

            final_data = strip_silent_audio(final_data)

            if final_data.size > 0:
                logger.info("Converting audio")
                with NamedTemporaryFile(suffix=".wav") as temp_wav_file:
                    with NamedTemporaryFile(suffix=".mp3") as temp_mp3_file:
                        wavfile.write(temp_wav_file, 48000, final_data)
                        cmd = ["ffmpeg", "-y", "-i", temp_wav_file.name, temp_mp3_file.name]
                        EasyProcess(cmd).call(timeout=40)
                        # uncomment below for testing
                        shutil.copyfile(temp_mp3_file.name, "test.mp3")


def get_loopback_device(mics):
    default_speaker = soundcard.default_speaker()
    loopback = None

    def get_loopback(mics, default_speaker):
        loopback = None
        for mic in mics:
            if mic.isloopback and default_speaker.name in mic.name:
                loopback = mic
                break
        if not loopback:
            for mic in mics:
                if default_speaker.name in mic.name:
                    loopback = mic
                    break
        return loopback

    loopback = get_loopback(mics, default_speaker)
    return loopback


if __name__ == "__main__":
    typer_app()
