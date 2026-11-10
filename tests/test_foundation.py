import json
import subprocess
from pathlib import Path

import pytest

from fo.config import credentials_dir, ensure_credentials


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
    assert not (root / "secrets").exists()
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
    secret = credentials_dir(root) / "keys.toml"
    secret.write_text('[provider]\napi_key="SENTINEL-NOT-FOR-OUTPUT"\n')
    secret.chmod(0o644)
    result = fo("doctor", "--office", root, "--json")
    assert result.returncode != 0
    assert "SENTINEL-NOT-FOR-OUTPUT" not in result.stdout + result.stderr
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["profile.ips"]["status"] == "fail"
    assert checks["credentials.perms"]["status"] == "fail"


def test_config_masks_secrets(tmp_path):
    root = tmp_path / "office"
    assert fo("init", root).returncode == 0
    secret = credentials_dir(root) / "keys.toml"
    secret.write_text('[schwab]\napp_secret="SENTINEL-NOT-FOR-OUTPUT"\n')
    secret.chmod(0o600)
    result = fo("config", "--office", root, "--json")
    assert result.returncode == 0
    assert "SENTINEL-NOT-FOR-OUTPUT" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["secrets"]["schwab"]["app_secret"] == "***"


def test_ignore_hook_blocks_forced_secret(tmp_path):
    root = tmp_path / "office"
    assert fo("init", root).returncode == 0
    (root / "secrets").mkdir()
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


def test_credentials_migrate_once_outside_office(tmp_path):
    from fo.auth import save_keys, save_secret_json
    from fo.config import read_config, read_secrets
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    config = root / "office.toml"
    config.write_text('# kept comment\n[office]\ntimezone = "UTC"\n')
    legacy = root / "secrets"
    legacy.mkdir(mode=0o700)
    contents = {"keys.toml": b'[fred]\napi_key="synthetic"\r\n', "schwab-token.json": b"{}\n"}
    for name, value in contents.items():
        (legacy / name).write_bytes(value)
        (legacy / name).chmod(0o600)
    directory = ensure_credentials(root)
    assert directory.parent == tmp_path / "credentials"
    assert directory.name == read_config(root)["office"]["id"]
    assert not directory.is_relative_to(root)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert directory.parent.stat().st_mode & 0o777 == 0o700
    for name, value in contents.items():
        assert (directory / name).read_bytes() == value
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert not legacy.exists()
    before = config.read_bytes(), config.stat().st_mtime_ns
    assert credentials_dir(root) == directory
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert config.read_text().startswith('# kept comment\n[office]\ntimezone = "UTC"\n')
    save_keys(root, {"fred": {"api_key": "replacement"}})
    save_secret_json(root, "exa", {"api_key": "synthetic"})
    assert read_secrets(root)["fred"]["api_key"] == "replacement"
    assert (directory / "exa.json").stat().st_mode & 0o777 == 0o600
    assert not legacy.exists()


def test_credential_conflicts_stay_and_doctor_flags_office_copy(tmp_path):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    directory = credentials_dir(root)
    legacy = root / "secrets"
    legacy.mkdir(mode=0o700)
    for name in ("same.json", "different.json"):
        (directory / name).write_text("local")
        (directory / name).chmod(0o600)
    (legacy / "same.json").write_text("local")
    (legacy / "different.json").write_text("office")
    assert ensure_credentials(root) == directory
    assert not (legacy / "same.json").exists()
    assert (legacy / "different.json").read_text() == "office"
    assert (directory / "different.json").read_text() == "local"
    checks = {c["name"]: c for c in diagnose(root)}
    assert checks["secrets.in_office"]["status"] == "fail"
    assert checks["credentials.perms"]["status"] == "pass"


