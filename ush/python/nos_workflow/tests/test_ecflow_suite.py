"""ecFlow suite, offline: the def parses, every task script preprocesses without unresolved variables, and the PBS
resources equal the cards (STOFS-2D-Global: the launcher's qsub overrides). Pure python, no ecflow module. MJ (10/20/26)"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
ECF = REPO / "ecf"
STAGES = ("prep", "nowcast", "forecast", "post")
CARD_DIRS = {
    "secofs_ufs": "pbs",
    "secofs_ufs_ww3": "pbs/secofs_ufs_ww3",
    "stofs_3d_atl_ufs": "pbs/stofs_3d_atl_ufs",
    "stofs_3d_atl_ufs_standalone": "pbs/stofs_3d_atl_ufs_standalone",
}
CYCLES = {
    "secofs_ufs": ["00", "06", "12", "18"],
    "secofs_ufs_ww3": ["12"],
    "stofs_3d_atl_ufs": ["12"],
    "stofs_3d_atl_ufs_standalone": ["12"],
    "stofs_2d_glo": ["00", "06", "12", "18"],
}
TRIES2 = {"secofs_ufs", "secofs_ufs_ww3", "stofs_3d_atl_ufs"}   # replaces the cards' ParMETIS retry; the others have none. MJ (10/21/26)
GENERATED = {"ECF_NAME": "/nos_workflow/x", "ECF_HOST": "h", "ECF_PORT": "1", "ECF_PASS": "p", "ECF_TRYNO": "1",
             "ECF_JOB": "j", "ECF_JOBOUT": "o", "TASK": "t", "FAMILY": "f", "SUITE": "nos_workflow"}


class Node:
    def __init__(self, kind, name, parent):
        self.kind, self.name, self.parent = kind, name, parent
        self.vars, self.kids, self.trigger, self.attrs = {}, [], None, []

    @property
    def path(self):
        return (self.parent.path if self.parent else "") + "/" + self.name

    def lookup(self, key):
        n = self
        while n:
            if key in n.vars:
                return n.vars[key]
            n = n.parent
        return GENERATED.get(key)


def parse_def(text):
    root = Node("root", "", None)
    stack, cur = [root], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        if word in ("suite", "family"):
            n = Node(word, rest.strip(), stack[-1])
            stack[-1].kids.append(n)
            stack.append(n)
            cur = None
        elif word in ("endfamily", "endsuite"):
            stack.pop()
            cur = None
        elif word == "task":
            cur = Node("task", rest.strip(), stack[-1])
            stack[-1].kids.append(cur)
        else:
            node = cur or stack[-1]
            if word == "edit":
                m = re.match(r"(\S+)\s+(?:'(.*?)'|(\S+))\s*(?:#.*)?$", rest)
                node.vars[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
            elif word == "trigger":
                node.trigger = rest
            elif word == "repeat":
                _, name, first, last = rest.split()
                node.vars[name] = first
                node.attrs.append(("repeat", name, first, last))
            else:
                node.attrs.append((word, rest))
    return root.kids[0]


def tasks(suite):
    for fam in suite.kids:
        if fam.kind != "family":
            continue
        day = fam.kids[0]
        for cyc in day.kids:
            for t in cyc.kids:
                yield fam.name, cyc.name, t


def subst(text, node, unresolved):
    pat = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)(?::([^%\s]*))?%")
    for _ in range(8):
        def rep(m):
            v = node.lookup(m.group(1))
            if v is None:
                if m.group(2) is not None:
                    return m.group(2)
                unresolved.add(m.group(1))
                return "?"
            return v
        new = pat.sub(rep, text)
        if new == text:
            return new
        text = new
    return text


def preprocess(path, node, unresolved, problems):
    out, manual = [], False
    for line in path.read_text().splitlines():
        s = line.strip()
        if s == "%manual":
            manual = True
            continue
        if manual:
            manual = s != "%end"
            continue
        m = re.match(r'%include\s+[<"](.+)[>"]$', s)
        if m:
            name = subst(m.group(1), node, unresolved)
            inc = ECF / "include" / name
            if not inc.exists():
                problems.append("missing include %s" % name)
                continue
            out += preprocess(inc, node, unresolved, problems)
            continue
        if not s.startswith("#") and line.count("%") % 2:
            problems.append("odd number of %% in: %s" % s)       # ecFlow: "Mismatched ecfmicro(%) count". MJ (10/21/26)
        out.append(subst(line, node, unresolved))
    return out


def build():
    suite = parse_def((ECF / "defs" / "nos_workflow.def").read_text())
    jobs = {}
    for system, cyc, t in tasks(suite):
        unresolved, problems = set(), []
        lines = preprocess(ECF / "scripts" / (t.name + ".ecf"), t, unresolved, problems)
        if unresolved:
            problems.append("unresolved %s" % sorted(unresolved))
        jobs[(system, cyc, t.name.replace("jnos_", ""))] = (t, lines, problems)
    return suite, jobs


SUITE, JOBS = build()


def pbs_l(lines):
    res = {}
    for l in lines:
        m = re.match(r"#PBS\s+-l\s+(\S+)", l)
        if m:
            for part in m.group(1).split(","):
                k, _, v = part.partition("=")
                res[k] = v
    return res


def card_res(system, stage):
    return pbs_l((REPO / CARD_DIRS[system] / ("jnos_%s_00.pbs" % stage)).read_text().splitlines())


def launcher_2d():
    text = (REPO / "pbs" / "stofs_2d_glo" / "launch_stofs_2d_glo.sh").read_text()
    g = lambda pat: re.search(pat, text).group(1)
    return {"prep_sel": g(r'PREPSEL="([^"]+)"'), "post_sel": g(r'POSTSEL="([^"]+)"'), "prep_wall": g(r"PWALL=(\S+);"),
            "nowcast_wall": g(r"NWALL=(\S+)\s"), "forecast_wall": g(r'sub forecast "\$\{FC\}" (\S+)'),
            "post_place": g(r"PLACE=(\S+) sub post"), "post_wall": g(r'sub post "\$\{PREP\}" (\S+)')}


def test_suite_layout():
    assert SUITE.name == "nos_workflow"
    assert [f.name for f in SUITE.kids if f.kind == "family"] == list(CYCLES)
    for fam in SUITE.kids:
        if fam.kind != "family":
            continue
        assert ("defstatus", "suspended") in fam.attrs, "%s must start suspended: SECOFS cron is live" % fam.name
        day = fam.kids[0]
        assert day.name == "day" and [a[:2] for a in day.attrs] == [("repeat", "PDY")]   # a defstatus is re-applied on requeue, so not on this node. MJ (10/21/26)
        assert [c.name for c in day.kids] == CYCLES[fam.name]
        for c in day.kids:
            assert [t.name for t in c.kids] == ["jnos_" + s for s in STAGES]
    assert len(JOBS) == 44


def test_include_path_matches_package_home():
    # ecFlow does not expand variables in ECF_INCLUDE, so the def carries the path twice. MJ (10/21/26)
    assert SUITE.vars["ECF_INCLUDE"] == SUITE.vars["PACKAGEHOME"] + "/ecf/include"
    assert SUITE.vars["ECF_FILES"] == "%PACKAGEHOME%/ecf/scripts"


@pytest.mark.parametrize("key", sorted(JOBS), ids=["/".join(k) for k in sorted(JOBS)])
def test_task_script_preprocesses(key):
    t, lines, problems = JOBS[key]
    assert not problems, problems
    assert lines[0].startswith("#PBS -N ")


@pytest.mark.parametrize("system", list(CYCLES))
@pytest.mark.parametrize("stage", STAGES)
def test_pbs_resources_match_cards(system, stage):
    got = pbs_l(JOBS[(system, CYCLES[system][0], stage)][1])
    if system == "stofs_2d_glo":   # the launcher overrides the card per job; post runs on the prep card. MJ (10/21/26)
        ln = launcher_2d()
        want = {k: v for k, v in pbs_l((REPO / "pbs" / "stofs_2d_glo" / ("jnos_%s_00.pbs" % ("prep" if stage == "post" else stage))).read_text().splitlines()).items()
                if k in ("select", "place")}
        want["walltime"] = ln[stage + "_wall"]
        if stage in ("prep", "post"):
            want["select"] = ln[stage + "_sel"]
        if stage == "post":
            want["place"] = ln["post_place"]
    else:
        want = {k: v for k, v in card_res(system, stage).items() if k in ("select", "place", "walltime")}
    assert {k: got[k] for k in ("select", "place", "walltime")} == want


@pytest.mark.parametrize("system", list(CYCLES))
def test_cycles_share_resources_and_job_names_are_unique(system):
    for s in STAGES:
        heads = {tuple(l for l in JOBS[(system, c, s)][1] if l.startswith("#PBS") and not l.startswith("#PBS -N")) for c in CYCLES[system]}
        assert len(heads) == 1, s
    names = [JOBS[k][1][0] for k in JOBS]
    assert len(set(names)) == len(names)


def test_pbs_header_form():
    for key, (t, lines, _) in JOBS.items():
        hdr = [l for l in lines if l.startswith("#PBS")]
        assert hdr[1:4] == ["#PBS -j oe", "#PBS -S /bin/bash", "#PBS -q dev"], key
        assert "#PBS -A ESTOFS-DEV" in hdr and hdr[-1] == "#PBS -l debug=true", key


def test_atl_variants_never_share_a_comout():
    cpl, sa = SUITE.kids[2], SUITE.kids[3]
    assert (cpl.name, sa.name) == ("stofs_3d_atl_ufs", "stofs_3d_atl_ufs_standalone")
    assert cpl.lookup("OFS") == sa.lookup("OFS") == "stofs_3d_atl_ufs"
    assert cpl.lookup("COMROOT") != sa.lookup("COMROOT") and sa.lookup("COMROOT").endswith("/com_atl_sa")
    assert subst(sa.lookup("OFS_YAML"), sa, set()) == "stofs_3d_atl_ufs_standalone"
    assert subst(cpl.lookup("OFS_YAML"), cpl, set()) == "stofs_3d_atl_ufs"
    sec = SUITE.kids[0]
    assert sec.lookup("COMROOT") == cpl.lookup("COMROOT")   # shared com, RUN-prefixed directories. MJ (10/21/26)


def test_every_module_and_env_set_exists():
    for key, (t, _, _) in JOBS.items():
        for var in ("PREP_MODSET", "RUN_MODSET", "POST_MODSET"):
            assert (ECF / "include" / ("nos_modules_%s.h" % t.lookup(var))).exists(), (key, var)
        assert (ECF / "include" / ("nos_env_%s.h" % t.lookup("ENVSET"))).exists(), key


def test_ecf_tries_policy():
    for system, cyc, t in tasks(SUITE):
        want = 2 if t.name == "jnos_post" or (system in TRIES2 and t.name in ("jnos_nowcast", "jnos_forecast")) else 1
        assert int(t.lookup("ECF_TRIES")) == want, (system, cyc, t.name)


def test_prep_start_times_follow_the_live_cron():
    guide = (REPO / "docs" / "secofs_run_guide.md").read_text()
    cron = {}
    for m in re.finditer(r"^(\d+)\s+(\d+)\s+\* \* \* \S*/launch_(secofs_ufs_ww3|secofs_ufs)\.sh (\d\d)\b", guide, re.M):
        cron[(m.group(3), m.group(4))] = "%02d%02d" % (int(m.group(2)), int(m.group(1)))
    assert len(cron) == 5
    want = dict(cron)
    want.update({("stofs_3d_atl_ufs", "12"): "1815", ("stofs_3d_atl_ufs_standalone", "12"): "1815"})
    want.update({("stofs_2d_glo", c): h for c, h in zip(CYCLES["stofs_2d_glo"], ("0500", "1100", "1700", "2300"))})
    for system, cyc, t in tasks(SUITE):
        if t.name != "jnos_prep":
            continue
        m = re.search(r"TIME >= (\d{4})\)\)$", t.trigger)
        assert m and m.group(1) == want[(system, cyc)], (system, cyc, t.trigger)
        prev = CYCLES[system].index(cyc) - 1
        assert ("../%s/jnos_nowcast == complete" % CYCLES[system][prev] in t.trigger) == (prev >= 0), (system, cyc)


def test_stage_dependencies_inside_a_cycle():
    for system, cyc, t in tasks(SUITE):
        want = {"jnos_nowcast": "jnos_prep", "jnos_forecast": "jnos_nowcast", "jnos_post": "jnos_forecast"}.get(t.name)
        if want:
            assert t.trigger == want + " == complete", (system, cyc, t.name)


def test_2d_cold_start_and_post_variables():
    ln = launcher_2d()
    d = SUITE.kids[4]
    assert d.lookup("PREP_SEGMENT") == "ncst fcst" and d.lookup("POST_SEGMENT") == "anomaly bias ncdiff grib2 ncrcat"
    assert d.lookup("DCOMROOT") == "" and d.lookup("KEEPDATA") == "NO" and d.lookup("ADCIRC_MODE") == "ops"
    assert d.lookup("PREP_ENV") == "" and ln["post_wall"] == d.lookup("POST_WALLTIME")


def test_pschism_run_ver_follows_the_standalone_card():
    inc = (ECF / "include" / "nos_modules_pschism.h").read_text()
    card = (REPO / CARD_DIRS["stofs_3d_atl_ufs_standalone"] / "jnos_nowcast_00.pbs").read_text()
    for path in ("IT-stofs.v2.1.0/versions/stofs_3d_atl/run.ver", "/lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver"):
        assert path in card and path in inc, path
    assert SUITE.kids[3].vars.get("STOFS_RUNVER", "") == ""   # the card's default stands unless the def names a file. MJ (10/21/26)


def test_module_loads_that_can_fail_do_not_end_the_job():
    # prod_util/2.0.17 (run.ver) and a placeholder ecflow version are unknown on WCOSS2; the jobs run under set -e. MJ (10/21/26)
    for f in (ECF / "include").glob("*.h"):
        for l in f.read_text().splitlines():
            if re.search(r"\bmodule load (prod_util|ecflow)", l) and not l.lstrip().startswith("#"):
                assert "||" in l, (f.name, l)
    assert not re.search(r"module load prod_", (ECF / "include" / "head.h").read_text())


def test_prod_envir_loads_with_envir_unset_like_the_cards():
    for key, (t, lines, _) in JOBS.items():
        s = [l.strip() for l in lines]
        load = next(i for i, l in enumerate(s) if l.startswith("module load prod_envir"))
        back = max(i for i, l in enumerate(s) if l == "export envir=dev")   # head.h exports it too, at the top. MJ (10/21/26)
        assert s.index("unset envir") < load < back, key


def test_post_prints_python_after_the_ecflow_reload():
    s = [l.strip() for l in JOBS[("secofs_ufs", "12", "post")][1]]
    echo = next(i for i, l in enumerate(s) if l.startswith('echo "post: python3'))
    assert echo > max(i for i, l in enumerate(s) if l.startswith("module load ecflow"))
