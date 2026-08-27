from pathlib import Path
from types import SimpleNamespace

from app.materials import storage


def test_material_assets_are_content_addressed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "settings", SimpleNamespace(storage_dir=tmp_path))

    first = storage.store_material_asset("document", "vl-p13-5.png", b"first crop")
    repeated = storage.store_material_asset("document", "vl-p13-5.png", b"first crop")
    changed = storage.store_material_asset("document", "vl-p13-5.png", b"changed crop")

    assert repeated == first
    assert changed != first
    assert storage.material_path(first).read_bytes() == b"first crop"
    assert storage.material_path(changed).read_bytes() == b"changed crop"
