"""API 测试：不触网、不调 LLM，全部用注入的假实现。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from skylens.api import routes
from skylens.api.main import create_app


@pytest.fixture
async def client():
    routes.reset_pack_cache()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    routes.reset_pack_cache()


@pytest.fixture
def fake_pack(monkeypatch, sample_pack: dict) -> dict:
    calls: list[tuple] = []

    async def fake_build(place: str, *, days: int = 7, **_: Any) -> dict:
        calls.append((place, days))
        fake_build.calls = calls  # type: ignore[attr-defined]
        return json.loads(json.dumps(sample_pack))

    monkeypatch.setattr(routes, "build_fact_pack", fake_build)
    return sample_pack


class TestHealth:
    async def test_healthz(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_config_without_key(self, client: httpx.AsyncClient, monkeypatch) -> None:
        from skylens.settings import Settings

        monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
        body = (await client.get("/api/config")).json()
        assert body["tianditu_key"] is None
        assert "天地图" in body["attribution"]["basemap"]

    async def test_config_passes_browser_key(self, client: httpx.AsyncClient, monkeypatch) -> None:
        from skylens.settings import Settings

        monkeypatch.setattr(
            routes, "get_settings", lambda: Settings(_env_file=None, tianditu_key="demo-key")
        )
        assert (await client.get("/api/config")).json()["tianditu_key"] == "demo-key"


class TestFactPack:
    async def test_returns_pack(self, client: httpx.AsyncClient, fake_pack: dict) -> None:
        response = await client.get("/api/fact_pack", params={"place": "明安图镇"})
        assert response.status_code == 200
        body = response.json()
        assert body["location"]["name"] == "明安图镇"
        assert body["fact_pack_id"].startswith("sha256:")

    async def test_geocode_failure_is_404(self, client: httpx.AsyncClient, monkeypatch) -> None:
        async def fake_build(*_: Any, **__: Any) -> dict:
            return {"error": "geocode_not_found", "query": "不存在的镇"}

        monkeypatch.setattr(routes, "build_fact_pack", fake_build)
        response = await client.get("/api/fact_pack", params={"place": "不存在的镇"})

        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "geocode_not_found"

    async def test_result_is_cached_per_place_and_days(
        self, client: httpx.AsyncClient, fake_pack: dict, monkeypatch
    ) -> None:
        await client.get("/api/fact_pack", params={"place": "明安图镇", "days": 7})
        await client.get("/api/fact_pack", params={"place": "明安图镇", "days": 7})
        assert len(routes.build_fact_pack.calls) == 1  # type: ignore[attr-defined]

        await client.get("/api/fact_pack", params={"place": "明安图镇", "days": 3})
        assert len(routes.build_fact_pack.calls) == 2  # type: ignore[attr-defined]

    async def test_missing_place_is_422(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/fact_pack")).status_code == 422


class TestChartsAndWarnings:
    async def test_charts(self, client: httpx.AsyncClient, monkeypatch) -> None:
        async def fake_charts(**_: Any) -> dict:
            return {"charts": [{"title": "JMA", "url": "https://example.invalid/j.png"}]}

        monkeypatch.setattr(routes, "fetch_charts", fake_charts)
        body = (await client.get("/api/charts")).json()
        assert body["charts"][0]["title"] == "JMA"

    async def test_charts_failure_returns_empty_list(
        self, client: httpx.AsyncClient, monkeypatch
    ) -> None:
        async def broken(**_: Any) -> dict:
            return {"error": "HTTP 403"}

        monkeypatch.setattr(routes, "fetch_charts", broken)
        body = (await client.get("/api/charts")).json()
        assert body == {"charts": [], "error": "HTTP 403"}

    async def test_warnings_are_explicitly_unavailable(self, client: httpx.AsyncClient) -> None:
        body = (await client.get("/api/warnings", params={"lat": 42.3, "lon": 115.0})).json()
        assert body["warnings"] == []
        assert body["available"] is False
        assert "不得改写" in body["policy"]


class TestExplain:
    async def test_json_endpoint(
        self, client: httpx.AsyncClient, fake_pack: dict, monkeypatch
    ) -> None:
        async def fake_explain(pack: dict, **_: Any) -> dict:
            return {"headline": "冷高压控制", "degraded": False, "facts": []}

        monkeypatch.setattr(routes, "explain_pack", fake_explain)
        body = (await client.get("/api/explain", params={"place": "明安图镇"})).json()

        assert body["degraded"] is False
        assert body["answer"]["headline"] == "冷高压控制"

    async def test_sse_event_order(
        self, client: httpx.AsyncClient, fake_pack: dict, monkeypatch
    ) -> None:
        async def fake_explain(pack: dict, **_: Any) -> dict:
            return {"headline": "h", "observed": "o", "degraded": False}

        monkeypatch.setattr(routes, "explain_pack", fake_explain)

        events: list[tuple[str, dict]] = []
        async with client.stream("POST", "/api/explain", json={"place": "明安图镇"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            event_name = ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event_name = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    events.append((event_name, json.loads(line.removeprefix("data: "))))

        assert [name for name, _ in events] == ["stage", "stage", "stage", "answer", "done"]
        assert events[0][1]["stage"] == "fact_pack"
        assert events[1][1]["fact_pack_id"] == fake_pack["fact_pack_id"]
        assert events[2][1]["stage"] == "explain"
        assert events[3][1]["answer"]["headline"] == "h"

    async def test_sse_reports_fact_pack_error(
        self, client: httpx.AsyncClient, monkeypatch
    ) -> None:
        async def fake_build(*_: Any, **__: Any) -> dict:
            return {"error": "geocode_not_found"}

        monkeypatch.setattr(routes, "build_fact_pack", fake_build)

        async with client.stream("POST", "/api/explain", json={"place": "无所谓"}) as response:
            body = "".join([chunk async for chunk in response.aiter_text()])

        assert "event: error" in body
        assert "geocode_not_found" in body
