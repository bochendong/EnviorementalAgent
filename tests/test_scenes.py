"""Every engine location must have a scene in the client's maps (web/assets/maps)."""
import json
from pathlib import Path

import pytest

from worldseeds.town.seed import WORKPLACE

MAPS = Path(__file__).resolve().parents[1] / "web" / "assets" / "maps"


@pytest.mark.skipif(not MAPS.exists(), reason="run web/tools/make_assets.py first")
def test_every_location_has_a_scene():
    hosted, doors = set(), set()
    for f in MAPS.glob("*.json"):
        if f.name == "scenes.json":
            continue
        objs = json.loads(f.read_text())["layers"][2]["objects"]
        for o in objs:
            props = {p["name"]: p["value"] for p in o.get("properties", [])}
            if o["type"] == "location" and o["name"] != "here":
                hosted.add(o["name"])
            if o["type"] == "building" and "interior" in props:
                doors.add(props["loc"])
                assert (MAPS / f"{props['interior']}.json").exists()
    needed = {"farm", "plaza", "shop", "forest"} | {w for w, _ in WORKPLACE.values()} | {f"home{i}" for i in range(1, 13)}
    assert needed <= hosted | doors, needed - (hosted | doors)
