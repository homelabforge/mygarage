"""GET /api/country-profiles: the list and one profile, with the EU fallback."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestCountryProfileRoutes:
    async def test_list_profiles(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/country-profiles", headers=auth_headers)
        assert response.status_code == 200
        rows = {row["country"]: row for row in response.json()}
        assert "EU" in rows and "FR" in rows
        assert rows["FR"]["has_inspection"] is True
        assert rows["FR"]["lez_scheme"] == "critair"
        assert rows["FR"]["names"]["inspection"] == "Contrôle technique"

    async def test_get_fr(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/country-profiles/fr", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["country"] == "FR"
        assert body["extends"] == "EU"
        assert body["inspection"]["schedules"][0]["steps"][0]["first_after_years"] == 4
        assert body["fuel"]["octane_scale"] == "RON"
        assert any(g["id"] == "sp95_e10" for g in body["fuel"]["grades"])
        assert body["sources"]

    async def test_member_state_without_file_reads_the_eu_baseline(
        self, client: AsyncClient, auth_headers
    ):
        response = await client.get("/api/country-profiles/AT", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["country"] == "EU"

    async def test_unknown_country_is_404(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/country-profiles/ZZ", headers=auth_headers)
        assert response.status_code == 404

    async def test_malformed_code_is_rejected(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/country-profiles/FRA", headers=auth_headers)
        assert response.status_code == 422
        response = await client.get("/api/country-profiles/..", headers=auth_headers)
        assert response.status_code in (404, 422)
