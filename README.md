# Migaku OCR

| :exclamation:  This project is in a functional state, but *not* actively maintained and *not* supported by Migaku |
|-------------------------------------------------------------------------------------------------------------------|


## Info

### TODOs

* Download ffmpeg dynamically if not available
* Fix pyinstaller builds for windows and macos
* Add support for other languages
* Add support for other OCR engines


### Known Issues

* There might be issues with recording on windows
* On macOS, screenshots are taken in the wrong location


| :zap: We'd be happy to get help with these issues! |
|----------------------------------------------------|


## Installation Instructons

### From source

* Install `poetry` (might be called `python-poetry`) with your package manager
* Install `tesseract`, `ffmpeg`, `tesseract-data-jpn` and `tesseract-data-jpn_vert` (the last two are part of `tesseract-lang` in homebrew)
* Install dependencies with `poetry install`
* Run application with `poetry run python ocr_tool.py`
