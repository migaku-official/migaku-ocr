from __future__ import annotations
import time
import imagehash  # type: ignore

# from tesserocr import PyTessBaseAPI, PSM, OEM  # type: ignore

import contextlib
import signal

from typing import Union
from PIL.PyAccess import PyAccess


import cv2  # type: ignore
import doxapy  # type: ignore

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
import pyperclip  # type: ignore
import pytesseract  # type: ignore
import soundcard  # type: ignore
import tomli
import tomli_w
import typer
from appdirs import user_config_dir
from easyprocess import EasyProcess  # type: ignore
from loguru import logger
from superqt import QLabeledSlider
from PIL import Image, ImageOps, ImageGrab
from PIL.ImageQt import ImageQt
from pynput import keyboard  # type: ignore
from PySide6.QtCore import QBuffer, QObject, QRect, Qt, QThread, Signal, SignalInstance, QMimeData, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
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
    QSlider,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from scipy.io import wavfile  # type: ignore

ffmpeg_command: Optional[str] = ""
tesseract_command: Optional[str] = ""


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


if platform.system() == "Windows":
    if os.path.isfile(resource_path("ffmpeg.exe")):
        ffmpeg_command = resource_path("ffmpeg.exe")
    if os.path.isfile(resource_path("./tesseract/tesseract.exe")):
        tesseract_command = resource_path("./tesseract/tesseract.exe")
    elif os.path.isfile(resource_path("./Game2Text/resources/bin/win/tesseract/tesseract.exe")):
        tesseract_command = resource_path("./Game2Text/resources/bin/win/tesseract/tesseract.exe")
    if not tesseract_command:
        tesseract_command = which("tesseract.exe")
elif os.path.isfile(resource_path("./ffmpeg")):
    ffmpeg_command = resource_path("./ffmpeg")

if not tesseract_command:
    tesseract_command = which("tesseract.exe")

if not ffmpeg_command:
    ffmpeg_command = which("ffmpeg")

selected_mic = None


class Rectangle:
    def __init__(self, x1=0.0, y1=0.0, x2=0.0, y2=0.0):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    def __bool__(self):
        return bool(self.x2 or self.y1 or self.x2 or self.y2)

    def get_width(self) -> int:
        return self.x2 - self.x1

    def get_height(self) -> int:
        return self.y2 - self.y1


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
            "auto_save_recording": False,
            "recording_seconds": 20,
            "enable_srs_image": True,
            "ocr_settings": {
                "upscale_amount": 3,
                "enable_thresholding": True,
                "automatic_thresholding": True,
                "thresholding_value": 130,
                "thresholding_algorithm": "OTSU",
                "smart_image_inversion": True,
                "add_border": True,
                "character_blacklist": "",
            },
        }
        self.config_dict: dict[str, Any]
        self.config_dict = self.load_config(default_settings)

    def load_config(self, default_settings) -> dict[str, Any]:
        config_dir = user_config_dir("migaku-ocr")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_file = os.path.join(config_dir, "config.toml")
        config_dict = default_settings
        try:
            with open(config_file, "r") as f:
                config_text = f.read()

            # merge default config and user config, user config has precedence
            config_dict = cast(dict, merge(tomli.loads(config_text), config_dict))
            logger.debug(config_dict)
        except FileNotFoundError:
            logger.info("no config file exists, loading default values")
        return config_dict

    def save_config(self):
        config_dir = user_config_dir("migaku-ocr")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_file = os.path.join(config_dir, "config.toml")
        with open(config_file, "wb") as f:
            tomli_w.dump(self.config_dict, f)


