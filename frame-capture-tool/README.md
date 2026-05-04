# Frame Capture Tool

A Python GUI application for capturing video frames from a Raspberry Pi camera.

## Requirements

- Raspberry Pi with camera module
- Python 3.7+
- Dependencies listed in requirements.txt

## Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Ensure rpicam-vid is available (part of Raspberry Pi OS).

## Usage

Run the application:
```bash
python main.py
```

The GUI allows you to:
- Select resolution
- Set countdown and recording duration
- Start recording
- Enable wireless transfer portal

## Notes

This application is designed for Raspberry Pi hardware. The rpicam-vid command is specific to Raspberry Pi cameras.