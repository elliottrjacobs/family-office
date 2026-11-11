import json
import subprocess
from pathlib import Path

import pytest

from fo.config import credentials_dir, ensure_credentials
from fo.office import git


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


@pytest.mark.parametrize("missing_file", [False, True])
def test_doctor_repairs_and_records_launchd_ignore(tmp_path, missing_file):
    from fo.init import initialize
    from fo.serve.onboarding import derive
    from fo.serve.server import Locator

    root = tmp_path / "office"
    initialize(root)
    path = root / ".gitignore"
    original = path.read_text().replace("launchd/\n", "").rstrip("\n")
    if missing_file:
        path.unlink()
    else:
        path.write_text(original)
    result = fo("doctor", "--office", root, "--json")
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["office.ignore"]["status"] == "warn"
    item = next(c for c in derive(Locator(root))["doctor"] if c["name"] == "office.ignore")
    assert "fo doctor --fix" in item["command"]
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["office.ignore"]["status"] == "pass"
    assert path.read_text() == ("" if missing_file else original + "\n") + "launchd/\n"
    assert git(root, "status", "--porcelain", "--", ".gitignore").stdout == ""
    if not missing_file:
        assert git(root, "status", "--porcelain").stdout == ""
    head = git(root, "rev-parse", "HEAD").stdout
    assert fo("doctor", "--fix", "--office", root, "--json").returncode == 0
    assert git(root, "rev-parse", "HEAD").stdout == head


def test_public_repo_cannot_be_an_office(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = fo("init", tmp_path / "office", "--json")
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason"] == "nested_repository"


@pytest.mark.parametrize("managed", [".gitignore", ".claude/settings.json", "office.toml"])
def test_doctor_retries_recording_after_index_lock(tmp_path, managed):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    path = root / managed
    if managed == ".gitignore":
        path.write_text(path.read_text().replace("launchd/\n", ""))
    elif managed == ".claude/settings.json":
        path.write_text("{}\n")
    else:
        path.write_text(
            "".join(
                line
                for line in path.read_text().splitlines(keepends=True)
                if not line.startswith("id = ")
            )
        )
    lock = root / ".git/index.lock"
    lock.touch()
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "git_failed"
    if managed == ".gitignore":
        assert "launchd/" in path.read_text().splitlines()
        checks = json.loads(fo("doctor", "--office", root, "--json").stdout)
        check = next(c for c in checks if c["name"] == "office.ignore")
        assert check["status"] == "warn"
        assert "fo doctor --fix" in check["reason"]
    lock.unlink()
    result = fo("doctor", "--fix", "--office", root, "--json")
    checks = json.loads(result.stdout)
    assert [c["name"] for c in checks if c["status"] == "fail"] == (
        ["skills.fresh"] if managed == "office.toml" else []
    )
    assert git(root, "status", "--porcelain").stdout == ""
    assert fo("commit", "--office", root, "--json").returncode == 0
    head = git(root, "rev-parse", "HEAD").stdout
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert isinstance(json.loads(result.stdout), list)
    assert git(root, "rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("ignore_present", [False, True])
def test_doctor_untracks_launchd_and_keeps_local_files(tmp_path, ignore_present):
    from fo.commits import commit_office
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    ignore = root / ".gitignore"
    if not ignore_present:
        ignore.write_text(ignore.read_text().replace("launchd/\n", ""))
    plist = root / "launchd/local.family-office.sync.plist"
    plist.parent.mkdir()
    plist.write_text("old host\n")
    git(root, "add", "-f", "--", ".gitignore", "launchd")
    git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-qm",
        "Old workaround",
    )
    unrelated = root / "profile/household.md"
    before = git(root, "show", "HEAD:profile/household.md").stdout
    unrelated.write_text(unrelated.read_text() + "\nUnrelated edit\n")
    git(root, "add", "--", "profile/household.md")
    checks = json.loads(fo("doctor", "--office", root, "--json").stdout)
    check = next(c for c in checks if c["name"] == "office.ignore")
    assert check["status"] == "warn"
    assert "fo doctor --fix" in check["reason"]
    plist.write_text("regenerated before repair\n")
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        next(c for c in json.loads(result.stdout) if c["name"] == "office.ignore")["status"]
        == "pass"
    )
    assert git(root, "ls-files", "--", "launchd").stdout == ""
    assert git(root, "ls-tree", "--name-only", "HEAD", "--", "launchd").stdout == ""
    assert plist.read_text() == "regenerated before repair\n"
    assert git(root, "show", "HEAD:profile/household.md").stdout == before
    assert git(root, "status", "--porcelain", "--", "profile/household.md").stdout.startswith("M ")
    git(root, "restore", "--staged", "--worktree", "--", "profile/household.md")
    plist.write_text("new host\n")
    (root / "notebook/plan.md").write_text("Updated plan\n")
    assert commit_office(root) == {"committed": True, "pushed": False}
    assert git(root, "status", "--porcelain").stdout == ""


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
    assert git(root, "status", "--porcelain").stdout == ""
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
    for name in ("fred.json", "exa.json"):
        (directory / name).write_text("local")
        (directory / name).chmod(0o600)
    (legacy / "fred.json").write_text("local")
    (legacy / "exa.json").write_text("office")
    assert ensure_credentials(root) == directory
    assert not (legacy / "fred.json").exists()
    assert (legacy / "exa.json").read_text() == "office"
    assert (directory / "exa.json").read_text() == "local"
    checks = {c["name"]: c for c in diagnose(root)}
    assert checks["secrets.in_office"]["status"] == "fail"
    assert checks["credentials.perms"]["status"] == "pass"


