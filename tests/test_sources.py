import csv
from datetime import datetime, timezone

import pytest

from wifi_location.models import Observation
from wifi_location.sources import read_csv, write_csv, load_uji, FIELDS
from wifi_location.simulation import generate


def test_csv_roundtrip(tmp_path):
    data = generate(sessions=1, samples_per_area=2)
    data.append(Observation(datetime(2026, 11, 4, tzinfo=timezone.utc), {}, session_id="empty"))
    path = tmp_path / "data.csv"
    write_csv(path, data)
    assert read_csv(path) == data


@pytest.mark.parametrize("bad", ["nan", "inf", "1", "-121", "oops"])
def test_csv_rejects_bad_rssi(tmp_path, bad):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(FIELDS)+f"\n2026-11-04T00:00:00Z,east,a,{bad},simulation,pc,s,a\n")
    with pytest.raises(ValueError, match="row 2"):
        read_csv(path)


def test_csv_rejects_missing_column_and_duplicate(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,rssi\n2026-11-04,-50\n")
    with pytest.raises(ValueError, match="columns"):
        read_csv(path)
    row = "2026-11-04T00:00:00Z,east,a,-50,simulation,pc,s,a\n"
    path.write_text(",".join(FIELDS)+"\n"+row+row)
    with pytest.raises(ValueError, match="duplicate"):
        read_csv(path)


def test_csv_rejects_naive_datetime(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(FIELDS)+"\n2026-11-04T00:00:00,east,a,-50,simulation,pc,s,a\n")
    with pytest.raises(ValueError, match="timezone"):
        read_csv(path)


def test_uji_100_is_missing_and_rows_independent(tmp_path):
    path = tmp_path / "uji.csv"
    path.write_text("WAP001,WAP002,WAP003,BUILDINGID,FLOOR,PHONEID,TIMESTAMP\n-45,100,-80,1,2,3,1380872700\n-46,-60,100,1,2,3,1380872701\n")
    data = load_uji(path)
    assert data[0].readings == {"WAP001": -45, "WAP003": -80}
    assert data[0].source == "ujindoorloc"
    assert data[0].area == "building-1/floor-2"
    assert data[0].session_id != data[1].session_id


def test_uji_rejects_invalid_format(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("area,rssi\nx,-50\n")
    with pytest.raises(ValueError, match="UJI"):
        load_uji(path)
