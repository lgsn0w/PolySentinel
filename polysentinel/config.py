from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database: str = os.getenv("SENTINEL_DB", str(ROOT / "data" / "sentinel.sqlite3"))
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "15"))
    lookback_seconds: int = int(os.getenv("LOOKBACK_SECONDS", "600"))
    overlap_seconds: int = 120
    window_seconds: int = 600
    minimum_usd: float = 10
    accumulation_minimum: float = 500
    alert_usd: float = 3000
    page_size: int = 500
    max_offset: int = 10000
    etherscan_key: str = os.getenv("ETHERSCAN_API_KEY", "")

    def __post_init__(self):
        if self.poll_seconds <= 0 or self.lookback_seconds <= 0:
            raise ValueError("Polling and lookback intervals must be positive")
        path = Path(self.database)
        if not path.is_absolute():
            object.__setattr__(self, "database", str(ROOT / path))
