"""
Examination Middleware - Configuration Module
Pydantic Settings for type-safe configuration management
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BASE_DIR / "app"
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Application Settings with validation"""
    
    # Application
    app_name: str = Field(default="Exam Submission Middleware")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    secret_key: str = Field(default="")  # MUST be set in production
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=60)
    
    # Server
    host: str = Field(default="0.0.0.0")  # Listen on all interfaces in production
    port: int = Field(default=8000)
    reload: bool = Field(default=False)
    
    # PostgreSQL
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="")
    postgres_db: str = Field(default="exam_middleware")
    database_mode: str = Field(default="postgres")  # Switch to postgres in production
    database_url: Optional[str] = None
    sqlite_db_path: str = Field(default=str(BASE_DIR / "exam_middleware.db"))
    
    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: str = Field(default="")
    redis_db: int = Field(default=0)
    redis_url: Optional[str] = None
    
    # Moodle Configuration
    moodle_base_url: str = Field(default="")  # MUST be set in production (e.g., https://moodle.institution.edu)
    moodle_ws_endpoint: str = Field(default="/webservice/rest/server.php")
    moodle_upload_endpoint: str = Field(default="/webservice/upload.php")
    moodle_token_endpoint: str = Field(default="/login/token.php")
    moodle_service: str = Field(default="moodle_mobile_app")
    moodle_admin_token: Optional[str] = None  # MUST be obtained from Moodle admin panel
    mock_lms_enabled: bool = Field(default=False)  # Set to False in production
    
    # File Storage
    upload_dir: str = Field(default=str(BASE_DIR / "uploads"))
    storage_dir: str = Field(default=str(BASE_DIR / "storage"))
    max_file_size_mb: int = Field(default=50)
    allowed_extensions: str = Field(default=".pdf,.jpg,.jpeg,.png")
    
    # ML Service (Optional - set to False if not used)
    ml_service_url: str = Field(default="http://localhost:8501")
    ml_service_enabled: bool = Field(default=False)
    
    # Subject Mapping - Configure via database after deployment
    subject_19ai405_assignment_id: int = Field(default=0)
    subject_19ai411_assignment_id: int = Field(default=0)
    subject_ml_assignment_id: int = Field(default=0)
    
    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default=str(BASE_DIR / "logs" / "app.log"))
    
    # CORS - Update for production domain
    cors_origins: str = Field(default='["http://localhost:8000"]')

    @field_validator("debug", "reload", "mock_lms_enabled", "ml_service_enabled", mode="before")
    @classmethod
    def parse_boolish_value(cls, value):
        """Accept a few non-standard environment values for booleans."""
        if isinstance(value, bool) or value is None:
            return value

        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return value

    @field_validator("database_url", "redis_url", mode="before")
    @classmethod
    def parse_optional_urls(cls, value):
        """Treat blank URL environment values as unset."""
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("redis_port", "redis_db", mode="before")
    @classmethod
    def parse_optional_ints_with_defaults(cls, value, info):
        """Allow blank environment values and fall back to field defaults."""
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].default
        return value

    @field_validator("log_file", mode="before")
    @classmethod
    def parse_log_file(cls, value):
        """Use the default log file when the environment value is blank."""
        if value is None:
            return str(BASE_DIR / "logs" / "app.log")
        if isinstance(value, str) and not value.strip():
            return str(BASE_DIR / "logs" / "app.log")
        return value
    
    class Config:
        env_file = str(ENV_FILE)
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def base_dir(self) -> Path:
        """Absolute project root for path-safe file access."""
        return BASE_DIR

    @property
    def app_dir(self) -> Path:
        """Absolute application package directory."""
        return APP_DIR

    def _resolve_path(self, raw_path: str) -> Path:
        """Resolve a configured filesystem path against the project root."""
        path = Path(raw_path)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return path

    @property
    def upload_dir_path(self) -> Path:
        """Absolute upload directory path."""
        return self._resolve_path(self.upload_dir)

    @property
    def storage_dir_path(self) -> Path:
        """Absolute storage directory path."""
        return self._resolve_path(self.storage_dir)

    @property
    def log_file_path(self) -> Path:
        """Absolute application log file path."""
        return self._resolve_path(self.log_file)

    @staticmethod
    def _normalize_async_database_url(database_url: str) -> str:
        """Ensure externally provided Postgres URLs use the async SQLAlchemy driver."""
        if database_url.startswith("postgresql+asyncpg://") or database_url.startswith("sqlite+aiosqlite:///"):
            return database_url
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        return database_url

    @staticmethod
    def _normalize_sync_database_url(database_url: str) -> str:
        """Convert async URLs back to sync driver URLs for migrations and tooling."""
        if database_url.startswith("sqlite+aiosqlite:///"):
            return database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
        if database_url.startswith("postgresql+asyncpg://"):
            return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    
    @property
    def database_url_computed(self) -> str:
        """Compute database URL if not provided"""
        if self.database_url:
            return self._normalize_async_database_url(self.database_url)
        if self.database_mode.lower() == "postgres":
            return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        sqlite_path = self.sqlite_db_path
        if not os.path.isabs(sqlite_path):
            sqlite_path = os.path.abspath(sqlite_path)
        sqlite_path = sqlite_path.replace("\\", "/")
        return f"sqlite+aiosqlite:///{sqlite_path}"
    
    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for migrations"""
        if self.database_url:
            return self._normalize_sync_database_url(self.database_url)
        if self.database_mode.lower() != "postgres":
            sqlite_path = self.sqlite_db_path
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.abspath(sqlite_path)
            sqlite_path = sqlite_path.replace("\\", "/")
            return f"sqlite:///{sqlite_path}"
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def redis_url_computed(self) -> str:
        """Compute Redis URL if not provided"""
        if self.redis_url:
            return self.redis_url
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    @property
    def moodle_webservice_url(self) -> str:
        """Full Moodle webservice URL"""
        return f"{self.moodle_base_url}{self.moodle_ws_endpoint}"
    
    @property
    def moodle_upload_url(self) -> str:
        """Full Moodle upload URL"""
        return f"{self.moodle_base_url}{self.moodle_upload_endpoint}"
    
    @property
    def moodle_token_url(self) -> str:
        """Full Moodle token URL"""
        return f"{self.moodle_base_url}{self.moodle_token_endpoint}"
    
    @property
    def allowed_extensions_list(self) -> List[str]:
        """Parse allowed extensions as list"""
        return [ext.strip() for ext in self.allowed_extensions.split(",")]
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins as list"""
        try:
            return json.loads(self.cors_origins)
        except json.JSONDecodeError:
            return ["http://localhost:8000"]
    
    @property
    def max_file_size_bytes(self) -> int:
        """Max file size in bytes"""
        return self.max_file_size_mb * 1024 * 1024
    
    def get_subject_assignment_mapping(self) -> dict:
        """Return subject code to assignment ID mapping"""
        return {
            "19AI405": self.subject_19ai405_assignment_id,
            "19AI411": self.subject_19ai411_assignment_id,
            "ML": self.subject_ml_assignment_id,
            "MACHINELEARNING": self.subject_ml_assignment_id,
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