@pytest.mark.parametrize(
    "platform,xdg", [("darwin", None), ("linux", None), ("linux", ""), ("linux", "xdg")]
)
def test_default_credentials_location(tmp_path, monkeypatch, platform, xdg):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    monkeypatch.delenv("FO_CREDENTIALS_HOME")
    monkeypatch.setattr("fo.config.sys.platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    if xdg is not None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / xdg) if xdg else "")
    base = (
        tmp_path / "Library/Application Support/FamilyOffice/credentials"
        if platform == "darwin"
        else (tmp_path / "xdg" if xdg else tmp_path / ".local/share") / "family-office/credentials"
    )
    assert credentials_dir(root).parent == base


def test_failed_credential_migration_preserves_office_copy(tmp_path, monkeypatch):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    directory = credentials_dir(root)
    legacy = root / "secrets"
    legacy.mkdir(mode=0o700)
    source = legacy / "keys.toml"
    source.write_text('[fred]\napi_key="synthetic"\n')
    source.chmod(0o600)

    def interrupted(*args, **kwargs):
        raise OSError("synthetic interruption")

    monkeypatch.setattr("fo.office.atomic_write", interrupted)
    assert ensure_credentials(root) == directory
    assert source.exists()
    assert not (directory / "keys.toml").exists()
    checks = {c["name"]: c for c in diagnose(root)}
    assert checks["secrets.in_office"]["status"] == "fail"


def test_credentials_cannot_be_placed_inside_office(tmp_path, monkeypatch):
    from fo.errors import OfficeError
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    monkeypatch.setenv("FO_CREDENTIALS_HOME", str(root / "local-credentials"))
    with pytest.raises(OfficeError, match="outside the office"):
        credentials_dir(root)
    assert not (root / "local-credentials").exists()


def test_legacy_secret_symlink_is_not_migrated(tmp_path):
    from fo.doctor import diagnose
    from fo.errors import OfficeError
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    (root / "secrets").symlink_to(root / "profile", target_is_directory=True)
    before = (root / "profile/accounts.json").read_bytes()
    with pytest.raises(OfficeError, match="symlink"):
        credentials_dir(root)
    assert (root / "profile/accounts.json").read_bytes() == before
    checks = {c["name"]: c for c in diagnose(root)}
    assert checks["credentials.perms"]["status"] == "fail"
    assert checks["secrets.in_office"]["status"] == "fail"


def test_icloud_placeholders_are_never_migrated(tmp_path):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    legacy = root / "secrets"
    legacy.mkdir()
    stub = legacy / ".keys.toml.icloud"
    stub.write_bytes(b"synthetic placeholder")
    before = stub.read_bytes(), stub.stat().st_mtime_ns
    directory = ensure_credentials(root)
    assert (stub.read_bytes(), stub.stat().st_mtime_ns) == before
    assert not (directory / stub.name).exists()
    check = next(c for c in diagnose(root) if c["name"] == "secrets.in_office")
    assert check["status"] == "fail"
    assert "download" in check["reason"]


def test_unmigrated_reads_do_not_write_and_doctor_fix_migrates(tmp_path):
    from fo.config import provider_key, public_config, read_secrets
    from fo.doctor import diagnose
    from fo.errors import OfficeError
    from fo.init import initialize
    from fo.serve.devices import Devices
    from fo.serve.onboarding import paired

    root = tmp_path / "office"
    initialize(root)
    config = root / "office.toml"
    config.write_text('[office]\ntimezone = "UTC"\n')
    legacy = root / "secrets"
    legacy.mkdir()
    (legacy / "keys.toml").write_text('[fred]\napi_key = "synthetic"\n')
    before = config.read_bytes(), config.stat().st_mtime_ns
    for read in (credentials_dir, read_secrets, public_config, lambda r: provider_key(r, "fred")):
        with pytest.raises(OfficeError) as error:
            read(root)
        assert error.value.reason == "credentials_not_migrated"
        assert "fo doctor --fix" in error.value.message
    assert Devices(lambda: root).list() == []
    assert not paired(root)
    checks = {c["name"]: c for c in diagnose(root)}
    assert checks["credentials.perms"]["status"] == "fail"
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert (legacy / "keys.toml").exists()
    result = fo("doctor", "--fix", "--office", root, "--json")
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["credentials.perms"]["status"] == "pass"
    assert checks["secrets.in_office"]["status"] == "pass"
    assert read_secrets(root)["fred"]["api_key"] == "synthetic"
    assert not legacy.exists()


def test_credentials_read_does_not_create_directory_and_devices_are_empty(tmp_path):
    from fo.init import initialize
    from fo.serve.devices import Devices

    root = tmp_path / "office"
    initialize(root)
    directory = credentials_dir(root)
    directory.rmdir()
    before = (root / "office.toml").stat().st_mtime_ns
    assert credentials_dir(root) == directory
    assert Devices(lambda: root).list() == []
    assert not directory.exists()
    assert (root / "office.toml").stat().st_mtime_ns == before
    Devices(lambda: root).save([])
    assert directory.stat().st_mode & 0o777 == 0o700


def test_doctor_fix_preserves_override_base_permissions(tmp_path):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    directory = credentials_dir(root)
    directory.parent.chmod(0o755)
    directory.chmod(0o755)
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert directory.stat().st_mode & 0o777 == 0o700
    assert directory.parent.stat().st_mode & 0o777 == 0o755


def test_init_denies_agent_reads_of_machine_credentials(tmp_path):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    deny = json.loads((root / ".claude/settings.json").read_text())["permissions"]["deny"]
    assert "Read(secrets/**)" in deny
    assert "Read(~/Library/Application Support/FamilyOffice/credentials/**)" in deny
    assert "Read(~/.local/share/family-office/credentials/**)" in deny


def test_office_id_creation_holds_the_config_write_lock(tmp_path, monkeypatch):
    import fo.config
    from fo.init import initialize
    from fo.lock import probe

    root = tmp_path / "office"
    initialize(root)
    (root / "office.toml").write_text('[office]\ntimezone = "UTC"\n')
    write = fo.config._write_config

    def locked_write(root, key, value):
        assert probe(root)
        write(root, key, value)

    monkeypatch.setattr(fo.config, "_write_config", locked_write)
    ensure_credentials(root)
    assert fo.config.read_config(root)["office"]["timezone"] == "UTC"


@pytest.mark.parametrize("read_only", [True, False])
def test_serve_only_migrates_credentials_when_writable(tmp_path, read_only):
    from fo.init import initialize
    from fo.serve import prepare

    root = tmp_path / "office"
    initialize(root)
    config = root / "office.toml"
    config.write_text('[office]\ntimezone = "UTC"\n')
    before = config.read_bytes(), config.stat().st_mtime_ns
    server, _ = prepare(root, port=0, read_only=read_only)
    try:
        if read_only:
            assert (config.read_bytes(), config.stat().st_mtime_ns) == before
        else:
            assert credentials_dir(root).is_dir()
    finally:
        if server.app.runs is not None:
            server.app.runs.shutdown()
        server.server_close()