algorithms = {
    "OTSU": doxapy.Binarization.Algorithms.OTSU,
    "BERNSEN": doxapy.Binarization.Algorithms.BERNSEN,
    "NIBLACK": doxapy.Binarization.Algorithms.NIBLACK,
    "SAUVOLA": doxapy.Binarization.Algorithms.SAUVOLA,
    "WOLF": doxapy.Binarization.Algorithms.WOLF,
    "NICK": doxapy.Binarization.Algorithms.NICK,
    "TRSINGH": doxapy.Binarization.Algorithms.TRSINGH,
    "BATAINEH": doxapy.Binarization.Algorithms.BATAINEH,
    "ISAUVOLA": doxapy.Binarization.Algorithms.ISAUVOLA,
    "WAN": doxapy.Binarization.Algorithms.WAN,
    "GATOS": doxapy.Binarization.Algorithms.GATOS,
}
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
        self.setWindowFlags(Qt.Dialog)  # type: ignore
        self.config = config
        self.srs_screenshot = srs_screenshot
        self.audio_worker = audio_worker
        self.main_hotkey_qobject = main_hotkey_qobject
        self.master_object = master_object
        self.ocr_settings_window: Optional[OCRSettingsWindow] = None
        processed_image = master_object.processed_image

        selection_ocr_button = QPushButton("Selection OCR")
        selection_ocr_button.clicked.connect(master_object.take_single_screenshot)  # type: ignore

        show_persistent_window_button = QPushButton("Show Persistent Window")
        show_persistent_window_button.clicked.connect(master_object.show_persistent_screenshot_window)  # type: ignore

        persistent_window_container = QWidget()
        persistent_window_layout = QHBoxLayout()
        persistent_window_layout.setContentsMargins(0, 0, 0, 0)
        persistent_window_container.setLayout(persistent_window_layout)

        persistent_window_ocr_button = QPushButton("Persistent Window OCR")
        persistent_window_ocr_button.clicked.connect(master_object.take_screenshot_from_persistent_window)  # type: ignore
        persistent_window_layout.addWidget(persistent_window_ocr_button)

        persistent_window_auto_ocr_button = QPushButton("Auto OCR")
        persistent_window_auto_ocr_button.clicked.connect(self.toggle_auto_ocr)  # type: ignore
        persistent_window_layout.addWidget(persistent_window_auto_ocr_button)

        hotkey_config_button = QPushButton("Configure Hotkeys")
        hotkey_config_button.clicked.connect(self.show_hotkey_config)  # type: ignore

        ocr_settings_button = QPushButton("OCR Settings")
        ocr_settings_button.clicked.connect(self.show_ocr_settings_window)  # type: ignore

        self.ocr_text_linedit_current = QLineEdit("This will contain the latest ocr result")
        self.ocr_text_linedit_last = QLineEdit("This will contain the previous ocr result")

        thresholding_widget = QWidget()
        thresholding_layout = QHBoxLayout()
        thresholding_layout.setContentsMargins(0, 0, 0, 0)
        thresholding_widget.setLayout(thresholding_layout)

        def toggle_thresholding(state):
            if state == Qt.Checked:
                self.config.config_dict["ocr_settings"]["enable_thresholding"] = True
                self.automatic_thresholding_check_box.setEnabled(True)
                self.thresholding_slider.setEnabled(True)
                self.algorithm_combobox.setEnabled(True)
            else:
                self.config.config_dict["ocr_settings"]["enable_thresholding"] = False
                self.automatic_thresholding_check_box.setEnabled(False)
                self.thresholding_slider.setEnabled(False)
                self.algorithm_combobox.setEnabled(False)
            master_object.ocr.start_ocr_in_thread(master_object.unprocessed_image, skip_override=True)

        self.enable_thresholding_checkbox = QCheckBox("Enable Thresholding")
        self.enable_thresholding_checkbox.setChecked(config.config_dict["ocr_settings"]["enable_thresholding"])
        self.enable_thresholding_checkbox.stateChanged.connect(toggle_thresholding)  # type: ignore

        thresholding_layout.addWidget(self.enable_thresholding_checkbox)

        def toggle_automatic_thresholding(state):
            if state == Qt.Checked:
                self.config.config_dict["ocr_settings"]["automatic_thresholding"] = True
                self.thresholding_slider.setEnabled(True)
                self.algorithm_combobox.setEnabled(True)
            else:
                self.config.config_dict["ocr_settings"]["automatic_thresholding"] = False
                self.thresholding_slider.setEnabled(False)
                self.algorithm_combobox.setEnabled(False)
            master_object.ocr.start_ocr_in_thread(master_object.unprocessed_image, skip_override=True)

        self.automatic_thresholding_check_box = QCheckBox("Automatic Thresholding")
        self.automatic_thresholding_check_box.setChecked(config.config_dict["ocr_settings"]["automatic_thresholding"])
        self.automatic_thresholding_check_box.stateChanged.connect(toggle_automatic_thresholding)  # type: ignore
        self.automatic_thresholding_check_box.setEnabled(config.config_dict["ocr_settings"]["enable_thresholding"])
        thresholding_layout.addWidget(self.automatic_thresholding_check_box)

        self.algorithm_combobox = QComboBox()
        self.algorithm_combobox.addItems(list(algorithms))
        self.algorithm_combobox.activated.connect(self.algorithm_change)  # type: ignore
        self.algorithm_combobox.setEnabled(
            config.config_dict["ocr_settings"]["enable_thresholding"]
            and config.config_dict["ocr_settings"]["automatic_thresholding"]
        )

        def change_thresholding_value():
            self.config.config_dict["ocr_settings"]["thresholding_value"] = self.thresholding_slider.value()
            print(f"thresholding: {self.thresholding_slider.value()}")
            print(f"image: {master_object.unprocessed_image}")
            self.master_object.ocr.start_ocr_in_thread(master_object.unprocessed_image, skip_override=True)

        self.thresholding_slider = QSlider(Qt.Horizontal)
        self.thresholding_slider.setRange(0, 255)
        self.thresholding_slider.setPageStep(1)
        self.thresholding_slider.setValue(config.config_dict["ocr_settings"]["thresholding_value"])
        self.thresholding_slider.sliderReleased.connect(change_thresholding_value)  # type: ignore
        self.thresholding_slider.setEnabled(
            config.config_dict["ocr_settings"]["enable_thresholding"]
            and config.config_dict["ocr_settings"]["automatic_thresholding"]
        )

        processed_image = master_object.processed_image
        self.image_preview = ImagePreview(processed_image)

        srs_screenshot_widget1 = QWidget()
        srs_screenshot_layout1 = QHBoxLayout()
        srs_screenshot_layout1.setContentsMargins(0, 0, 0, 0)
        srs_screenshot_widget1.setLayout(srs_screenshot_layout1)

        srs_screenshot_checkbox = QCheckBox("SRS Screenshot 🛈")
        srs_screenshot_checkbox.setChecked(config.config_dict["enable_srs_image"])
        srs_screenshot_checkbox.setToolTip("A screenshot will be taken that can be added to your SRS cards")

        def srs_screenshot_checkbox_toggl(state):
            self.config.config_dict["enable_srs_image"] = bool(state == Qt.Checked)

        srs_screenshot_checkbox.stateChanged.connect(srs_screenshot_checkbox_toggl)  # type: ignore
        self.texthooker_mode_checkbox = QCheckBox("Texthooker mode 🛈")
        self.texthooker_mode_checkbox.setChecked(config.config_dict["texthooker_mode"])

        def texthooker_mode_checkbox_toggl(state):
            self.config.config_dict["texthooker_mode"] = bool(state == Qt.Checked)
            if state == Qt.Checked:
                self.srs_screenshot.start_texthooker_mode()

        self.texthooker_mode_checkbox.stateChanged.connect(texthooker_mode_checkbox_toggl)  # type: ignore
        self.texthooker_mode_checkbox.setToolTip("Screenshot is taken automatically on clipboard change")

        srs_screenshot_widget2 = QWidget()
        srs_screenshot_layout2 = QHBoxLayout()
        srs_screenshot_layout2.setContentsMargins(0, 0, 0, 0)
        srs_screenshot_widget2.setLayout(srs_screenshot_layout2)

        manual_srs_screenshot_button = QPushButton("Manual SRS Screenshot")
        manual_srs_screenshot_button.clicked.connect(self.srs_screenshot.take_srs_screenshot)  # type: ignore
        srs_screenshot_layout2.addWidget(manual_srs_screenshot_button)

        def copy_screenshot_to_clipboard():
            if self.srs_screenshot.image:
                im = ImageQt(self.srs_screenshot.image).copy()
                print(type(im))
                QApplication.clipboard().setImage(im)

        srs_screenshot_to_clipboard_button = QPushButton("Copy Screenshot to Clipboard")
        srs_screenshot_to_clipboard_button.clicked.connect(copy_screenshot_to_clipboard)  # type: ignore
        srs_screenshot_layout2.addWidget(srs_screenshot_to_clipboard_button)

        srs_screenshot_layout1.addWidget(srs_screenshot_checkbox)
        srs_screenshot_layout1.addWidget(self.texthooker_mode_checkbox)

        srs_image_location_button = QPushButton("Set Screenshot Location for SRS Image")
        srs_image_location_button.clicked.connect(srs_screenshot.set_srs_image_location)  # type: ignore

        self.recording_checkbox = QCheckBox("Enable Recording")
        self.recording_checkbox.setChecked(config.config_dict["enable_recording"])
        self.recording_checkbox.stateChanged.connect(self.recording_checkbox_toggl)  # type: ignore

        self.auto_save_recording_checkbox = QCheckBox("Save Recording on OCR")
        self.auto_save_recording_checkbox.setChecked(config.config_dict["auto_save_recording"])
        self.auto_save_recording_checkbox.stateChanged.connect(self.auto_save_recording_checkbox_toggl)  # type: ignore

        save_icon = QApplication.style().standardIcon(QStyle.SP_DialogSaveButton)

        self.audio_save_button = QPushButton("Save Recording")
        self.audio_save_button.setIcon(save_icon)
        self.audio_save_button.clicked.connect(audio_worker.save_audio_and_restart_recording)  # type: ignore
        self.audio_save_button.setEnabled(config.config_dict["enable_recording"])

        self.audio_clipboard_button = QPushButton("Copy last recording to clipboard")
        self.audio_clipboard_button.clicked.connect(audio_worker.save_last_file_to_clipboard)  # type: ignore
        self.audio_clipboard_button.setEnabled(config.config_dict["enable_recording"])

        recording_layout1 = QHBoxLayout()
        recording_layout1.setContentsMargins(0, 0, 0, 0)
        recording_layout1.addWidget(self.recording_checkbox)
        recording_layout1.addWidget(self.auto_save_recording_checkbox)
        recording_widget1 = QWidget()
        recording_widget1.setLayout(recording_layout1)

        recording_layout2 = QHBoxLayout()
        recording_layout2.setContentsMargins(0, 0, 0, 0)
        recording_layout2.addWidget(self.audio_save_button)
        recording_layout2.addWidget(self.audio_clipboard_button)
        recording_widget2 = QWidget()
        recording_widget2.setLayout(recording_layout2)

        recording_seconds_label = QLabel("Seconds to continuously record:")
        self.recording_seconds_spinbox = QSpinBox()
        self.recording_seconds_spinbox.setValue(config.config_dict["recording_seconds"])
        self.recording_seconds_spinbox.setMinimum(1)
        self.recording_seconds_spinbox.valueChanged.connect(self.spinbox_valuechange)  # type: ignore

        recording_seconds_layout = QHBoxLayout()
        recording_seconds_layout.setContentsMargins(0, 0, 0, 0)
        recording_seconds_layout.addWidget(recording_seconds_label)
        recording_seconds_layout.addWidget(self.recording_seconds_spinbox)
        recording_seconds_widget = QWidget()
        recording_seconds_widget.setLayout(recording_seconds_layout)

        try:
            self.mics = soundcard.all_microphones(include_loopback=True)
        except RuntimeError:
            self.mics = []
        mic_names = [mic.name for mic in self.mics]
        self.mic_combobox = QComboBox()
        self.mic_combobox.addItems(mic_names)
        loopback = get_loopback_device(self.mics)
        if loopback:
            self.mic_combobox.setCurrentText(loopback.name)
        global selected_mic
        try:
            selected_mic = next(x for x in self.mics if x.name == self.mic_combobox.currentText())
        except (RuntimeError, StopIteration):
            selected_mic = None

        self.mic_combobox.activated.connect(self.mic_selection_change)  # type: ignore

        if config.config_dict["enable_recording"]:
            self.audio_worker.save_audio_and_restart_recording()

        self.audio_peak_progressbar = QProgressBar()
        self.audio_peak_progressbar.setRange(0, 1000)
        self.audio_peak_progressbar.setTextVisible(False)
        progressbar_style = """
        min-height: 10px;
        max-height: 10px;
        """
        self.audio_peak_progressbar.setStyleSheet(progressbar_style)
        self.update_audio_progressbar_in_thread()

        save_settings_button = QPushButton("Save Settings")
        save_settings_button.clicked.connect(config.save_config)  # type: ignore

        layout = QVBoxLayout()
        layout.addWidget(selection_ocr_button)
        layout.addWidget(show_persistent_window_button)
        layout.addWidget(persistent_window_container)
        layout.addWidget(ocr_settings_button)
        layout.addWidget(self.image_preview)
        layout.addWidget(self.ocr_text_linedit_current)
        layout.addWidget(self.ocr_text_linedit_last)
        layout.addWidget(thresholding_widget)
        layout.addWidget(self.algorithm_combobox)
        layout.addWidget(self.thresholding_slider)
        layout.addWidget(hotkey_config_button)
        layout.addWidget(srs_screenshot_widget1)
        layout.addWidget(srs_screenshot_widget2)
        layout.addWidget(srs_image_location_button)
        layout.addWidget(recording_widget1)
        layout.addWidget(recording_widget2)
        layout.addWidget(recording_seconds_widget)
        layout.addWidget(self.mic_combobox)
        layout.addWidget(self.audio_peak_progressbar)
        layout.addWidget(save_settings_button)
        self.setLayout(layout)

    def toggle_auto_ocr(self):
        if self.master_object.auto_ocr_thread:
            self.master_object.auto_ocr_thread.stop_signal = True
            self.master_object.auto_ocr_thread.wait()
        else:
            self.master_object.start_auto_ocr_in_thread()

    def algorithm_change(self):
        self.config.config_dict["ocr_settings"]["thresholding_algorithm"] = self.algorithm_combobox.currentText()
        self.master_object.ocr.start_ocr_in_thread(self.master_object.unprocessed_image, skip_override=True)

    def update_linedit_text(self, text: str):
        self.ocr_text_linedit_last.setText(self.ocr_text_linedit_current.text())
        self.ocr_text_linedit_current.setText(text)

    def refresh_preview_image(self, image):
        self.image_preview.setImage(image)

    def show_ocr_settings_window(self):
        self.ocr_settings_window = OCRSettingsWindow(self.master_object)
        self.ocr_settings_window.show()

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

    def auto_save_recording_checkbox_toggl(self, state):
        self.config.config_dict["auto_save_recording"] = state == Qt.Checked

    def recording_checkbox_toggl(self, state):
        self.config.config_dict["enable_recording"] = state == Qt.Checked
        if state == Qt.Checked:
            self.audio_worker.save_audio_and_restart_recording()
            self.audio_save_button.setEnabled(True)
            self.audio_clipboard_button.setEnabled(True)
        else:
            self.audio_worker.stop_recording()
            self.audio_save_button.setEnabled(False)
            self.audio_clipboard_button.setEnabled(False)

    def spinbox_valuechange(self):
        self.config.config_dict["recording_seconds"] = self.recording_seconds_spinbox.value()

    def mic_selection_change(self):
        global selected_mic
        mic_name = self.mic_combobox.currentText()
        selected_mic = next(x for x in self.mics if x.name == mic_name)
        self.update_audio_progress_thread.stop()
        self.update_audio_progress_thread.wait()
        self.update_audio_progressbar_in_thread()

    class UpdateAudioProgressThread(QThread):
        volume_signal = cast(SignalInstance, Signal(int))

        def __init__(self):
            QThread.__init__(self)
            self.stop_signal = False

        def run(self):
            samplerate = 48000
            global selected_mic
            loopback = selected_mic
            if not loopback:
                return
            with loopback.recorder(samplerate=samplerate) as rec:
                while not self.stop_signal:
                    data: numpy.ndarray
                    data = rec.record()
                    added_data = [abs(sum(instance)) for instance in data]
                    volume = int(math.ceil(numpy.mean(added_data) * 1000))  # type: ignore
                    self.volume_signal.emit(volume)

        def stop(self):
            self.stop_signal = True


