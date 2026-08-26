"""sporttery.fetch_league_list 展平逻辑测试(离线 mock,不发真实请求)。

覆盖接口的两种条目形态:
- hot 分组:平铺联赛条目(顶层含 leagueAbbCnName)
- normal 等分组:洲包装条目(countryList -> 国家 -> leagueList)
"""

import typing

import pytest

from app.collector.sources import sporttery

# 模拟 getLeagueListV1 的 value 结构:hot 平铺 + normal 洲包装嵌套
_SAMPLE_PAYLOAD: dict[str, typing.Any] = {
    "errorCode": "0",
    "value": {
        "hot": [
            {
                "areaId": 176,
                "leagueAbbCnName": "西甲",
                "uniformLeagueId": 24,
                "seasonList": [{"seasonId": 15485, "seasonName": "2026/2027"}],
            }
        ],
        "normal": [
            {
                "countryCnName": "欧洲",
                "countryList": [
                    {
                        "countryCnName": "欧洲",
                        "leagueList": [
                            {
                                "areaId": 7,
                                "leagueAbbCnName": "欧冠",
                                "uniformLeagueId": 30,
                                "seasonList": [
                                    {"seasonId": 15574, "seasonName": "2026/2027"}
                                ],
                            },
                            {
                                "areaId": 176,
                                "leagueAbbCnName": "西国王杯",
                                "uniformLeagueId": 21,
                                "seasonList": [
                                    {"seasonId": 13994, "seasonName": "2025/2026"}
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    },
}


@pytest.fixture
def stub_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """将网关请求替换为离线样本。"""

    async def fake_get_json(
        client: typing.Any, path: str, params: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return _SAMPLE_PAYLOAD

    monkeypatch.setattr(sporttery, "_get_json", fake_get_json)


class TestFetchLeagueList:
    async def test_flattens_hot_and_nested_groups(self, stub_gateway: None) -> None:
        items = await sporttery.fetch_league_list()

        names = [it["leagueAbbCnName"] for it in items]
        assert names == ["西甲", "欧冠", "西国王杯"]

        xijia = items[0]
        assert xijia["group"] == "hot"
        assert xijia["tier"] == 1
        assert "countryCnName" not in xijia  # 平铺条目不带国家包装信息

        ucl = items[1]
        assert ucl["group"] == "normal"
        assert ucl["tier"] == 1
        assert ucl["countryCnName"] == "欧洲"
        assert ucl["uniformLeagueId"] == 30

    async def test_nested_item_resolvable_by_name(
        self, stub_gateway: None
    ) -> None:
        from app.collector.parsers import league as league_parser

        items = await sporttery.fetch_league_list()
        item = league_parser.find_league_item(items, "欧冠")
        assert item["uniformLeagueId"] == 30
