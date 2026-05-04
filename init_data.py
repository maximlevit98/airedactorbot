"""
Одноразовая инициализация данных при первом запуске на сервере.
Восстанавливает пользователей и отчёты из бэкапа.
"""
import base64
import json
from pathlib import Path

USERS = {
    "837956420": "eyJ1c2VyX2lkIjogODM3OTU2NDIwLCAiam9pbmVkX2F0IjogIjIwMjYtMDUtMDNUMjM6MTY6MjMuOTQ0NTc5IiwgImNoYW5uZWwiOiAiQGh0dHBzOi8vdC5tZS9zYW1va2F0c3R1ZmYiLCAiY3JlZGl0cyI6IDUwLCAiZnJlZV9wb3N0X3VzZWQiOiB0cnVlLCAidG90YWxfcG9zdHMiOiAwLCAidG90YWxfdG9rZW5zX2luIjogMCwgInRvdGFsX3Rva2Vuc19vdXQiOiAwLCAidG90YWxfY29zdF91c2QiOiAwLjAsICJ0b3RhbF9wYWlkX3VzZCI6IDEuMTgyOTk5OTk5OTk5OTk5OH0=",
}


def restore():
    users_dir = Path("users")
    users_dir.mkdir(exist_ok=True)

    for uid, encoded in USERS.items():
        path = users_dir / f"{uid}.json"
        if not path.exists():
            data = json.loads(base64.b64decode(encoded))
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ Восстановлен пользователь {uid}")
        else:
            print(f"⏭ Пользователь {uid} уже существует, пропускаем")


if __name__ == "__main__":
    restore()
