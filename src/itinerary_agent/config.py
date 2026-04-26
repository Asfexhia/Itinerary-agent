from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    google_maps_api_key: str | None = None
    llm_provider: str = "mock"


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
    )
