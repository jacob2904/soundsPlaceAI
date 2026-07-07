"""Tests for the cross-platform installer and the runtime path bootstrap."""

import importlib.util
from pathlib import Path

import pytest

from cinesfx import installer
from cinesfx.installer import (
    PLUGIN_ID,
    InstallError,
    install_from_repo,
    install_payload,
    plugin_dir,
    plugins_root,
    stage_payload,
    uninstall,
)


# ---------------------------------------------------------------- target paths


def test_plugins_root_per_os():
    mac = plugins_root("Darwin", env={})
    assert mac.as_posix().endswith(
        "Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins"
    )
    win = plugins_root("Windows", env={"PROGRAMDATA": r"C:\ProgramData"})
    assert "Support" in win.parts and "Workflow Integration Plugins" in win.parts
    linux = plugins_root("Linux", env={})
    assert linux == Path("/opt/resolve/Workflow Integration Plugins")


def test_plugins_root_env_override_wins():
    root = plugins_root("Darwin", env={"CINESFX_PLUGINS_DIR": "/tmp/custom"})
    assert root == Path("/tmp/custom")


def test_plugin_dir_appends_id():
    assert plugin_dir("Linux", env={}).name == PLUGIN_ID


# ------------------------------------------------------------------- staging


def test_stage_payload_copies_expected_layout(tmp_path):
    payload = tmp_path / "payload"
    staged = stage_payload(installer.repo_root(), payload)

    assert "CineSFX.py" in staged
    for expected in (
        "CineSFX.py",
        "cinesfx_bootstrap.py",
        "manifest.xml",
        "config.example.yaml",
    ):
        assert (payload / expected).is_file(), expected
    assert (payload / "cinesfx" / "__init__.py").is_file()
    assert (payload / "cinesfx" / "installer.py").is_file()
    # __pycache__ must never be bundled.
    assert not list(payload.rglob("__pycache__"))


def test_stage_payload_rejects_non_repo(tmp_path):
    with pytest.raises(InstallError):
        stage_payload(tmp_path / "empty", tmp_path / "out")


# ------------------------------------------------------------------ install


def test_install_payload_copies_into_plugin_dir(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "CineSFX.py").write_text("# panel")
    (payload / "manifest.xml").write_text("<x/>")

    env = {"CINESFX_PLUGINS_DIR": str(tmp_path / "resolve")}
    result = install_payload(payload, system="Linux", env=env)

    assert result.plugin_dir == Path(tmp_path / "resolve") / PLUGIN_ID
    assert (result.plugin_dir / "CineSFX.py").is_file()
    assert "CineSFX.py" in result.items
    # Idempotent: installing again just refreshes.
    again = install_payload(payload, system="Linux", env=env)
    assert again.plugin_dir == result.plugin_dir


def test_install_payload_rejects_bad_payload(tmp_path):
    (tmp_path / "notpayload").mkdir()
    with pytest.raises(InstallError):
        install_payload(tmp_path / "notpayload", system="Linux", env={})


def test_install_from_repo_and_uninstall(tmp_path):
    env = {"CINESFX_PLUGINS_DIR": str(tmp_path / "resolve")}
    result = install_from_repo(system="Linux", env=env)

    assert (result.plugin_dir / "cinesfx" / "__init__.py").is_file()
    assert (result.plugin_dir / "cinesfx_bootstrap.py").is_file()

    assert uninstall(system="Linux", env=env) is True
    assert not result.plugin_dir.exists()
    assert uninstall(system="Linux", env=env) is False  # nothing left


# ------------------------------------------------------- runtime bootstrap


def _load_bootstrap():
    path = Path(__file__).resolve().parent.parent / "plugin" / "cinesfx_bootstrap.py"
    spec = importlib.util.spec_from_file_location("cinesfx_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_pkg(dir_path: Path) -> None:
    (dir_path / "cinesfx").mkdir(parents=True, exist_ok=True)
    (dir_path / "cinesfx" / "__init__.py").write_text("")


def test_bootstrap_package_root_installed_layout(tmp_path):
    boot = _load_bootstrap()
    plugin = tmp_path / "com.soundsplaceai.cinesfx"
    _make_pkg(plugin)  # cinesfx/ sits inside the plugin folder
    assert boot.package_root(plugin, env={}) == plugin


def test_bootstrap_package_root_dev_checkout(tmp_path):
    boot = _load_bootstrap()
    repo = tmp_path / "repo"
    (repo / "plugin").mkdir(parents=True)
    _make_pkg(repo)  # cinesfx/ is one level above the plugin folder
    assert boot.package_root(repo / "plugin", env={}) == repo


def test_bootstrap_home_override_wins(tmp_path):
    boot = _load_bootstrap()
    home = tmp_path / "home"
    _make_pkg(home)
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    assert boot.package_root(plugin, env={"CINESFX_HOME": str(home)}) == home


def test_bootstrap_apply_wires_sys_path_and_ffmpeg(tmp_path):
    boot = _load_bootstrap()
    plugin = tmp_path / "com.soundsplaceai.cinesfx"
    _make_pkg(plugin)
    (plugin / "libs").mkdir()
    (plugin / "ffmpeg").mkdir()

    fake_path: list[str] = []
    env: dict[str, str] = {"PATH": "/usr/bin"}
    root = boot.apply(plugin, env=env, sys_path=fake_path)

    assert root == plugin
    assert str(plugin) in fake_path            # package root added
    assert str(plugin / "libs") in fake_path   # bundled deps added
    assert str(plugin / "ffmpeg") in env["PATH"].split(":")  # ffmpeg on PATH
