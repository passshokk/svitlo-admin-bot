"""CLI-обгортка над `core/drift_ops.py` — сама логіка живе там, бо її ще й
викликає owner-панель (`api/admin_routes.py`), а `scripts/` навмисно не їде
в прод-контейнер (.gcloudignore).

    python -m scripts.drift_report
    python -m scripts.drift_report --show 40
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from core.drift_ops import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
