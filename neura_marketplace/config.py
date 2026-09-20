from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    neuralake_api_key: str = ''
    neuralake_base_url: str = 'https://api.neuralake.cloud/v1'
    neuralake_model: str = "text"

    jarvis_model: str = "text"
    marcelo_model: str = "reasoning"

    worker_text_model: str = "text"
    worker_code_model: str = "code"
    verifier_model: str = "reasoning"
    multimodal_model: str = "multimodal"

    database_path: Path = Path('./neura.db')
    agent_dataset_dir: Path = Path('./data/agency-agents')
    sample_agent_dataset_dir: Path = Path('./data/sample-agents')

    jarvis_host: str = '127.0.0.1'
    jarvis_port: int = 8000
    jarvis_base_url: str = 'http://127.0.0.1:8000'

    marcelo_host: str = '127.0.0.1'
    marcelo_port: int = 8001
    marcelo_base_url: str = 'http://127.0.0.1:8001'

    runner_base_url: str = 'http://127.0.0.1:8002'
    workspace_root: Path = Path('/workspace')
    skills_dir: Path = Path('/app/data/skills')

    worker_gateway_host: str = '127.0.0.1'
    worker_gateway_port: int = 8010
    # Empty base URL keeps MARCELO delegating through the in-process executor.
    worker_gateway_base_url: str = ''
    worker_gateway_token: str = ''
    a2a_request_timeout: float = 600.0
    worker_gateway_database_path: Path = Path('./neura-worker.db')

    seller_host: str = '127.0.0.1'
    seller_port: int = 8020
    seller_base_url: str = 'http://127.0.0.1:8020'
    seller_database_path: Path = Path('./seller.db')
    # Comma-separated destinations workers may reach with the a2a.call tool.
    a2a_outbound_allowlist: str = 'http://127.0.0.1:8020/,http://seller:8020/'

    # Agora Conversational AI voice bridge (empty = voice disabled, text still works).
    agora_app_id: str = ''
    agora_agent_id: str = ''
    agora_customer_id: str = ''
    agora_customer_secret: str = ''
    # Server-side only; used to mint RTC tokens for browser clients, never sent to the UI.
    agora_app_certificate: str = ''

    max_task_attempts: int = 3
    marketplace_candidate_limit: int = 5
    agent_max_steps: int = 16
    tool_timeout_seconds: float = 45.0

    @property
    def effective_agent_dataset_dir(self) -> Path:
        if self.agent_dataset_dir.exists() and any(self.agent_dataset_dir.rglob('*.md')):
            return self.agent_dataset_dir
        return self.sample_agent_dataset_dir


settings = Settings()
