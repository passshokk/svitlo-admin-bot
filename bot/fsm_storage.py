# bot/fsm_storage.py
from typing import Any, Dict, Optional
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from core.database import db
from google.cloud import firestore

class FirestoreStorage(BaseStorage):
    """
    Технічний FSM Storage для Firestore.
    Зберігає стани в ізольованій колекції FSM_Sessions за Telegram ID.
    Запобігає появі сміття та усуває марні HTTP-запити при state.clear().
    """
    def __init__(self, collection_name: str = "FSM_Sessions"):
        self.collection = db.collection(collection_name)

    def _get_doc_ref(self, key: StorageKey):
        return self.collection.document(str(key.user_id))

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        doc_ref = self._get_doc_ref(key)
        if not state:
            doc = await doc_ref.get()
            if doc.exists:
                doc_data = doc.to_dict() or {}
                # Якщо даних немає або вони порожні — видаляємо документ повністю
                if not doc_data.get("data"):
                    await doc_ref.delete()
                else:
                    await doc_ref.update({"state": firestore.DELETE_FIELD})
        else:
            state_str = state.state if hasattr(state, 'state') else state
            await doc_ref.set({"state": state_str}, merge=True)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("state") if doc.exists else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        doc_ref = self._get_doc_ref(key)
        if not data:
            doc = await doc_ref.get()
            if doc.exists:
                doc_data = doc.to_dict() or {}
                # Якщо стан відсутній — документ більше не потрібен, видаляємо
                if not doc_data.get("state"):
                    await doc_ref.delete()
                else:
                    await doc_ref.update({"data": firestore.DELETE_FIELD})
        else:
            await doc_ref.set({"data": data}, merge=True)

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        doc = await self._get_doc_ref(key).get()
        return doc.to_dict().get("data", {}) if doc.exists else {}

    async def close(self) -> None:
        pass