import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("master_data_snapshot", ROOT / "scripts" / "master_data_snapshot.py")
master = importlib.util.module_from_spec(spec)
spec.loader.exec_module(master)


def test_lookup_many_returns_each_category():
    snapshot = {"lists": {
        "projects": {"items": [{"code": "R02", "name": "Nam O"}]},
        "contractors": {"items": [{"code": "CTC", "name": "Coteccons"}]},
    }}
    result = master.lookup_many(snapshot, [("projects", "R02"), ("contractors", "Coteccons")])
    assert result["results"]["projects"]["matches"][0]["code"] == "R02"
    assert result["results"]["contractors"]["matches"][0]["code"] == "CTC"
