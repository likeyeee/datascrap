import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试使用独立的 SQLite 文件和固定令牌
TEST_DB = ROOT / "data" / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["API_TOKEN"] = "test-system-token-0123456789"
os.environ["SECRET_KEY"] = "test-secret"
os.environ.setdefault("DEEPSEEK_API_KEY", "")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from scout import config, db
    db.engine()
    db.Base.metadata.drop_all(db.engine())
    db.Base.metadata.create_all(db.engine())
    config.clear_cache()
    yield
