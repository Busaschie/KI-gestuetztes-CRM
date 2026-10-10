import json

import httpx
import pytest

from agents.llm.base import LLMError
from agents.llm.providers.mistral import MistralProvider
from agents.llm.providers.ollama import OllamaProvider


def test_mistral_sends_json_mode_and_parses_answer():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"last_name": "Hötter"}'}}]})

    p = MistralProvider("key", "mistral-small-latest", "mistral-ocr-latest", transport=httpx.MockTransport(handler))
    assert p.complete_json("sys", "cv", {"type": "object"}) == {"last_name": "Hötter"}
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["max_tokens"] == 4096
    assert seen["auth"] == "Bearer key"


def test_mistral_without_key_fails_clearly():
    with pytest.raises(LLMError, match="MISTRAL_API_KEY"):
        MistralProvider("", "m", "o")


def ndjson(*contents):
    lines = [json.dumps({"message": {"content": c}, "done": False}) for c in contents]
    lines.append(json.dumps({"message": {"content": ""}, "done": True}))
    return httpx.Response(200, content="\n".join(lines).encode())


def test_ollama_streams_and_joins_chunks():
    p = OllamaProvider("http://x", "m", transport=httpx.MockTransport(lambda r: ndjson('{"last_', 'name": "Hötter"}')))
    assert p.complete_json("s", "u", {}) == {"last_name": "Hötter"}


def test_ollama_sends_schema_as_format():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ndjson('{"ok": true}')

    p = OllamaProvider("http://localhost:11434", "qwen3:8b", transport=httpx.MockTransport(handler))
    assert p.complete_json("sys", "cv", {"type": "object"}) == {"ok": True}
    assert seen["body"]["format"] == {"type": "object"} and seen["body"]["stream"] is True


def test_ollama_not_running_gives_hint():
    def handler(request):
        raise httpx.ConnectError("refused")

    p = OllamaProvider("http://localhost:11434", "x", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="ollama serve"):
        p.complete_json("s", "u", {})


def test_ollama_disables_thinking_and_sets_context():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ndjson("{}")

    OllamaProvider("http://x", "qwen3:8b", num_ctx=8192, transport=httpx.MockTransport(handler)).complete_json("s", "u", {})
    assert seen["body"]["think"] is False and seen["body"]["options"]["num_ctx"] == 8192


def test_ollama_retries_without_think_for_models_without_thinking():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("think" in body)
        if "think" in body:
            return httpx.Response(400, json={"error": "\"llama3.1\" does not support thinking"})
        return ndjson('{"ok": 1}')

    p = OllamaProvider("http://x", "llama3.1", transport=httpx.MockTransport(handler))
    assert p.complete_json("s", "u", {}) == {"ok": 1} and calls == [True, False]


