import base64
import json

import httpx
import pytest

from app.services import ai_providers as ap

FOLDER = "b1gtest"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Api-Key k"})


def test_yandex_text_suggest_parses_json_schema_answer():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        answer = json.dumps({"title": "Kettle", "description": "A steel kettle."})
        return httpx.Response(200, json={"result": {"alternatives": [{"message": {"role": "assistant", "text": answer}}], "usage": {}}})

    p = ap.YandexGPTText("k", FOLDER, client=_client(handler))
    s = p.suggest(ap.PageMeta(url="https://shop.example/1", title="Kettle 1.7", text="Boils water."), "ru")
    assert s.title == "Kettle" and s.description == "A steel kettle."
    assert seen["url"].endswith("/foundationModels/v1/completion") and seen["auth"] == "Api-Key k"
    assert seen["body"]["modelUri"] == f"gpt://{FOLDER}/yandexgpt-lite/latest"
    assert "jsonSchema" in seen["body"] and "Russian" in seen["body"]["messages"][0]["text"]
    assert "shop.example" in seen["body"]["messages"][1]["text"]


@pytest.mark.parametrize("status,kind", [(403, "auth"), (401, "auth"), (429, "quota"), (500, "bad_response")])
def test_yandex_text_maps_http_errors(status, kind):
    p = ap.YandexGPTText("k", FOLDER, client=_client(lambda r: httpx.Response(status, json={"message": "denied"})))
    with pytest.raises(ap.ProviderError) as ei:
        p.suggest(ap.PageMeta(url="https://x.example/"), "en")
    assert ei.value.kind == kind and ei.value.status == status and "denied" in ei.value.message


def test_yandex_text_bad_json_is_bad_response():
    p = ap.YandexGPTText("k", FOLDER, client=_client(lambda r: httpx.Response(200, json={"result": {"alternatives": [{"message": {"text": "not json"}}]}})))
    with pytest.raises(ap.ProviderError) as ei:
        p.suggest(ap.PageMeta(url="https://x.example/"), "en")
    assert ei.value.kind == "bad_response"


def test_yandex_art_images_api():
    img = b"\xff\xd8fakejpeg"

    def handler(req: httpx.Request):
        assert req.url == "https://ai.api.cloud.yandex.net/v1/images/generations"
        body = json.loads(req.content)
        assert body["model"] == f"art://{FOLDER}/aliceai-image-art-3.0" and body["prompt"].startswith("a cup") and body["size"] == "1024x1024"
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": base64.b64encode(img).decode()}], "output_format": "jpeg"})

    p = ap.YandexArtImage("k", FOLDER, client=_client(handler))
    assert p.generate("a cup", "en") == img


def test_yandex_art_denied_and_bad_payload():
    p = ap.YandexArtImage("k", FOLDER, client=_client(lambda r: httpx.Response(403, json={"message": "Access to model art://yandex-art/latest denied"})))
    with pytest.raises(ap.ProviderError) as ei:
        p.generate("x", "en")
    assert ei.value.kind == "auth" and "denied" in ei.value.message

    p = ap.YandexArtImage("k", FOLDER, client=_client(lambda r: httpx.Response(200, json={"data": []})))
    with pytest.raises(ap.ProviderError) as ei:
        p.generate("x", "en")
    assert ei.value.kind == "bad_response"
