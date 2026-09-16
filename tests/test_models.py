from backend.app.llm.ollama import display_name, is_vision_model
from backend.app.storage.chat_repository import is_allowed_model_id


def test_model_ids_accept_installed_ollama_names() -> None:
    assert is_allowed_model_id("phi4-mini")
    assert is_allowed_model_id("llama3.2")
    assert is_allowed_model_id("mistral:latest")
    assert not is_allowed_model_id("../etc/passwd")
    assert not is_allowed_model_id("")


def test_vision_hint_and_display_names() -> None:
    assert is_vision_model("llava")
    assert is_vision_model("llama3.2-vision")
    assert not is_vision_model("phi4-mini")
    assert display_name("phi4-mini") == "Phi-4 Mini"
    assert display_name("mistral") == "Mistral"