def test_migration_only_moves_managed_credentials_and_names_leftovers(tmp_path):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    legacy = root / "secrets"
    legacy.mkdir()
    managed = (
        "keys.toml",
        "alphavantage.json",
        "fred.json",
        "exa.json",
        "firecrawl.json",
        "gemini.json",
        "schwab-token.json",
        "devices.json",
    )
    remaining = ("notes.txt", "other-provider.json", "edgar.json", ".keys.toml.icloud")
    for name in (*managed, *remaining):
        (legacy / name).write_bytes(b"synthetic fixture\n")
    before = {
        name: ((legacy / name).read_bytes(), (legacy / name).stat().st_mtime_ns)
        for name in remaining
    }
    directory = ensure_credentials(root)
    assert sorted(p.name for p in directory.iterdir()) == sorted(managed)
    for name in managed:
        assert (directory / name).read_bytes() == b"synthetic fixture\n"
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in legacy.iterdir()) == sorted(remaining)
    for name in remaining:
        assert ((legacy / name).read_bytes(), (legacy / name).stat().st_mtime_ns) == before[name]
    check = next(c for c in diagnose(root) if c["name"] == "secrets.in_office")
    assert check["status"] == "fail"
    for name in remaining:
        assert f"secrets/{name}" in check["reason"]
    assert "synthetic fixture" not in check["reason"]


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


@pytest.mark.parametrize("missing_base", [False, True])
def test_doctor_accepts_missing_local_credentials_without_creating_them(tmp_path, missing_base):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    directory = credentials_dir(root)
    directory.rmdir()
    if missing_base:
        directory.parent.rmdir()
    check = next(c for c in diagnose(root) if c["name"] == "credentials.perms")
    assert check["status"] == "pass"
    assert not directory.exists()


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


@pytest.mark.parametrize("repair", ["migration", "doctor"])
@pytest.mark.parametrize(
    "permissions",
    [
        {"allow": ["Read"], "deny": ["Read(secrets/**)"]},
        {"allow": ["Read"]},
        None,
    ],
)
def test_existing_office_credential_read_denies_are_checked_and_repaired(
    tmp_path, repair, permissions
):
    from fo.doctor import diagnose
    from fo.init import initialize
    from fo.serve.onboarding import derive
    from fo.serve.server import Locator

    root = tmp_path / "office"
    initialize(root)
    legacy = root / "secrets"
    legacy.mkdir()
    (legacy / "keys.toml").write_text('[fred]\napi_key = "synthetic"\n')
    settings = {"env": {"EXAMPLE": "kept"}}
    if permissions is not None:
        settings["permissions"] = permissions
    settings["model"] = "sonnet"
    path = root / ".claude/settings.json"
    path.write_text(json.dumps(settings, indent=4) + "\n")
    path.chmod(0o640)
    before = path.read_bytes(), path.stat().st_mtime_ns
    check = next(c for c in diagnose(root) if c["name"] == "credentials.agent_reads")
    assert check["status"] == "fail"
    assert "fo doctor --fix" in check["reason"]
    item = next(c for c in derive(Locator(root))["doctor"] if c["name"] == check["name"])
    assert "doctor --fix" in item["command"]
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    if repair == "migration":
        ensure_credentials(root)
    else:
        result = fo("doctor", "--fix", "--office", root, "--json")
        assert result.returncode == 0, result.stdout + result.stderr
    updated = json.loads(path.read_text())
    assert list(updated) == list(settings) + ([] if permissions is not None else ["permissions"])
    expected_permissions = {**(permissions or {})}
    expected_permissions["deny"] = [
        *(permissions or {}).get("deny", []),
        "Read(~/Library/Application Support/FamilyOffice/credentials/**)",
        "Read(~/.local/share/family-office/credentials/**)",
    ]
    assert updated == {**settings, "permissions": expected_permissions}
    assert path.stat().st_mode & 0o777 == 0o640
    assert not legacy.exists()
    check = next(c for c in diagnose(root) if c["name"] == "credentials.agent_reads")
    assert check["status"] == "pass"
    assert git(root, "status", "--porcelain").stdout == ""
    before = path.read_bytes(), path.stat().st_mtime_ns
    ensure_credentials(root)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("repair", ["migration", "doctor"])
