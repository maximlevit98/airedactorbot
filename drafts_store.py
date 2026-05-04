"""
Хранение черновиков незаконченных постов.
Файлы: drafts/{user_id}_{draft_id}.json
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from storage import BASE
DRAFTS_DIR = BASE / "drafts"

STAGE_LABELS = {
    "draft": "черновик готов",
    "plan":  "план готов",
    "hooks": "хуки готовы",
    "topic": "только тема",
}


def _get_stage(data: dict) -> str:
    if data.get("post_draft"):
        return "draft"
    if data.get("post_plan"):
        return "plan"
    if data.get("post_hooks_text"):
        return "hooks"
    return "topic"


def save_draft(user_id: int, fsm_data: dict) -> str:
    """
    Сохраняет или обновляет черновик поста из FSM-данных.
    Возвращает draft_id.
    """
    DRAFTS_DIR.mkdir(exist_ok=True)

    draft_id = fsm_data.get("draft_id") or uuid.uuid4().hex[:8]
    path = DRAFTS_DIR / f"{user_id}_{draft_id}.json"

    stage = _get_stage(fsm_data)
    topic = fsm_data.get("post_topic") or "Без темы"

    data = {
        "draft_id": draft_id,
        "user_id": user_id,
        "saved_at": datetime.now().isoformat(),
        "topic": topic,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
    }
    # Сохраняем все post_* поля кроме стиля (он большой, грузим из отчёта)
    for k, v in fsm_data.items():
        if k.startswith("post_") and k != "post_style" and v is not None:
            data[k] = v

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Черновик сохранён: %s (стадия: %s)", path.name, stage)
    return draft_id


def load_drafts(user_id: int) -> list[dict]:
    """Список всех черновиков пользователя, от новых к старым."""
    if not DRAFTS_DIR.exists():
        return []
    result = []
    for path in sorted(DRAFTS_DIR.glob(f"{user_id}_*.json"), reverse=True):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("Не удалось загрузить черновик %s: %s", path, e)
    return result


def load_draft(user_id: int, draft_id: str) -> Optional[dict]:
    """Загружает конкретный черновик."""
    path = DRAFTS_DIR / f"{user_id}_{draft_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Не удалось загрузить черновик %s: %s", path, e)
        return None


def delete_draft(user_id: int, draft_id: str) -> bool:
    """Удаляет черновик. Возвращает True если файл существовал."""
    path = DRAFTS_DIR / f"{user_id}_{draft_id}.json"
    if path.exists():
        path.unlink()
        logger.info("Черновик удалён: %s", path.name)
        return True
    return False
