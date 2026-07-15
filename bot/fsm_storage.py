# bot/fsm_storage.py
from typing import Any, Dict, Optional
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from core.database import db
from core.context import student_ctx

class FirestoreStorage(BaseStorage):
    """Асинхронний адаптер FSM. Зберігає стан у вкладеному об'єкті fsm_cache основної БД."""
    def __init__(self, collection_name: str = "Svitlo"):
        self.collection = db.collection(collection_name)

    def _get_doc_ref(self, key: StorageKey):
        student = student_ctx.get()
        # Якщо студент знайдений у мідлварі (навіть зі старим Rowy ID), беремо його ID.
        # Якщо це абсолютно новий лід, беремо його Telegram ID.
        doc_id = student['id'] if student else str(key.user_id)
        return self.collection.document(doc_id)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        doc_ref = self._get_doc_ref(key)
        
        if state is None:
            await doc_ref.set({"fsm_cache": {"state": None}}, merge=True)
            return

        state_str = state.state if hasattr(state, 'state') else state
        await doc_ref.set({"fsm_cache": {"state": state_str}}, merge=True)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("fsm_cache", {}).get("state") if doc.exists else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        await self._get_doc_ref(key).set({"fsm_cache": {"data": data}}, merge=True)

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("fsm_cache", {}).get("data", {}) if doc.exists else {}

    async def close(self) -> None:
        pass