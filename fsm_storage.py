# fsm_storage.py
from typing import Any, Dict, Optional
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.state import State
import database as db

class FirestoreStorage(BaseStorage):
    """
    Кастомний FSM Storage для збереження станів реєстрації безпосередньо у Firestore (колекція Users).
    """
    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        state_str = state.state if isinstance(state, State) else state
        # Використовуємо merge=True, щоб не затерти інші дані профілю
        await db.db.collection('Users').document(str(key.user_id)).set(
            {'application_profile': {'state': state_str}}, merge=True
        )

    async def get_state(self, key: StorageKey) -> Optional[str]:
        doc = await db.db.collection('Users').document(str(key.user_id)).get()
        if doc.exists:
            return doc.to_dict().get('application_profile', {}).get('state')
        return None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        await db.db.collection('Users').document(str(key.user_id)).set(
            {'application_profile': {'data': data}}, merge=True
        )

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        doc = await db.db.collection('Users').document(str(key.user_id)).get()
        if doc.exists:
            return doc.to_dict().get('application_profile', {}).get('data', {})
        return {}

    async def close(self) -> None:
        pass