class ImagePreview(QLabel):
    def __init__(self, image=None):
        super().__init__()
        self.image = image
        self.setMinimumSize(350, 170)

        self._update_pixmap()

    def _update_pixmap(self):
        if self.image:
            im = ImageQt(self.image).copy()
            pixmap = QPixmap.fromImage(im).scaled(self.width(), self.height(), Qt.KeepAspectRatio)
            self.setPixmap(pixmap)
        else:
            self.setText("This will show a preview of your screenshots.")

    def setImage(self, image):
        self.image = image
        self._update_pixmap()

    def resizeEvent(self, _):
        self._update_pixmap()


class SRSScreenshot:
    def __init__(self, app, config: Configuration):
        self.app = app
        self.config = config
        self.srs_image_location = Rectangle()
        self.image: Optional[Image.Image] = None

    def set_srs_image_location(self):
        QApplication.setOverrideCursor(Qt.CrossCursor)
        selection_window = SelectorWidget(self.app)
        selection_window.show()
        selection_window.activateWindow()
        if selection_window.exec() == QDialog.Accepted and selection_window.coordinates:
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
                int(self.srs_image_location.x1),
                int(self.srs_image_location.y1),
                int(self.srs_image_location.x2),
                int(self.srs_image_location.y2),
            ),
        )
        if image:
            MAX_SIZE = (848, 480)
            image.thumbnail(MAX_SIZE)
            with NamedTemporaryFile(suffix=".webp", delete=False) as temp_webp_file:
                image.save(temp_webp_file.name, optimize=True, quality=75)
                self.image = Image.open(temp_webp_file.name)
                shutil.copyfile(temp_webp_file.name, "test.webp")

    def trigger_srs_screenshot_on_clipboard_change(self):
        while True:
            pyperclip.waitForNewPaste()
            if not self.config.config_dict["texthooker_mode"]:
                break
            self.take_srs_screenshot()

    def take_srs_screenshot_in_thread(self):
        with contextlib.suppress(AttributeError):
            if self.srs_screenshot_thread:
                self.srs_screenshot_thread.wait()
        self.srs_screenshot_thread = SRSScreenshot.SRSScreenshotThread(self, self.config)
        self.srs_screenshot_thread.start()

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


