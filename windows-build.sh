#!/bin/sh

rm -rf .venv build dist && \
vagrant up && \
vagrant winrm --command "cd c:\vagrant ; poetry config virtualenvs.in-project true ; poetry install ; poetry run pyinstaller --onefile --windowed --clean --hidden-import mss --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 --add-data 'Game2Text\resources\bin\win\tesseract;tesseract' ocr_tool.py"
