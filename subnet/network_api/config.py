from typing import List

from pydantic import BaseModel


class ApiConfig(BaseModel):
    """Configuration for the API Server."""

    host: str = "127.0.0.1"
    port: int = 8000
    whitelist_ips: List[str] = ["127.0.0.1"]
    enable_api: bool = True
