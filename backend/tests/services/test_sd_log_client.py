import httpx
import pytest

from app.services.sd_log_client import SdLogClient, SdLogUnreachable


@pytest.mark.asyncio
async def test_list_logs_parses_databases(monkeypatch):
    payload = {
        "current_db": "a.db",
        "databases": [{"filename": "a.db", "status": "active", "size": 0}],
    }

    async def fake_get(self, url, **kw):
        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return R()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    client = SdLogClient("http://10.0.0.5")
    logs = await client.list_logs()
    assert logs == payload["databases"]


@pytest.mark.asyncio
async def test_download_log_returns_bytes(monkeypatch):
    async def fake_get(self, url, **kw):
        class R:
            content = b"SQLITEDATA"

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    client = SdLogClient("http://10.0.0.5")
    assert await client.download_log("a.db") == b"SQLITEDATA"


@pytest.mark.asyncio
async def test_unreachable_raises(monkeypatch):
    async def boom(self, url, **kw):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("httpx.AsyncClient.get", boom)
    with pytest.raises(SdLogUnreachable):
        await SdLogClient("http://10.0.0.5").list_logs()


@pytest.mark.asyncio
async def test_download_rejects_bad_filename():
    with pytest.raises(ValueError):
        await SdLogClient("http://10.0.0.5").download_log("../etc/passwd")