class OCRSettingsWindow(QWidget):
    def __init__(self, master_object: MasterObject):
        super().__init__()
        self.master_object = master_object
        self.config = self.master_object.config
        self.setWindowTitle("Migaku OCR Settings")
        self.setWindowFlags(Qt.Dialog)  # type: ignore
        self.unprocessed_image_label = QLabel()
        self.processed_image_label = QLabel()

        unprocessed_image = master_object.unprocessed_image
        processed_image = master_object.processed_image

        layout = QHBoxLayout()
        left_side_layout = QVBoxLayout()
        right_side_layout = QVBoxLayout()

        if unprocessed_image:
            im = ImageQt(unprocessed_image).copy()
            pixmap = QPixmap.fromImage(im)
            self.unprocessed_image_label.setPixmap(pixmap)
        else:
            self.unprocessed_image_label.setText("No screenshot taken yet...")

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

        def change_upscale_value(state):
            self.config.config_dict["ocr_settings"]["upscale_amount"] = state
            master_object.ocr.start_ocr_in_thread(unprocessed_image)

        upscale_spinbox = QSpinBox()
        upscale_spinbox.setValue(self.config.config_dict["ocr_settings"]["upscale_amount"])
        upscale_spinbox.setMinimum(1)
        upscale_spinbox.setMaximum(6)
        upscale_spinbox.valueChanged.connect(change_upscale_value)  # type: ignore
        right_side_layout.addWidget(upscale_spinbox)

        self.blacklist_lineedit = QLineEdit(self.config.config_dict["ocr_settings"]["character_blacklist"])
        self.blacklist_lineedit.editingFinished.connect(self.change_blacklist_text)  # type: ignore
        right_side_layout.addWidget(self.blacklist_lineedit)

        right_side_widget = QWidget()
        right_side_widget.setLayout(right_side_layout)
        layout.addWidget(right_side_widget)
        self.setLayout(layout)

    def change_blacklist_text(self):
        self.config.config_dict["ocr_settings"]["character_blacklist"] = self.blacklist_lineedit.text()

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

        self.original_config = copy.deepcopy(config.config_dict)

        self.setWindowTitle("Migaku OCR Hotkey Settings")
        self.setWindowFlags(Qt.Dialog)  # type: ignore
        layout = QVBoxLayout()

        self.hotkeyCheckBox = QCheckBox("Enable Global Hotkeys")
        self.hotkeyCheckBox.setChecked(config.config_dict["enable_global_hotkeys"])
        self.hotkeyCheckBox.stateChanged.connect(self.checkbox_toggl)  # type: ignore

        layout.addWidget(self.hotkeyCheckBox)
        single_screenshot_hotkey_field = HotKeyField(config, "single_screenshot_hotkey", "Single screenshot OCR")
        layout.addWidget(single_screenshot_hotkey_field)
        persistent_window_hotkey_field = HotKeyField(config, "persistent_window_hotkey", "Spawn persistent window")
        layout.addWidget(persistent_window_hotkey_field)
        persistent_screenshot_hotkey_field = HotKeyField(
            config, "persistent_screenshot_hotkey", "Persistent window OCR"
        )
        layout.addWidget(persistent_screenshot_hotkey_field)
        stop_recording_hotkey_field = HotKeyField(config, "stop_recording_hotkey", "Stop recording")
        layout.addWidget(stop_recording_hotkey_field)

        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)
        self.okButton = QPushButton("OK")
        self.okButton.clicked.connect(self.save_close)  # type: ignore
        button_layout.addWidget(self.okButton)
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.cancel_close)  # type: ignore
        button_layout.addWidget(self.cancelButton)
        self.setLayout(layout)

    def checkbox_toggl(self, state):
        self.config.config_dict["enable_global_hotkeys"] = bool(state == Qt.Checked)

    def save_close(self):
        self.config.save_config()
        self.close()

    def cancel_close(self):
        self.config.config_dict = self.original_config
        self.close()

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)
        self.main_hotkey_qobject.start()


