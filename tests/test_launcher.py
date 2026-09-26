"""tools/launch.py + daemon single instance.

Real processes, but only ones this test starts: a fake backend (a temp
package whose argv is exactly `python -m backend.daemon.main`) and decoys.
Never the user's desktop, browser, or any process the test did not spawn.
The suite's SG_CUBE_HOME is a temp dir, so the mutex and PID file here can't
collide with a real SG-CUBE.
"""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import launch  # noqa: E402

from backend.daemon.main import pid_file  # noqa: E402

PY = sys.executable


def _real(popen: subprocess.Popen) -> psutil.Process:
    """The interpreter itself: a venv python.exe is a redirector that runs the
    base interpreter as its child, and that child is what the backend sees."""
    p = psutil.Process(popen.pid)
    if Path(sys.executable).resolve() == Path(sys._base_executable).resolve():
        return p  # not a venv: no redirector
    for _ in range(100):
        if kids := p.children():
            return kids[0]
        time.sleep(0.05)
    raise AssertionError("venv redirector never started the interpreter")


def _write_pid(proc: psutil.Process, port: int = 1) -> None:
    pid_file().parent.mkdir(parents=True, exist_ok=True)
    pid_file().write_text(json.dumps({"pid": proc.pid, "create_time": proc.create_time(), "port": port}))


@pytest.fixture
def spawned():
    procs = []
    yield procs
    for p in procs:
        try:
            for k in psutil.Process(p.pid).children(recursive=True):
                k.kill()
        except psutil.Error:
            pass
        p.kill()
        p.wait()
    pid_file().unlink(missing_ok=True)


@pytest.fixture
def fake_backend(tmp_path, spawned):
    """A process whose argv is exactly `<python> -m backend.daemon.main`."""
    pkg = tmp_path / "backend" / "daemon"
    pkg.mkdir(parents=True)
    (tmp_path / "backend" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "main.py").write_text("import time\ntime.sleep(60)\n")
    p = subprocess.Popen([PY, "-m", "backend.daemon.main", "--port", "1"], cwd=tmp_path)
    spawned.append(p)
    return _real(p)


def _decoy(spawned, code="import time; time.sleep(60)", *extra):
    p = subprocess.Popen([PY, "-c", code, *extra])
    spawned.append(p)
    return _real(p)


# ── which process counts as SG-CUBE ─────────────────────────────────────

def test_fake_backend_is_recognised(fake_backend):
    _write_pid(fake_backend, port=8123)
    assert launch.running_instance() == {"pid": fake_backend.pid, "port": 8123}


def test_command_line_text_alone_is_not_sg_cube(spawned):
    # Contains "-m backend.daemon.main" as text, but it is `python -c`.
    decoy = _decoy(spawned, "import time; time.sleep(60)", "-m", "backend.daemon.main")
    _write_pid(decoy)
    assert launch.running_instance() is None
    assert not pid_file().exists(), "a PID file naming a non-SG-CUBE process is stale"


def test_reused_pid_with_other_start_time_is_not_sg_cube(fake_backend):
    pid_file().write_text(json.dumps({"pid": fake_backend.pid,
                                      "create_time": fake_backend.create_time() - 100, "port": 1}))
    assert launch.running_instance() is None


def test_dead_pid_is_stale(spawned):
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    pid_file().write_text(json.dumps({"pid": p.pid, "create_time": 0, "port": 1}))
    assert launch.running_instance() is None
    assert not pid_file().exists()


# ── Stop SG-CUBE ─────────────────────────────────────────────────────────

def test_stop_when_nothing_runs_says_so():
    pid_file().unlink(missing_ok=True)
    assert launch.stop() == "SG-CUBE is not running."


def test_stop_never_touches_another_python(spawned):
    decoy = _decoy(spawned, "import time; time.sleep(60)", "-m", "backend.daemon.main")
    _write_pid(decoy)
    assert launch.stop() == "SG-CUBE is not running."
    assert decoy.is_running()


def test_stop_stops_only_sg_cube(fake_backend, spawned):
    bystander = _decoy(spawned)
    _write_pid(fake_backend)
    assert launch.stop() == "SG-CUBE stopped."
    fake_backend.wait(timeout=10)
    assert not fake_backend.is_running()
    assert bystander.is_running()
    assert not pid_file().exists()


# ── the launcher's start path (no browser, no dialog) ───────────────────

@pytest.fixture
def ui(monkeypatch):
    seen = {"opened": [], "messages": [], "started": 0}
    monkeypatch.setattr(launch.webbrowser, "open", seen["opened"].append)
    monkeypatch.setattr(launch, "_message", lambda text, error=False: seen["messages"].append((text, error)))

    def _start(port):
        seen["started"] += 1
        return subprocess.Popen([PY, "-c", "import sys; sys.exit(1)"])  # dies at once
    monkeypatch.setattr(launch, "start_server", _start)
    return seen


def test_running_instance_opens_its_hud_and_starts_nothing(fake_backend, ui, monkeypatch):
    _write_pid(fake_backend, port=8123)
    monkeypatch.setattr(launch, "is_up", lambda port: port == 8123)
    assert launch.main([]) == 0
    assert ui["started"] == 0
    assert ui["opened"] == ["http://127.0.0.1:8123/"]


def test_failed_start_is_visible(ui, monkeypatch):
    pid_file().unlink(missing_ok=True)
    monkeypatch.setattr(launch, "is_up", lambda port: False)
    assert launch.main([]) == 1
    assert ui["started"] == 1 and ui["opened"] == []
    (text, error), = ui["messages"]
    assert error and "did not start" in text
    assert "sg_cube.log" in text and "launcher_boot.log" in text


def test_stop_command_reports_in_a_dialog(ui):
    pid_file().unlink(missing_ok=True)
    assert launch.main(["stop"]) == 0
    assert ui["messages"] == [("SG-CUBE is not running.", False)]


# ── the daemon refuses a second backend for the same data folder ────────

def test_mutex_blocks_a_second_backend(spawned, tmp_path):
    code = textwrap.dedent("""
        import sys, time
        from backend.daemon.main import claim_single_instance
        print(claim_single_instance(8123), flush=True)
        time.sleep(float(sys.argv[1]))
    """)
    first = subprocess.Popen([PY, "-c", code, "30"], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    spawned.append(first)
    assert first.stdout.readline().strip() == "True"
    second = subprocess.run([PY, "-c", code, "0"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert second.stdout.strip() == "False"
    info = json.loads(pid_file().read_text())
    assert info["port"] == 8123 and info["pid"] == _real(first).pid
