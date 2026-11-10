import json
import subprocess
from pathlib import Path

import pytest

from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.init import initialize, target


def fo(*args, cwd=None):
    return subprocess.run(["fo", *map(str, args)], cwd=cwd, capture_output=True, text=True)


def test_version():
    result = fo("--version")
    assert result.returncode == 0
    assert result.stdout.startswith("family-office ")


def test_init_doctor_idempotent_and_discovery(tmp_path):
    root = tmp_path / "office"
    result = fo("init", root, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["office"] == str(root)
    assert (root / "secrets").stat().st_mode & 0o777 == 0o700
    before = (root / "profile/household.md").read_bytes()
    assert fo("init", root).returncode == 0
    assert (root / "profile/household.md").read_bytes() == before
    result = fo("doctor", "--office", root, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(c["status"] != "fail" for c in json.loads(result.stdout))
    result = fo("doctor", "--json", cwd=root / "profile")
    assert result.returncode == 0
    assert (root / "AGENTS.md").read_text().count("<!-- fo:rules:start -->") == 1
    assert (
        subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True
        ).stdout
        == ""
    )


def test_public_repo_cannot_be_an_office(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = fo("init", tmp_path / "office", "--json")
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason"] == "nested_repository"


def test_missing_office_is_structured(tmp_path):
    result = fo("doctor", "--office", tmp_path, "--json")
    assert result.returncode != 0
    assert "reason" in json.loads(result.stdout)


def test_invalid_profile_and_secret_permissions(tmp_path):
    root = tmp_path / "office"
    assert fo("init", root).returncode == 0
    (root / "profile/ips.json").write_text('{"bands":[{"name":"equity","min":0.9,"max":0.2}]}')
    secret = root / "secrets/keys.toml"
    secret.write_text('[provider]\napi_key="SENTINEL-NOT-FOR-OUTPUT"\n')
    secret.chmod(0o644)
    result = fo("doctor", "--office", root, "--json")
    assert result.returncode != 0
    assert "SENTINEL-NOT-FOR-OUTPUT" not in result.stdout + result.stderr
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["profile.ips"]["status"] == "fail"
    assert checks["secrets.perms"]["status"] == "fail"


def test_config_masks_secrets(tmp_path):
    root = tmp_path / "office"
    assert fo("init", root).returncode == 0
    secret = root / "secrets/keys.toml"
    secret.write_text('[schwab]\napp_secret="SENTINEL-NOT-FOR-OUTPUT"\n')
    secret.chmod(0o600)
    result = fo("config", "--office", root, "--json")
    assert result.returncode == 0
    assert "SENTINEL-NOT-FOR-OUTPUT" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["secrets"]["schwab"]["app_secret"] == "***"


def test_ignore_hook_blocks_forced_secret(tmp_path):
    root = tmp_path / "office"
    assert fo("init", root).returncode == 0
    (root / "secrets/keys.toml").write_text('key="fake"')
    subprocess.run(["git", "-C", str(root), "add", "-f", "secrets/keys.toml"], check=True)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "bad",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "private path" in result.stderr.lower()


def test_symlink_target_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "office"
    root.symlink_to(outside, target_is_directory=True)
    assert fo("init", root, "--json").returncode != 0
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "location",
    [
        "Library/Mobile Documents/com~apple~CloudDocs",
        "Library/CloudStorage/Dropbox",
        "Dropbox",
        "Google Drive",
        "OneDrive",
        "OneDrive-Personal",
        "OneDrive - Work",
        "Box",
        "Desktop",
        "Documents",
    ],
)
def test_init_refuses_cloud_synced_paths(tmp_path, monkeypatch, location):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / location / "office"
    with pytest.raises(OfficeError) as error:
        target(root)
    assert error.value.reason == "cloud_synced_path"
    assert "~/FamilyOffice" in error.value.message
    assert not root.exists()


def test_init_checks_resolved_cloud_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "Documents", target_is_directory=True)
    with pytest.raises(OfficeError) as error:
        target(tmp_path / "alias/office")
    assert error.value.reason == "cloud_synced_path"


@pytest.mark.parametrize("location", ["FamilyOffice", "DocumentsBackup", "Library/Other"])
def test_init_allows_local_paths(tmp_path, monkeypatch, location):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / location
    assert target(root) == (root.resolve(), False)


def test_existing_cloud_office_opens_and_doctor_warns(tmp_path, monkeypatch):
    root = tmp_path / "Documents/office"
    initialize(root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert target(root) == (root.resolve(), True)
    assert initialize(root)["created"] is False
    checks = {item["name"]: item for item in diagnose(root)}
    assert checks["office.location"]["status"] == "warn"
    assert "~/FamilyOffice" in checks["office.location"]["reason"]
