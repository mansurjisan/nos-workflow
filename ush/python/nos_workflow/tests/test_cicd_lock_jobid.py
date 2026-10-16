"""Jenkinsfile Gate lock reclaim and the current_jobid guard of the post/unsuccessful scancel, run as the real shell snippets. Offline. MJ (10/16/26)"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TEXT = (REPO / ".cicd" / "Jenkinsfile").read_text()
JOB = "https://jenkins.example/job/NOS/job/nos-workflow-atl-hercules/"
OTHER = "https://jenkins.example/job/NOS/job/nos-workflow-secofs-hercules/"


def _snippet(anchor: str) -> str:
    """The ''' shell script that contains `anchor`. MJ (10/16/26)"""
    for body in re.findall(r"'''(.*?)'''", TEXT, re.S):
        if anchor in body:
            return body
    raise AssertionError(anchor)


def _gate(tmp_path, holder, age=100, job_url=JOB, build=JOB + "12/", jobid=None, info=True):
    root = tmp_path / "ci"
    if holder is not None:
        (root / ".ci-lock").mkdir(parents=True)
        if info:
            (root / ".ci-lock" / "info").write_text(f"{holder} {int(time.time()) - age}")
        else:
            os.utime(root / ".ci-lock", (time.time() - age,) * 2)
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "scancel").write_text(f'#!/bin/bash\necho "$@" >> {tmp_path}/scancel.calls\n')
    (stubs / "scancel").chmod(0o755)
    ws = tmp_path / "ws"
    (ws / "ci_logs").mkdir(parents=True, exist_ok=True)
    if jobid is not None:
        (ws / "ci_logs" / "current_jobid").write_text(jobid)
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "CI_LOCK_ROOT": str(root), "BUILD_URL": build, "WORKSPACE": str(ws)}
    if job_url is not None:
        env["JOB_URL"] = job_url
    r = subprocess.run(["sh", "-e", "-c", _snippet('LOCK_DIR="${CI_LOCK_ROOT}')], env=env, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr


def test_free_lock_is_acquired(tmp_path):
    assert _gate(tmp_path, None)[:2] == (0, "ACQUIRED")


def test_lock_left_by_an_earlier_build_of_this_job_is_reclaimed_at_once(tmp_path):
    rc, out, err = _gate(tmp_path, JOB + "11/", age=100)
    assert (rc, out) == (0, "ACQUIRED")
    assert "reclaiming the CI lock left by an earlier build of this job" in err and JOB + "11/" in err
    assert (tmp_path / "ci" / ".ci-lock" / "info").read_text().startswith(JOB + "12/")


def test_lock_of_another_job_within_18h_still_blocks(tmp_path):
    rc, out, _ = _gate(tmp_path, OTHER + "5/", age=11443)
    assert rc == 0 and out.startswith("HELD:" + OTHER + "5/")


def test_stale_lock_of_another_job_is_reclaimed_after_18h(tmp_path):
    rc, out, err = _gate(tmp_path, OTHER + "5/", age=64801)
    assert out == "ACQUIRED" and "reclaiming stale CI lock" in err


def test_empty_or_missing_job_url_falls_back_to_the_age_rule(tmp_path):
    for job_url in ("", None):
        d = tmp_path / ("e" if job_url == "" else "n")
        d.mkdir()
        assert _gate(d, JOB + "11/", age=100, job_url=job_url)[1].startswith("HELD:")
    d = tmp_path / "old"
    d.mkdir()
    assert _gate(d, JOB + "11/", age=64801, job_url="")[1] == "ACQUIRED"


def test_a_sibling_job_sharing_the_name_prefix_is_not_this_job(tmp_path):
    assert _gate(tmp_path, JOB.rstrip("/") + "-2/3/", age=100)[1].startswith("HELD:")


def _post(tmp_path, content, build="12"):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "scancel").write_text(f'#!/bin/bash\necho "$@" >> {tmp_path}/scancel.calls\n')
    (stubs / "scancel").chmod(0o755)
    ws = tmp_path / "ws"
    (ws / "ci_logs").mkdir(parents=True)
    if content is not None:
        (ws / "ci_logs" / "current_jobid").write_text(content)
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "WORKSPACE": str(ws)}
    if build is not None:
        env["BUILD_NUMBER"] = build
    r = subprocess.run(["sh", "-e", "-c", _snippet("post/unsuccessful: scancel")], env=env, capture_output=True, text=True)
    calls = tmp_path / "scancel.calls"
    return r, (calls.read_text().strip() if calls.exists() else "")


def test_scancel_runs_for_a_job_this_build_submitted(tmp_path):
    r, calls = _post(tmp_path, "12 555\n")
    assert r.returncode == 0 and calls == "555"


def test_scancel_skips_a_stale_id_from_an_earlier_build(tmp_path):
    r, calls = _post(tmp_path, "11 10137191\n")
    assert r.returncode == 0 and calls == "" and "skipping stale jobid" in r.stdout


def test_scancel_skips_an_old_format_id_without_a_build_number(tmp_path):
    assert _post(tmp_path, "10137191\n")[1] == ""


def test_run_stage_writes_the_build_number_and_manual_when_unset():
    text = (REPO / ".cicd" / "scripts" / "run_stage.sh").read_text()
    assert '"${BUILD_NUMBER:-manual} ${JOBID}"' in text


def _cancelled(tmp_path):
    f = tmp_path / "scancel.calls"
    return f.read_text().strip() if f.exists() else ""


def test_same_job_reclaim_cancels_the_job_the_ended_build_recorded(tmp_path):
    rc, out, err = _gate(tmp_path, JOB + "11/", jobid="11 10137191\n")
    assert out == "ACQUIRED" and _cancelled(tmp_path) == "10137191" and "cancelling job 10137191 left by build 11" in err


def test_same_job_reclaim_cancels_nothing_for_another_build_or_no_file(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    assert _gate(a, JOB + "11/", jobid="9 777\n")[1] == "ACQUIRED" and _cancelled(a) == ""
    b = tmp_path / "b"
    b.mkdir()
    assert _gate(b, JOB + "11/")[1] == "ACQUIRED" and _cancelled(b) == ""


def test_stale_other_job_reclaim_never_cancels(tmp_path):
    assert _gate(tmp_path, OTHER + "5/", age=64801, jobid="5 777\n")[1] == "ACQUIRED" and _cancelled(tmp_path) == ""


def test_lock_without_info_file_does_not_crash_and_uses_the_dir_mtime(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    rc, out, _ = _gate(a, "x", age=100, info=False)
    assert rc == 0 and out.startswith("HELD:")
    b = tmp_path / "b"
    b.mkdir()
    assert _gate(b, "x", age=64801, info=False)[1] == "ACQUIRED"


def test_lock_is_released_before_archiving_in_post_always():
    always = TEXT[TEXT.index("        always {"):TEXT.index("        unsuccessful {")]
    assert always.index('rm -rf "${CI_LOCK_ROOT}/.ci-lock"') < always.index("archiveArtifacts")
