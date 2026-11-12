# Config and test seams

## Settings with pydantic-settings
```python
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRAG_", env_file=(".env",), extra="ignore")
    top_k: int = Field(4, ge=1, le=50)
    llm_timeout_s: float = Field(30, gt=0)
    nvidia_api_key: SecretStr | None = Field(None, validation_alias="NVIDIA_API_KEY")

def get_settings() -> Settings:
    return Settings()  # fresh each call: tests can change env between calls
```
Use `.get_secret_value()` only at the call that needs it. Never print the settings object with secrets exposed.

## Provider factory seam
```python
_chat_factory = None

def set_chat_factory(factory) -> None:
    global _chat_factory
    _chat_factory = factory

def make_chat(model: str):
    return (_chat_factory or _default_chat)(model)
```
Tests install a fake factory; production uses the default. The default factory imports the SDK lazily so importing the module needs no key.

## Windows notes
- `open(path, encoding="utf-8")`, `Path.read_text(encoding="utf-8")`.
- Console output of non-ASCII may fail on legacy code pages; set `PYTHONUTF8=1` or avoid fancy characters in CLI output.
- Use `.venv/Scripts/python.exe`; commands in READMEs are PowerShell.
- File locks: close Chroma clients and files before deleting a temp dir in tests.

## Retry with tenacity
```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

@retry(retry=retry_if_exception_type(TransientError), stop=stop_after_attempt(3),
       wait=wait_exponential_jitter(initial=0.5, max=8), reraise=True)
def call(...): ...
```
In tests patch the wait to zero instead of sleeping.