class HotKeyField(QWidget):
    def __init__(self, config: Configuration, hotkey_functionality: str, hotkey_name: str):
        super().__init__()
        hotkey_label = QLabel(hotkey_name)
        layout = QHBoxLayout()
        layout.addWidget(hotkey_label)

        self.keyEdit = KeySequenceLineEdit(config, hotkey_functionality)
        layout.addWidget(self.keyEdit)

        self.clearButton = QPushButton("Clear")
        self.clearButton.clicked.connect(self.keyEdit.clear)  # type: ignore
        layout.addWidget(self.clearButton)

        self.setLayout(layout)


class KeySequenceLineEdit(QLineEdit):
    def __init__(self, config: Configuration, hotkey_functionality: str):
        super().__init__()
        self.config = config
        self.modifiers: Qt.KeyboardModifiers = Qt.NoModifier  # type: ignore
        self.key: Qt.Key = Qt.Key_unknown
        self.keysequence = QKeySequence()
        self.hotkey_functionality = hotkey_functionality
        self.setText(self.getQtText(config.config_dict["hotkeys"][self.hotkey_functionality]))

    def clear(self):
        self.setText("")
        self.config.config_dict["hotkeys"][self.hotkey_functionality] = ""

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.modifiers = event.modifiers()
        self.key = event.key()
        self.updateKeySequence()
        self.updateConfig()

    def updateConfig(self):
        self.config.config_dict["hotkeys"][self.hotkey_functionality] = self.getPynputText()

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

        self.setMouseTracking(True)
        self.original_cursor_x = 0
        self.original_cursor_y = 0
        self.original_window_x = 0
        self.original_window_y = 0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.master_object = master_object

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
        ocrButton.clicked.connect(master_object.take_screenshot_from_persistent_window)  # type: ignore
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
        self.setGeometry(x, y, w, h)

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
            self.drag_x = event.globalPosition().x()
            self.drag_y = event.globalPosition().y()
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
                w = max(50, self.drag_w + event.globalPosition().x() - self.drag_x)
                h = max(50, self.drag_h + event.globalPosition().y() - self.drag_y)
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
            x1 = self.x()
            y1 = self.y()
            x2 = x1 + self.width()
            y2 = y1 + self.height()
            self.master_object.closed_persistent_window.x1 = x1
            self.master_object.closed_persistent_window.y1 = y1
            self.master_object.closed_persistent_window.x2 = x2
            self.master_object.closed_persistent_window.y2 = y2
            self.master_object.config.config_dict["persistent_window_location"] = {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }

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
        self.srs_screenshot = SRSScreenshot(self.app, self.config)
        self.audio_worker = AudioWorker(self.app, self.config)
        self.main_hotkey_qobject = MainHotkeyQObject(self.config, self, self.audio_worker)
        self.ocr = OCR(self)
        self.persistent_window: Optional[PersistentWindow] = None
        self.unprocessed_image: Optional[Image.Image] = None
        self.processed_image: Optional[Image.Image] = None
        self.update_audio_progress_thread: Optional[MainWindow.UpdateAudioProgressThread] = None
        self.auto_ocr_thread: Optional[MasterObject.AutoOcrThread] = None
        self.closed_persistent_window = Rectangle()
        # this allows for ctrl-c to close the application
        signal.signal(signal.SIGINT, lambda *_: self.app.quit())

        self.setup_tray()

        self.show_main_window()

        sys.exit(self.app.exec())

    def setup_tray(self):
        icon = QIcon("migaku_icon.png")

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(icon)
        self.tray.setVisible(True)
        self.menu = QMenu()

        self.openMain = QAction("Open")
        self.openMain.triggered.connect(self.show_main_window)  # type: ignore
        self.quit = QAction("Quit")
        self.quit.triggered.connect(self.app.quit)  # type: ignore

        self.menu.addAction(self.openMain)
        self.menu.addAction(self.quit)

        self.tray.setContextMenu(self.menu)

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
        if selector.exec() == QDialog.Accepted and selector.selectedPixmap:
            image = convert_qpixmap_to_pil_image(selector.selectedPixmap)
            self.ocr.start_ocr_in_thread(image)
        QApplication.restoreOverrideCursor()

    def show_persistent_screenshot_window(self):
        x1, y1, x2, y2 = self.get_persistent_window_coordinates()
        temp_rectangle = Rectangle(x1, y1, x2, y2)
        if temp_rectangle:
            self.persistent_window = PersistentWindow(
                self,
                x=temp_rectangle.x1,
                y=temp_rectangle.y1,
                w=temp_rectangle.get_width(),
                h=temp_rectangle.get_height(),
            )
        else:
            self.persistent_window = PersistentWindow(self)
        self.persistent_window.show()

    def get_persistent_window_coordinates(self) -> tuple[int, int, int, int]:
        if self.persistent_window and not self.persistent_window.isHidden():
            x1 = self.persistent_window.x()
            y1 = self.persistent_window.y()
            x2 = x1 + self.persistent_window.width()
            y2 = y1 + self.persistent_window.height()
        elif self.closed_persistent_window:
            x1 = self.closed_persistent_window.x1
            y1 = self.closed_persistent_window.y1
            x2 = self.closed_persistent_window.x2
            y2 = self.closed_persistent_window.y2
        elif self.config.config_dict.get("persistent_window_location", None):
            x1 = self.config.config_dict.get("persistent_window_location", {}).get("x1", 0)
            y1 = self.config.config_dict.get("persistent_window_location", {}).get("y1", 0)
            x2 = self.config.config_dict.get("persistent_window_location", {}).get("x2", 0)
            y2 = self.config.config_dict.get("persistent_window_location", {}).get("y2", 0)
        else:
            x1 = 0
            y1 = 0
            x2 = 0
            y2 = 0

        return (int(x1), int(y1), int(x2), int(y2))

    def take_screenshot_from_persistent_window(self):
        self.srs_screenshot.take_srs_screenshot_in_thread()
        persistent_window = self.persistent_window
        x1, y1, x2, y2 = self.get_persistent_window_coordinates()
        temp_rectangle = Rectangle(x1, y1, x2, y2)
        if not temp_rectangle:
            logger.warning("persistent window not initialized yet or persistent_window location not saved")
        else:
            x1, y1, x2, y2 = self.get_persistent_window_coordinates()
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

            self.ocr.start_ocr_in_thread(image)

    def start_auto_ocr_in_thread(self):
        self.auto_ocr_thread = MasterObject.AutoOcrThread(self)
        self.auto_ocr_thread.persistent_auto_signal.connect(self.take_screenshot_from_persistent_window)
        self.auto_ocr_thread.start()

    class AutoOcrThread(QThread):
        persistent_auto_signal = cast(SignalInstance, Signal())

        def __init__(self, master_object: MasterObject):
            QThread.__init__(self)
            self.stop_signal = False
            self.master_object = master_object

        def run(self):
            hash1 = None
            changing = False
            while not self.stop_signal:
                x1, y1, x2, y2 = self.master_object.get_persistent_window_coordinates()
                temp_rectangle = Rectangle(x1, y1, x2, y2)
                if temp_rectangle:
                    new_hash = imagehash.average_hash(ImageGrab.grab(bbox=(x1, y1, x2, y2)))
                    if not hash1:
                        self.persistent_auto_signal.emit()
                        hash1 = new_hash
                    else:
                        if hash1 == new_hash:
                            if changing:
                                self.persistent_auto_signal.emit()
                                changing = False
                        else:
                            changing = True
                    hash1 = new_hash
                    time.sleep(0.3)
                else:
                    time.sleep(1)

        def stop(self):
            self.stop_signal = True


