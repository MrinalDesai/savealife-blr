"""Central settings. Everything comes from .env; nothing is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    ibm_cloud_api_key: str = field(default_factory=lambda: _env("IBM_CLOUD_API_KEY"))
    wxo_instance_url: str = field(default_factory=lambda: _env("WXO_INSTANCE_URL"))
    watsonx_api_key: str = field(default_factory=lambda: _env("WATSONX_API_KEY") or _env("IBM_CLOUD_API_KEY"))
    watsonx_url: str = field(default_factory=lambda: _env("WATSONX_URL", "https://us-south.ml.cloud.ibm.com"))
    watsonx_project_id: str = field(default_factory=lambda: _env("WATSONX_PROJECT_ID"))
    watsonx_text_model: str = field(default_factory=lambda: _env("WATSONX_TEXT_MODEL", "ibm/granite-4-h-small"))
    watsonx_vision_model: str = field(
        default_factory=lambda: _env("WATSONX_VISION_MODEL", "meta-llama/llama-4-maverick-17b-128e-instruct-fp8")
    )
    google_routes_api_key: str = field(default_factory=lambda: _env("GOOGLE_ROUTES_API_KEY"))
    simulation: bool = field(default_factory=lambda: _env("SIMULATION", "true").lower() == "true")

    def missing(self) -> list[str]:
        """Names of required settings that are empty."""
        required = {
            "IBM_CLOUD_API_KEY": self.ibm_cloud_api_key,
            "WXO_INSTANCE_URL": self.wxo_instance_url,
            "WATSONX_PROJECT_ID": self.watsonx_project_id,
        }
        return [k for k, v in required.items() if not v]


settings = Settings()
