"""CLI-обгортка над `core/sync_ops.py` — сама логіка живе там, бо її ще й
викликає owner-панель (`api/admin_routes.py`), а `scripts/` навмисно не їде
в прод-контейнер (.gcloudignore).

    python -m scripts.sync_to_schooltoday            # показати, що зміниться
    python -m scripts.sync_to_schooltoday --apply
    python -m scripts.sync_to_schooltoday --limit 5 --apply
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from core.sync_ops import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
