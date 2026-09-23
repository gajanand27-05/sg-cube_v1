"""The suite must not write into the real capture archive.

Found while confirming the archive was ready to collect calibration data.
Running three test files added three records to
`backend/database/captures`:

    wake records before: 186
    ... 9 passed ...
    wake records after:  189

`test_barge_in_real_audio` and `test_wake_preroll` drive the REAL listen loop,
and the wake branch archives the pre-roll that fired it — reaching the
module-level `_ARCHIVE_DIR`, not a fixture. So every suite run injects
synthetic wakes into the production sample.

Exactly the hazard conftest already guards for `dogfooding.json` and
`contacts.json`, and it bites harder here, because this archive is about to
be the EVIDENCE BASE for two open questions:

  * whether '[unk] [unk] [unk] onyx' false wakes are marginal or solid —
    answered by replaying archived wake triggers;
  * where _FOLLOWUP_MIN_RMS belongs — answered by the RMS distribution of
    archived follow-ups.

Both are distribution questions. Test-generated records do not just add
noise, they add noise with a systematic shape: the same fixture clip, the
same synthetic frames, the same handful of RMS values, repeated once per
suite run. A calibration drawn from that would be measuring the fixtures.
"""
import sys
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import capture_archive as ca

REAL_ARCHIVE = _root / "backend" / "database" / "captures"


def test_the_archive_dir_is_redirected_away_from_production():
    """The guard itself. If this fails, every other test in the suite is
    writing into the user's real sample."""
    assert ca._ARCHIVE_DIR.resolve() != REAL_ARCHIVE.resolve(), (
        f"capture_archive is pointed at the production archive "
        f"({ca._ARCHIVE_DIR}); a suite run injects synthetic wakes into the "
        "sample that _FOLLOWUP_MIN_RMS and the false-wake question will be "
        "calibrated from"
    )


def test_archiving_during_the_suite_lands_in_the_sandbox(tmp_path):
    """Drive the real archive() and prove the bytes go somewhere harmless."""
    before = len(list(REAL_ARCHIVE.glob("*.wav"))) if REAL_ARCHIVE.exists() else 0

    wav = ca.archive(np.zeros(1600, dtype=np.int16), "suite probe",
                     trigger="wake", extra={"bucket": "wake_trigger"})

    after = len(list(REAL_ARCHIVE.glob("*.wav"))) if REAL_ARCHIVE.exists() else 0
    assert after == before, (
        f"the suite wrote {after - before} file(s) into {REAL_ARCHIVE}"
    )
    if wav is not None:
        assert REAL_ARCHIVE.resolve() not in wav.resolve().parents


def test_gate_rejections_do_not_land_in_production():
    """The histogram is a single accumulating file, so one polluting run
    contaminates every later read of it rather than adding one row."""
    before = (REAL_ARCHIVE / ca.GATE_REJECTIONS_FILE).exists()
    ca.record_gate_rejection(123, floor=400)
    after_path = REAL_ARCHIVE / ca.GATE_REJECTIONS_FILE
    if not before:
        assert not after_path.exists(), (
            "a suite run created the production rejection histogram; its "
            "counts would then be fixture frames, not the user's room"
        )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