def test_credential_repairs_do_not_create_absent_claude_settings(tmp_path, repair):
    from fo.doctor import diagnose
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    path = root / ".claude/settings.json"
    path.unlink()
    if repair == "migration":
        ensure_credentials(root)
    else:
        result = fo("doctor", "--fix", "--office", root, "--json")
        assert result.returncode == 0, result.stdout + result.stderr
    assert not path.exists()
    check = next(c for c in diagnose(root) if c["name"] == "credentials.agent_reads")
    assert check["status"] == "pass"


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


def test_doctor_git_repairs_refuse_a_concurrent_office_lock(tmp_path, monkeypatch):
    from contextlib import ExitStack

    from typer.testing import CliRunner

    from fo.cli import app
    from fo.init import initialize
    from fo.lock import office_lock

    root = tmp_path / "office"
    initialize(root)
    ignore = root / ".gitignore"
    original = ignore.read_text().replace("launchd/\n", "")
    ignore.write_text(original)
    head = git(root, "rev-parse", "HEAD").stdout
    with ExitStack() as locks:

        def ensure_then_lock(root):
            directory = ensure_credentials(root)
            locks.enter_context(office_lock(root))
            return directory

        monkeypatch.setattr("fo.config.ensure_credentials", ensure_then_lock)
        result = CliRunner().invoke(app, ["doctor", "--fix", "--office", str(root), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["reason"] == "office_locked"
    assert ignore.read_text() == original
    assert git(root, "rev-parse", "HEAD").stdout == head
    assert git(root, "diff", "--cached", "--name-only").stdout == ""


def test_existing_identity_credential_recording_waits_for_office_lock(tmp_path, monkeypatch):
    from fo.errors import OfficeError
    from fo.init import initialize
    from fo.lock import office_lock

    root = tmp_path / "office"
    initialize(root)
    (root / ".claude/settings.json").write_text("{}\n")
    head = git(root, "rev-parse", "HEAD").stdout
    monkeypatch.setattr("fo.config.LOCK_WAIT", 0.05)
    with office_lock(root):
        with pytest.raises(OfficeError) as error:
            ensure_credentials(root)
    assert error.value.reason == "office_locked"
    assert git(root, "rev-parse", "HEAD").stdout == head
    assert git(root, "diff", "--cached", "--name-only").stdout == ""
    result = fo("doctor", "--fix", "--office", root, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(root, "status", "--porcelain").stdout == ""


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


def test_serve_starts_and_handshakes_when_credentials_are_unavailable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fo.init import initialize
    from fo.serve import handshake, prepare
    from fo.serve.onboarding import derive

    root = tmp_path / "office"
    initialize(root)
    blocked = tmp_path / "blocked"
    blocked.write_text("synthetic non-directory")
    monkeypatch.setenv("FO_CREDENTIALS_HOME", str(blocked / "credentials"))
    monkeypatch.setattr(
        "fo.serve.server.make_server",
        lambda app, host, port: SimpleNamespace(app=app, server_address=(host, port)),
    )
    server, _ = prepare(root, port=0)
    try:
        assert json.loads(handshake(server))["office"] == str(root)
        check = next(
            c for c in derive(server.app.locator)["doctor"] if c["name"] == "credentials.perms"
        )
        assert check["status"] == "fail"
        assert "doctor --fix" in check["command"]
        assert not (root / "secrets").exists()
    finally:
        server.app.runs.shutdown()