def test_ollama_timeout_becomes_llm_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    p = OllamaProvider("http://x", "qwen3:8b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="hängt"):
        p.complete_json("s", "u", {})


def test_normalize_unwraps_and_maps_aliases():
    from agents.llm.schemas import normalize_llm_output

    assert normalize_llm_output({"CVProfile": {"vorname": "Max", "nachname": "Mustermann"}}) == {
        "first_name": "Max", "last_name": "Mustermann"}
    out = normalize_llm_output({"name": "Anna Maria Hötter"})
    assert out["first_name"] == "Anna Maria" and out["last_name"] == "Hötter"
    assert normalize_llm_output(["x"]) == {}


def test_schema_makes_all_fields_required():
    from agents.llm.schemas import CV_SCHEMA

    assert {"first_name", "last_name", "email"} <= set(CV_SCHEMA["required"])
    pos = CV_SCHEMA["$defs"]["PositionOut"]
    assert set(pos["required"]) == set(pos["properties"])


def test_fill_from_text_like_llama_answer():
    """Nachgestellt: llama3.1 lieferte den Namen nur als 'headline' und keine Kontaktdaten."""
    from agents.llm.schemas import CVProfile, fill_from_text, normalize_llm_output

    text = ("Max Mustermann\nmusterstr. 12 89898 München – tel: +49 151 2345678 – email: muster@de.de\n"
            "linkedin.com/in/max-mustermann\nBeruflicher Werdegang\n")
    raw = {"headline": "Max Mustermann", "positions": [{"title": "KI-Manager", "company": "cimdata", "start": "2026", "end": "heute"}]}
    p = fill_from_text(CVProfile.model_validate(normalize_llm_output(raw)), text)
    assert (p.first_name, p.last_name, p.email) == ("Max", "Mustermann", "muster@de.de")
    assert p.phone == "+49 151 2345678" and p.linkedin_url == "https://linkedin.com/in/max-mustermann"
    assert p.headline is None
    assert p.positions[0].is_current and p.positions[0].end is None


def test_fill_from_text_does_not_guess_name_from_non_name_line():
    from agents.llm.schemas import CVProfile, fill_from_text

    p = fill_from_text(CVProfile(), "LEBENSLAUF\nBeruflicher Werdegang")
    assert p.last_name is None


def test_name_found_below_page_header():
    from agents.llm.schemas import CVProfile, fill_from_text

    text = ("Seite 1 von 4\nErika Musterfrau\nSenior Entwicklerin | Business Analyst\n"
            "München | +49 1525 1234567 | erika@example.de | Geb.: 01.01.1970\n"
            "LinkedIn: linkedin.com/in/erika-müsterfrau | GitHub: https://github.com/erika\n")
    p = fill_from_text(CVProfile(), text)
    assert (p.first_name, p.last_name) == ("Erika", "Musterfrau")
    assert p.linkedin_url == "https://linkedin.com/in/erika-müsterfrau"
    assert p.phone == "+49 1525 1234567" and p.email == "erika@example.de"


def test_linkedin_from_model_gets_https():
    from agents.llm.schemas import CVProfile, fill_from_text

    p = fill_from_text(CVProfile(last_name="X", linkedin_url="linkedin.com/in/x"), "")
    assert p.linkedin_url == "https://linkedin.com/in/x"


def test_schema_limits_list_lengths():
    from agents.llm.schemas import CV_SCHEMA

    assert CV_SCHEMA["properties"]["skills"]["maxItems"] == 40
    assert CV_SCHEMA["$defs"]["PositionOut"]["properties"]["tasks"]["maxItems"] == 6


def test_ollama_reports_truncated_loop_with_tail():
    def handler(request):
        body = json.loads(request.content)
        assert body["options"]["num_predict"] == 100
        lines = [json.dumps({"message": {"content": '"Python", '}, "done": False})] * 5
        lines.append(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length"}))
        return httpx.Response(200, content="\n".join(lines).encode())

    p = OllamaProvider("http://x", "m", num_predict=100, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="abgeschnitten.*Python"):
        p.complete_json("s", "u", {})


def test_invented_languages_are_removed():
    """Nachgestellt: llama3.1 ergänzte Deutsch/Englisch, obwohl der CV keine Sprachen nennt."""
    from agents.llm.schemas import CVProfile, fill_from_text

    text = "Max Mustermann\nDeutschlandweit umzugsbereit\nInternationale Zusammenarbeit"
    p = fill_from_text(CVProfile(last_name="Mustermann", languages=[{"name": "Deutsch"}, {"name": "Englisch"}]), text)
    assert p.languages == []


def test_languages_in_text_are_kept_in_any_spelling():
    from agents.llm.schemas import CVProfile, fill_from_text

    text = "Limbi străine: engleză (C1), germană – fließend. Sprachen: Rumänisch (Muttersprache)"
    langs = [{"name": "Englisch", "level": "C1"}, {"name": "Deutsch"}, {"name": "Rumänisch"}, {"name": "Französisch"}]
    p = fill_from_text(CVProfile(last_name="X", languages=langs), text)
    assert [lang.name for lang in p.languages] == ["Englisch", "Deutsch", "Rumänisch"]


def test_mistral_retries_on_rate_limit_then_succeeds():
    calls, waits = [], []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"message": "Rate limit exceeded"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})

    p = MistralProvider("k", "m", "o", transport=httpx.MockTransport(handler), sleep=waits.append)
    assert p.complete_json("s", "u", {}) == {"ok": 1}
    assert len(calls) == 3 and waits == [2.0, 2.0]


def test_mistral_gives_clear_hint_when_rate_limit_persists():
    p = MistralProvider("k", "m", "o", sleep=lambda s: None,
                        transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})))
    with pytest.raises(LLMError, match="Ratenlimit.*Pay-as-you-go"):
        p.complete_json("s", "u", {})