class MainHotkeyQObject(QObject):
    def __init__(self, config: Configuration, master_object: MasterObject, audio_worker: AudioWorker):
        super().__init__()

        if config.config_dict["enable_global_hotkeys"]:
            logger.info("Started hotkeys")
            self.manager = KeyBoardManager(config)
            self.manager.single_screenshot_signal.connect(master_object.take_single_screenshot)
            self.manager.persistent_window_signal.connect(master_object.show_persistent_screenshot_window)
            self.manager.persistent_screenshot_signal.connect(master_object.take_screenshot_from_persistent_window)
            self.manager.stop_recording_signal.connect(audio_worker.save_audio_and_restart_recording)
            self.start()

    def start(self):
        self.manager.start()

    def stop(self):
        with contextlib.suppress(AttributeError):
            self.manager.hotkey.stop()


class KeyBoardManager(QObject):
    single_screenshot_signal = cast(SignalInstance, Signal())
    persistent_window_signal = cast(SignalInstance, Signal())
    persistent_screenshot_signal = cast(SignalInstance, Signal())
    stop_recording_signal = cast(SignalInstance, Signal())

    def __init__(self, config: Configuration):
        super().__init__()
        self.config = config

    def start(self):
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


class OCR:
    def __init__(self, master_object: MasterObject):
        self.master_object = master_object
        self.ocr_thread: Optional[OCR.OCRThread] = None
        self.api = None
        self.jpn_api = None
        self.jpn_vert_api = None

    class OCRThread(QThread):
        unprocessed_signal = cast(SignalInstance, Signal(Image.Image))
        processed_signal = cast(SignalInstance, Signal(Image.Image))
        ocr_text_signal = cast(SignalInstance, Signal(str))

        def __init__(self, ocr: OCR, image, skip_override: bool):
            QThread.__init__(self)
            self.image = image
            self.ocr = ocr
            self.skip_override = skip_override

        def run(self):
            self.ocr.start_ocr(
                self.image, self.unprocessed_signal, self.processed_signal, self.ocr_text_signal, self.skip_override
            )

    def start_ocr_in_thread(self, image, skip_override=False):
        if image:
            if self.ocr_thread:
                self.ocr_thread.wait()
            self.ocr_thread = OCR.OCRThread(self, image, skip_override)
            ocr_settings_window = self.master_object.main_window.ocr_settings_window
            main_window = self.master_object.main_window
            if ocr_settings_window:
                self.ocr_thread.unprocessed_signal.connect(ocr_settings_window.refresh_unprocessed_image)
                self.ocr_thread.processed_signal.connect(ocr_settings_window.refresh_processed_image)
                self.ocr_thread.ocr_text_signal.connect(ocr_settings_window.refresh_ocr_text)
            if main_window:
                self.ocr_thread.ocr_text_signal.connect(main_window.update_linedit_text)
            if self.master_object.main_window:
                self.ocr_thread.processed_signal.connect(self.master_object.main_window.refresh_preview_image)
            self.ocr_thread.start()

    def start_ocr(
        self,
        image: Image.Image,
        unprocessed_signal: SignalInstance,
        processed_signal: SignalInstance,
        ocr_text_signal: SignalInstance,
        skip_override: bool,
    ):
        self.master_object.unprocessed_image = image.copy()
        unprocessed_signal.emit(self.master_object.unprocessed_image)
        print("got to that point")
        if self.master_object.config.config_dict["auto_save_recording"]:
            print("auto save true")
            self.master_object.audio_worker.save_audio_and_restart_recording()

        override_options: list[dict[str, Any]] = [
            {},
            {"ocr_settings": {"automatic_thresholding": True, "thresholding_algorithm": "OTSU"}},
            {"ocr_settings": {"automatic_thresholding": True, "thresholding_algorithm": "NICK"}},
            {"ocr_settings": {"automatic_thresholding": True, "thresholding_algorithm": "WAN"}},
            {"invert_color": True},
        ]
        if skip_override:
            override_options = [{}]

        image_processor = ImageProcessor(self.master_object.config, image)
        text = ""
        initial_text = ""
        initial_image = None
        for retries, override_option in enumerate(override_options):
            image = image_processor.process_image(override_option)
            text = self.do_ocr(image)
            if retries == 0:
                initial_text = text
                initial_image = image.copy()
            if not self.retry_necessary(text):
                break
            elif retries == len(override_options) - 1:
                text = initial_text
                assert initial_image is not None
                image = initial_image
                if not skip_override:
                    logger.info("Failed with all override_options, original text might contain blacklisted chars")
            if not skip_override:
                logger.info(
                    f"Ocr failed, retrying with option {override_option} retries: {retries} recognized text: {text}"
                )

        processed_signal.emit(image)
        self.master_object.processed_image = image
        ocr_text_signal.emit(text)

        process_text(text)

    def retry_necessary(self, text):
        config = self.master_object.config
        if not text.strip():
            return True
        return any(char.lower() in config.config_dict["ocr_settings"]["character_blacklist"] for char in text)

    def do_ocr(self, image: Image.Image):
        width, height = image.size
        language = ""
        path = ""
        if platform.system() == "Windows":
            path = os.path.abspath(tesseract_command)
            pytesseract.pytesseract.tesseract_cmd = path
        # else:
        #     path = "/home/julius/Projects/tesseract/tesseract/tesseract"
        #     pytesseract.pytesseract.tesseract_cmd = path
        if width > height:
            language = "jpn"
            tesseract_config = "--oem 1 --psm 6"
        else:
            language = "jpn_vert"
            tesseract_config = "--oem 1 --psm 5"
        text = pytesseract.image_to_string(image, lang=language, config=tesseract_config)
        text = text.strip()

        for (f, t) in [
            (" ", ""),
            ("いぃ", "い"),
            ("\n", ""),
            ("①", "１"),
            ("②", "２"),
            ("③", "３"),
            ("④", "４"),
            ("⑤", "５"),
            ("⑥", "６"),
            ("⑦", "７"),
            ("⑧", "８"),
            ("⑨", "９"),
            ("⑩", "１０"),
            ("⑪", "１１"),
            ("⑫", "１２"),
            ("⑬", "１３"),
            ("⑭", "１４"),
            ("⑮", "１５"),
            ("⑯", "１６"),
            ("⑰", "１７"),
            ("⑱", "１８"),
            ("⑲", "１９"),
            ("⑳", "２０"),
        ]:
            text = text.replace(f, t)
        logger.info(text)
        return text


