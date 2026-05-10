"""NCO environment normalization.

The shell J-jobs export a forest of environment variables (NCO
convention: ``HOMEnos``, ``FIXofs``, ``COMOUT``, ``DATA`` …). Python
stages need a typed, validated handle on those variables instead of
peppering ``os.environ.get`` calls through the codebase. ``NCOEnv`` is
that handle — built once at the top of a stage and passed downstream.

Anything missing that the stage actually needs raises ``ConfigError``
with a message naming the variable, so on-call doesn't have to chase a
``KeyError`` through a stack trace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .bash_compat import cyc_str
from .errors import ConfigError


def _derive_net(ofs: str) -> str:
    """Best-effort mapping from OFS name to NCO ``NET`` namespace.

    STOFS-family systems live under ``NET=stofs``; everything else —
    SECOFS, CBOFS, LEOFS, etc. — defaults to ``NET=nos``. Operators can
    override by exporting ``NET`` themselves.
    """
    name = ofs.lower()
    if name.startswith("stofs"):
        return "stofs"
    return "nos"


def _require(env: dict, key: str) -> str:
    """Look up ``key`` in ``env`` or raise ``ConfigError`` with a clear msg."""
    val = env.get(key)
    if val is None or val == "":
        raise ConfigError(
            f"required NCO env var {key!r} is not set (export it from the J-job "
            f"or pass --{key.lower()} to the CLI)"
        )
    return val


def _path_or_default(env: dict, key: str, default: Path) -> Path:
    val = env.get(key)
    if val is None or val == "":
        return default
    return Path(val)


@dataclass(frozen=True)
class NCOEnv:
    """Frozen, typed view of the NCO environment for a single stage run.

    All directory fields are ``pathlib.Path``; all string fields are
    plain ``str`` (already validated, e.g. ``cyc`` is two digits). The
    dataclass is frozen because we treat one ``NCOEnv`` instance as the
    immutable ground truth for one stage; mutations belong in a fresh
    instance constructed via ``dataclasses.replace``.
    """

    ofs: str
    pdy: str
    cyc: str
    cycle: str
    net: str
    run: str
    homenos: Path
    fixofs: Path
    parmnos: Path
    ushnos: Path
    execnos: Path
    scriptsnos: Path
    comin: Path
    comout: Path
    comoutroot: Path
    dataroot: Path
    data: Path
    pgmout: str
    jlogfile: str
    sendcom: str
    senddbn: str
    keepdata: str

    @classmethod
    def from_env(cls, ofs: Optional[str] = None) -> "NCOEnv":
        """Build an ``NCOEnv`` from ``os.environ``.

        ``ofs`` lets the CLI override the env-derived OFS name. If not
        passed, we read ``$OFS`` then fall back to ``$RUN``. Everything
        else comes from the environment with the documented NCO
        defaults; required variables raise ``ConfigError``.
        """
        env = os.environ

        # Identity ---------------------------------------------------------
        ofs_value = ofs or env.get("OFS") or env.get("RUN")
        if not ofs_value:
            raise ConfigError(
                "OFS not set: pass --ofs, or export OFS / RUN before invoking "
                "the stage"
            )
        ofs_value = ofs_value.lower()

        pdy = _require(env, "PDY")
        cyc_raw = _require(env, "cyc")
        cyc = cyc_str(cyc_raw)
        cycle = env.get("cycle") or f"t{cyc}z"

        net = env.get("NET") or _derive_net(ofs_value)
        run = env.get("RUN") or ofs_value

        # Directories ------------------------------------------------------
        homenos = _path_or_default(env, "HOMEnos", Path("/lfs/h1/nos") / net / ofs_value)
        fixofs = _path_or_default(env, "FIXofs", homenos / "fix")
        parmnos = _path_or_default(env, "PARMnos", homenos / "parm")
        ushnos = _path_or_default(env, "USHnos", homenos / "ush")
        execnos = _path_or_default(env, "EXECnos", homenos / "exec")
        scriptsnos = _path_or_default(env, "SCRIPTSnos", homenos / "scripts")

        comout = Path(_require(env, "COMOUT"))
        comoutroot = _path_or_default(env, "COMOUTROOT", comout.parent)
        comin = _path_or_default(env, "COMIN", comout)
        dataroot = _path_or_default(env, "DATAROOT", Path("/lfs/h2/emc/stmp"))
        data = Path(_require(env, "DATA"))

        # NCO log/dbn knobs ------------------------------------------------
        pgmout = env.get("pgmout", "OUTPUT.$$")
        jlogfile = env.get("jlogfile", "")
        sendcom = env.get("SENDCOM", "YES")
        senddbn = env.get("SENDDBN", "NO")
        keepdata = env.get("KEEPDATA", "NO")

        return cls(
            ofs=ofs_value,
            pdy=pdy,
            cyc=cyc,
            cycle=cycle,
            net=net,
            run=run,
            homenos=homenos,
            fixofs=fixofs,
            parmnos=parmnos,
            ushnos=ushnos,
            execnos=execnos,
            scriptsnos=scriptsnos,
            comin=comin,
            comout=comout,
            comoutroot=comoutroot,
            dataroot=dataroot,
            data=data,
            pgmout=pgmout,
            jlogfile=jlogfile,
            sendcom=sendcom,
            senddbn=senddbn,
            keepdata=keepdata,
        )

    def as_shell_env(self) -> dict:
        """Re-serialize the dataclass as a flat ``dict[str, str]``.

        Suitable for passing to ``subprocess.run(env=...)``. Keys use the
        NCO casing the shell scripts expect (``HOMEnos``, ``cyc``, …).
        """
        return {
            "OFS": self.ofs,
            "PDY": self.pdy,
            "cyc": self.cyc,
            "cycle": self.cycle,
            "NET": self.net,
            "RUN": self.run,
            "HOMEnos": str(self.homenos),
            "FIXofs": str(self.fixofs),
            "PARMnos": str(self.parmnos),
            "USHnos": str(self.ushnos),
            "EXECnos": str(self.execnos),
            "SCRIPTSnos": str(self.scriptsnos),
            "COMIN": str(self.comin),
            "COMOUT": str(self.comout),
            "COMOUTROOT": str(self.comoutroot),
            "DATAROOT": str(self.dataroot),
            "DATA": str(self.data),
            "pgmout": self.pgmout,
            "jlogfile": self.jlogfile,
            "SENDCOM": self.sendcom,
            "SENDDBN": self.senddbn,
            "KEEPDATA": self.keepdata,
        }


__all__ = ["NCOEnv"]
