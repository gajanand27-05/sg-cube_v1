"""torch must never be imported.

It was ~524 MB of install for one call site (the speech gate's VAD, via the
silero-vad package), on a product whose floor is an 8 GB laptop with no GPU.
The gate now runs faster-whisper's bundled Silero v5 on onnxruntime. These
tests keep it gone: a lazy `import torch` inside a function body is exactly
how it got in last time, and it would only fail on a machine without torch —
i.e. a user's, never the dev box.
"""
import ast
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BANNED = {"torch", "torchaudio", "torchvision", "silero_vad", "ultralytics"}


def test_no_backend_source_imports_torch():
    offenders = []
    for py in (_ROOT / "backend").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):  # walks function bodies too
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in _BANNED:
                    offenders.append(f"{py.relative_to(_ROOT)}:{node.lineno} {name}")
    assert not offenders, "torch-family imports:\n" + "\n".join(offenders)


def test_the_app_and_the_speech_gate_work_with_torch_unimportable(tmp_path):
    """Blocks torch rather than checking sys.modules afterwards, so the result
    does not depend on whether torch happens to be installed: ctranslate2
    (under faster-whisper) does an OPTIONAL `try: import torch`, and would load
    it on any machine that has it for unrelated reasons. What must hold is that
    nothing NEEDS it — the gate must still measure, not fail open to None."""
    # A fresh interpreter: the suite's own imports must not mask or cause it.
    probe = (
        "import sys\n"
        f"BANNED = {sorted(_BANNED)!r}\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BANNED:\n"
        "            raise ImportError(f'blocked: {name}')\n"
        "sys.meta_path.insert(0, Block())\n"
        "import numpy as np\n"
        "import backend.server.main\n"
        "from backend.ai_modules.speech import speech_gate, stt_whisper, stt_manager\n"
        "from backend.daemon import wake_word, trigger, preload\n"
        "secs = speech_gate.speech_seconds(np.zeros(32000, dtype=np.float32))\n"
        "assert secs == 0.0, f'gate did not measure: {secs!r}'\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in BANNED)\n"
        "assert not bad, bad\n"
    )
    env = {**__import__("os").environ, "SG_CUBE_HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", probe], cwd=_ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
