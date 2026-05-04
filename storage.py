"""
Базовая директория для всех данных.
Локально: ./  (текущая папка)
Railway:  /app/storage  (persistent volume)
"""
import os
from pathlib import Path

BASE = Path(os.getenv("DATA_DIR", "."))
