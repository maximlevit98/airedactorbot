"""
Хранение готовых к публикации постов.
Файлы: ready_posts/{user_id}_{post_id}.json
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from storage import BASE
POSTS_DIR = BASE / "ready_posts"


def save_post(user_id: int, topic: str, text: str) -> str:
    """Сохраняет готовый пост. Возвращает post_id."""
    POSTS_DIR.mkdir(exist_ok=True)
    post_id = uuid.uuid4().hex[:8]
    path = POSTS_DIR / f"{user_id}_{post_id}.json"
    data = {
        "post_id": post_id,
        "user_id": user_id,
        "saved_at": datetime.now().isoformat(),
        "topic": topic or "Без темы",
        "text": text,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Пост сохранён: %s", path.name)
    return post_id


def load_posts(user_id: int) -> list[dict]:
    """Список готовых постов пользователя, от новых к старым."""
    if not POSTS_DIR.exists():
        return []
    result = []
    for path in sorted(POSTS_DIR.glob(f"{user_id}_*.json"), reverse=True):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("Не удалось загрузить пост %s: %s", path, e)
    return result


def load_post(user_id: int, post_id: str) -> Optional[dict]:
    """Загружает конкретный пост."""
    path = POSTS_DIR / f"{user_id}_{post_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Не удалось загрузить пост %s: %s", path, e)
        return None


def delete_post(user_id: int, post_id: str) -> bool:
    """Удаляет пост. Возвращает True если файл существовал."""
    path = POSTS_DIR / f"{user_id}_{post_id}.json"
    if path.exists():
        path.unlink()
        logger.info("Пост удалён: %s", path.name)
        return True
    return False
