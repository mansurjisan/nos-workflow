"""STOFS-2D-GLO prep helper shared by the ops steps: link the fix mesh files into a run directory. MJ (10/19/26)"""
from __future__ import annotations

from pathlib import Path

from .settings import AdcircConfigError, CycleContext


def link_mesh_files(ctx: CycleContext, run_dir: Path, extra=()) -> None:
    """Link the fix files as fort.14 / fort.13; adcprep only accepts those exact names."""
    s = ctx.settings
    for src_name, dst_name in ((s.grid_file, "fort.14"), (s.attr_file, "fort.13"), *extra):
        src = ctx.fixofs / src_name
        if not src.is_file():
            raise AdcircConfigError(f"missing fix file {src} (tools/fetch_stofs_2d_glo_fix.sh)")
        dst = run_dir / dst_name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src.resolve())
