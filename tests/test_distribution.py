import subprocess
import tarfile
import zipfile
from pathlib import Path


def test_built_distribution_contains_canonical_roster(tmp_path):
    subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)], check=True, capture_output=True, timeout=60
    )
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        contents = set(wheel.namelist())
        for source in Path("skills").rglob("*"):
            if source.is_file():
                assert "fo/data/" + source.as_posix() in contents
        for source in Path("agents").glob("*.md"):
            assert "fo/data/" + source.as_posix() in contents
        assert "fo/store/schemas/output/networth.schema.json" in contents
        assert "fo/data/playbooks/piotroski.yaml" in contents
    with tarfile.open(next(tmp_path.glob("*.tar.gz"))) as archive:
        assert not any(
            "/.agents/" in name or "/docs/plans/references/" in name for name in archive.getnames()
        )
