"""JNOS_PREP must propagate the ex-script exit status (static check)."""
import re
from pathlib import Path

JOB = Path(__file__).resolve().parents[4] / "jobs" / "JNOS_PREP"


def test_prep_status_captured_and_fatal():
    text = JOB.read_text()
    assert re.search(r"exnos_prep\.sh\n\s*export err=\$\?", text)
    fail = text.index('if [ "${err:-0}" -ne 0 ]')
    assert "exit $err" in text[fail:fail + 400]
    assert fail < text.index("completed normally")
    assert fail < text.index("rm -rf $DATA")
