import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    admin_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v25.0"
    storage_backend: str = "sqlite"
    sqlite_path: str = "data/nexo.sqlite3"
    google_cloud_project: str = ""
    firestore_database: str = "(default)"
    vertex_location: str = "global"
    vertex_model: str = "gemini-2.5-flash"
    enable_vertex_ai: bool = False
    knowledge_path: str = "knowledge/sources.json"
    web_path: str = "web"

    @classmethod
    def from_env(cls):
        values = {}
        for name in cls.__dataclass_fields__:
            value = os.getenv(name.upper())
            if value is not None:
                values[name] = value.lower() == "true" if name == "enable_vertex_ai" else value
        return cls(**values)

    def prepare(self):
        if self.storage_backend not in {"sqlite", "firestore"}:
            raise ValueError("STORAGE_BACKEND must be sqlite or firestore")
        if self.storage_backend == "firestore" and not self.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore")
        if self.enable_vertex_ai and not self.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Vertex AI")
        if self.storage_backend == "sqlite" and self.sqlite_path != ":memory:":
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
