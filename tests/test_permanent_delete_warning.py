"""delete_file uses the shell's undoable delete, which silently deletes for
good where there is no Recycle Bin. The prompt must say "permanent delete"
before the user says yes, and the result must not claim the Recycle Bin.

Measured on this machine: only fixed drives (C:, D:), both with a bin
(NukeOnDelete=0, MaxCapacity ~13.6 GB) — no USB or network volume to delete
from. So the non-fixed cases are simulated at the drive-type seam; the fixed
case runs against the real registry."""
import pytest

import backend.core.tools  # noqa: F401
from backend.core.agent import tool_policy
from backend.core.tools import files
from backend.core.tools.registry import REGISTRY


@pytest.fixture
def victim(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "SEARCH_ROOTS", [tmp_path])
    f = tmp_path / "report.txt"
    f.write_text("x" * 2048)
    monkeypatch.setattr(files, "_to_recycle_bin", lambda p: p.unlink())
    return f


def test_a_real_fixed_drive_with_a_bin_is_recoverable(victim):
    assert files.permanent_delete_reason(victim) is None


@pytest.mark.parametrize("patch, why", [
    ({"_drive_type": lambda root: 2}, "no Recycle Bin"),                             # removable (USB)
    ({"_drive_type": lambda root: 4}, "no Recycle Bin"),                             # network drive
    ({"_bitbucket_settings": lambda root: {"NukeOnDelete": 1}}, "turned off"),
    ({"_bitbucket_settings": lambda root: {"MaxCapacity": 0.001}}, "larger than"),   # ~1 KB bin
])
def test_the_prompt_says_permanent_delete(victim, monkeypatch, patch, why):
    for name, fn in patch.items():
        monkeypatch.setattr(files, name, fn)
    prep = tool_policy.prepare_confirmation("delete_file", {"file": str(victim)})
    assert prep.details[0].startswith("PERMANENT DELETE") and why in prep.details[0]
    assert str(victim) in prep.details

    r = REGISTRY["delete_file"].func(str(victim))
    assert r.status == "success"
    assert r.message.startswith("Permanently deleted") and "Recycle Bin" not in r.message.split("—")[0]
    assert r.data["permanent"] is True


def test_recoverable_delete_still_says_recycle_bin(victim):
    prep = tool_policy.prepare_confirmation("delete_file", {"file": str(victim)})
    assert not any("PERMANENT" in d for d in prep.details)
    assert "Recycle Bin" in REGISTRY["delete_file"].func(str(victim)).message


def test_unsure_means_warn(victim, monkeypatch):
    def boom(root):
        raise OSError("volume vanished")
    monkeypatch.setattr(files, "_drive_type", boom)
    assert "could not confirm a Recycle Bin" in files.permanent_delete_reason(victim)


def test_a_folder_is_judged_by_its_total_size(tmp_path, monkeypatch):
    """Three 600-byte files, each under a ~1 KB bin, together over it."""
    folder = tmp_path / "album"
    folder.mkdir()
    for i in range(3):
        (folder / f"p{i}.jpg").write_bytes(b"x" * 600)
    monkeypatch.setattr(files, "_bitbucket_settings", lambda root: {"MaxCapacity": 0.001})
    assert all((folder / f"p{i}.jpg").stat().st_size < 0.001 * 1024 * 1024 for i in range(3))
    assert files._total_size(folder) == 1800
    assert "larger than the Recycle Bin" in files.permanent_delete_reason(folder)
    assert files.permanent_delete_reason(folder / "p0.jpg") is None
