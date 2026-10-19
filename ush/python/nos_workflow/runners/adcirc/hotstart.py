"""Reads the model time of an ADCIRC restart file (the one hotstart helper the ops chain uses). MJ (10/18/26)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


def file_time(path: Path) -> Optional[float]:
    import netCDF4

    ds = netCDF4.Dataset(path, "r")
    try:
        var = ds.variables["time"]
        if var.size == 0:
            log.warning("%s: time dimension is empty, skipping", path.name)
            return None
        data = var[:]
        fill = getattr(var, "_FillValue", None)
        # netCDF4 returns a masked element for a fill value. MJ (10/05/26)
        if np.ma.is_masked(data.flat[0]) or (fill is not None and data.flat[0] == fill):
            log.warning("%s: time contains fill value, skipping", path.name)
            return None
        return float(data.flat[0])
    finally:
        ds.close()
