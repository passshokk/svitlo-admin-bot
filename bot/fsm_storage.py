# bot/fsm_storage.py
from typing import Any, Dict, Optional
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from core.database import db

class FirestoreStorage(BaseStorage):
    """
    Технічний FSM Storage.
    Записує стани в ізольовану колекцію FSM_Sessions за Telegram ID.
    Повністю запобігає появі технічного сміття в основній CRM 'Svitlo'.
    """
    def __init__(self, collection_name: str = "FSM_Sessions"):
        self.collection = db.collection(collection_name)

    def _get_doc_ref(self, key: StorageKey):
        return self.collection.document(str(key.user_id))

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        doc_ref = self._get_doc_ref(key)
        if state is None:
            await doc_ref.set({"state": None}, merge=True)
            return
        state_str = state.state if hasattr(state, 'state') else state
        await doc_ref.set({"state": state_str}, merge=True)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("state") if doc.exists else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        await self._get_doc_ref(key).set({"data": data}, merge=True)

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("data", {}) if doc.exists else {}

    async def close(self) -> None:
        pass