class ImageProcessor:
    def __init__(self, config: Configuration, original_image: Image.Image) -> None:
        self.config = config
        self.original_image = original_image
        self.inverted = False

    def process_image(self, override_option: dict[str, Any]) -> Image.Image:
        override_option_copy = override_option.copy()
        config_dict = merge(override_option_copy, self.config.config_dict.copy())
        image = self.original_image.copy()
        is_grayscale = self.check_if_is_grayscale(image)

        image = self.increase_image_size(config_dict, image)
        image = self.threshold_image(config_dict, image, is_grayscale)
        image = self.smart_invert_image(config_dict, image)
        image = self.add_border(image)

        return image

    def add_border(self, image: Image.Image) -> Image.Image:
        if self.config.config_dict["ocr_settings"]["add_border"]:
            return ImageOps.expand(image, 10, fill="white")
        else:
            return image

    def check_if_is_grayscale(self, image: Image.Image) -> bool:
        pixels = cast(PyAccess, image.load())

        width, height = image.size
        diff = 0
        for x in range(width):
            for y in range(height):
                if len(pixels[x, y]) == 3:
                    r, g, b = pixels[x, y]
                elif len(pixels[x, y]) == 4:
                    r, g, b, _ = pixels[x, y]
                else:
                    return False
                rg = abs(r - g)
                rb = abs(r - b)
                gb = abs(g - b)
                diff += rg + rb + gb
        abs_diff = diff / (height * width)
        return abs_diff < 5

    def increase_image_size(self, config_dict: dict, image: Union[numpy.ndarray, Image.Image]) -> Image.Image:
        image = self.smart_convert_to_pillow(image)
        upscale_amount = config_dict["ocr_settings"]["upscale_amount"]
        image = image.resize((image.width * upscale_amount, image.height * upscale_amount))
        return image

    def threshold_image(self, config_dict: dict, image: Image.Image, is_grayscale: bool):
        if not config_dict["ocr_settings"]["enable_thresholding"]:
            return image
        pillow_image: Optional[Image.Image] = None
        if config_dict["ocr_settings"]["automatic_thresholding"]:
            if is_grayscale:
                return image
            grayscale_image = self.pillow_to_doxa(image)
            binary_image = numpy.empty(grayscale_image.shape, grayscale_image.dtype)

            algorithm = algorithms[config_dict["ocr_settings"]["thresholding_algorithm"]]
            # Pick an algorithm from the DoxaPy library and convert the image to binary
            doxa = doxapy.Binarization(algorithm)
            doxa.initialize(grayscale_image)
            doxa.to_binary(binary_image, {"window": 75, "k": 0.2})
            pillow_image = self.doxa_to_pillow(binary_image)

        else:
            opencv_image = self.smart_convert_to_opencv(image)
            opencv_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)  # type: ignore
            opencv_image = cv2.threshold(  # type: ignore
                opencv_image, config_dict["ocr_settings"]["thresholding_value"], 255, cv2.THRESH_BINARY  # type: ignore
            )[1]
            pillow_image = self.opencv_to_pillow(opencv_image)
        return pillow_image

    def smart_convert_to_pillow(self, image: Union[numpy.ndarray, Image.Image]) -> Image.Image:
        if isinstance(image, numpy.ndarray):
            image = self.opencv_to_pillow(image)
        return image

    def smart_convert_to_opencv(self, image: Union[numpy.ndarray, Image.Image]) -> numpy.ndarray:
        if isinstance(image, Image.Image):
            image = self.pillow_to_opencv(image)
        return image

    def smart_invert_image(self, config_dict: dict, image: Image.Image) -> Image.Image:
        if config_dict.get("invert_color", False):
            if self.inverted:
                print("forcibly not inverting")
                return image
            else:
                print("forcibly inverting")
                return ImageOps.invert(image)
        else:
            self.inverted = False
        if config_dict["ocr_settings"]["smart_image_inversion"]:
            colors = sorted(image.getcolors(image.size[0] * image.size[1]))
            if isinstance(colors[-1][-1], int):
                if colors[-1][-1] < 128:
                    self.inverted = True
                    image = ImageOps.invert(image)
            else:
                colors = cast(list[tuple[int, tuple[int, int, int]]], colors)
                _, (r, g, b) = colors[-1]

                if r < 128 and g < 128 and b < 128:
                    self.inverted = True
                    image = ImageOps.invert(image)

        return image

    # both from: https://stackoverflow.com/a/48602446/8825153
    def opencv_to_pillow(self, opencv_image: numpy.ndarray) -> Image.Image:
        color_coverted = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(color_coverted)

    def pillow_to_opencv(self, pillow_image: Image.Image) -> numpy.ndarray:
        numpy_image = numpy.array(pillow_image)
        return cv2.cvtColor(numpy_image, cv2.COLOR_RGB2BGR)

    def pillow_to_doxa(self, pillow_image: Image.Image) -> numpy.ndarray:
        return numpy.array(pillow_image.convert("L"))

    def doxa_to_pillow(self, doxa_image: numpy.ndarray) -> Image.Image:
        return Image.fromarray(doxa_image)


def process_text(text: str):
    if text:
        pass
        pyperclip.copy(text)


def capture_desktop(app: QApplication):
    desktop_pixmap = QPixmap(app.screens()[0].virtualSize())

    painter = QPainter(desktop_pixmap)
    for screen in app.screens():
        painter.drawPixmap(
            screen.geometry().topLeft(),
            screen.grabWindow(0),  # type: ignore
        )
    return desktop_pixmap


class SelectorWidget(QDialog):
    def __init__(self, app: QApplication):
        super().__init__()
        if platform.system() == "Linux":
            self.setWindowFlags(
                Qt.FramelessWindowHint  # type: ignore
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

        self.setGeometry(app.screens()[0].virtualGeometry())
        self.desktopPixmap = capture_desktop(app)
        self.selectedRect = QRect()
        self.selectedPixmap = None

        self.coordinates = Rectangle()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key_Escape]:
            self.reject()

    def mousePressEvent(self, event: QMouseEvent):
        self.selectedRect.setTopLeft(event.globalPosition().toPoint())
        self.coordinates.x1 = event.globalPosition().x()
        self.coordinates.y1 = event.globalPosition().y()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.selectedRect.setBottomRight(event.globalPosition().toPoint())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.selectedPixmap = self.desktopPixmap.copy(self.selectedRect.normalized())
        self.coordinates.x2 = event.globalPosition().x()
        self.coordinates.y2 = event.globalPosition().y()
        self.accept()

    def paintEvent(self, _: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.desktopPixmap)
        path = QPainterPath()
        painter.fillPath(path, QColor.fromRgb(255, 255, 255, 200))
        painter.setPen(Qt.red)
        painter.drawRect(self.selectedRect)


def convert_qpixmap_to_pil_image(pixmap: QPixmap):
    q_image = pixmap.toImage()
    buffer = QBuffer()
    buffer.open(QBuffer.ReadWrite)  # type: ignore
    q_image.save(buffer, "PNG")  # type: ignore
    return Image.open(io.BytesIO(buffer.data()))  # type: ignore


class AudioWorker:
    def __init__(self, app: QApplication, config: Configuration):
        self.app = app
        self.config = config
        self.last_audio_file = ""
        self.audio_recorder_threads: list[AudioWorker.AudioRecorderThread] = []
        self.audio_processing_threads: list[AudioWorker.AudioProcessorThread] = []

    def save_audio_and_restart_recording(self):
        self.stop_recording()
        self._start_recording()

    def clean_up_finished_audio_recorder_threads(self):
        for thread in self.audio_recorder_threads:
            if thread.isFinished():
                self.audio_recorder_threads.remove(thread)

    def clean_up_finished_audio_processing_threads(self):
        for thread in self.audio_processing_threads:
            if thread.isFinished():
                self.audio_processing_threads.remove(thread)

    def _start_recording(self):
        audio_recorder_thread = AudioWorker.AudioRecorderThread(self.config, self)
        self.audio_recorder_threads.append(audio_recorder_thread)
        audio_recorder_thread.done_signal.connect(self._process_audio)
        audio_recorder_thread.finished.connect(self.clean_up_finished_audio_recorder_threads)
        audio_recorder_thread.start()

    def stop_recording(self) -> None:
        for thread in self.audio_recorder_threads:
            thread.stop_recording = True

    @Slot(deque)
    def _process_audio(self, audio_deque: deque):
        print("got finish signal")
        audio_processing_thread = AudioWorker.AudioProcessorThread(audio_deque, self)
        audio_processing_thread.finished.connect(self.clean_up_finished_audio_processing_threads)
        self.audio_processing_threads.append(audio_processing_thread)
        audio_processing_thread.start()

    def save_last_file_to_clipboard(self):
        data = QMimeData()
        url = QUrl.fromLocalFile(self.last_audio_file)
        data.setUrls([url])

        self.app.clipboard().setMimeData(data)

    class AudioRecorderThread(QThread):
        done_signal = cast(SignalInstance, Signal(deque))

        def __init__(self, config: Configuration, audio_worker: AudioWorker) -> None:
            QThread.__init__(self)
            self.config = config
            self.stop_recording = False
            self.audio_worker = audio_worker

        def run(self):
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
                        logger.info("Got recording stop signal")
                        break
                    data = rec.record(numframes=samplerate)
                    audio_deque.append(data)
                    if len(audio_deque) > self.config.config_dict["recording_seconds"]:
                        audio_deque.popleft()
            self.done_signal.emit(audio_deque)
            print("emitting completed signal")

    class AudioProcessorThread(QThread):
        def __init__(self, audio_deque, audio_worker: AudioWorker):
            QThread.__init__(self)
            self.audio_worker = audio_worker
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
                    with NamedTemporaryFile(suffix=".opus", delete=False) as temp_opus_file:
                        wavfile.write(temp_wav_file, 48000, final_data)
                        cmd = ["ffmpeg", "-y", "-i", temp_wav_file.name, temp_opus_file.name]
                        EasyProcess(cmd).call(timeout=40)
                        self.audio_worker.last_audio_file = temp_opus_file.name
                        # uncomment below for testing
                        # shutil.copyfile(temp_wav_file.name, "test.wav")
                        shutil.copyfile(temp_opus_file.name, "test.opus")


def get_loopback_device(mics):
    try:
        default_speaker = soundcard.default_speaker()
    except RuntimeError:
        return None
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
