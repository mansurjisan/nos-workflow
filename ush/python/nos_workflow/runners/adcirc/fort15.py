"""fort.15 (and fort.rotm) writer for ADCIRC.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), models/adcirc/adcirc.py generate_fort15. Same text
for the same inputs; the tidal table comes from nos_utils.forcing.adcirc_tides
instead of his TideFac, the mesh summary from runners.adcirc.mesh, and the
unused SWAN/river-flux/OWI-wave branches are dropped.
"""
from __future__ import annotations

import math
import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, TextIO, Tuple

from .mesh import MeshInfo
from .physics import AdcircConfiguration

_NWS_BASE: Dict[int, Tuple[int, int]] = {0: (1, 0), 14: (1, 3)}


@dataclass
class Fort15Spec:
    """Inputs for one fort.15, mirroring the arguments of Zach's Adcirc class."""

    name: str
    mesh_name: str
    coldstart_time: datetime
    start_time: datetime
    end_time: datetime
    dt: float
    physics: Mapping[str, Any]
    attributes: List[str]
    mesh: MeshInfo
    tides: Mapping[str, Any]
    tide_constituents: List[str]
    hotstart_unit: int
    nws: int
    ice: bool
    ramp: float = 5.0
    output_minutes: float = 20.0
    wind_dt: int = 3600
    flux_settling: float = 0.0
    station_file: Optional[str] = None
    projection_center: Optional[Tuple[float, float]] = None
    output_options: Dict[str, bool] = field(default_factory=dict)


class Fort15Writer:
    def __init__(self, spec: Fort15Spec) -> None:
        if spec.nws not in _NWS_BASE:
            raise ValueError(f"Unsupported NWS value: {spec.nws}")
        self.s = spec
        self.phys = AdcircConfiguration(dict(spec.physics), spec.dt)
        for key, value in spec.output_options.items():
            self.phys.set_output_option(key, value)
        self.sim_length = (spec.end_time - spec.coldstart_time).total_seconds() / 86400.0

    def _slam0_sfea0(self) -> Tuple[float, float]:
        if self.s.projection_center is not None:
            return self.s.projection_center[0], self.s.projection_center[1]
        return self.s.mesh.mean_lon, self.s.mesh.mean_lat

    def write(self, output) -> None:
        output = Path(output)
        with open(output, "w") as f:
            self._header(f)
            self._hotstart(f)
            self._coordinate_system(f, output)
            self._solver(f)
            nodal_att, tau0 = self._nodal_attributes(f)
            f.write(" 1                     ! NCOR\n")
            f.write(" 2                     ! NTIP\n" if self.phys.use_self_attraction_and_loading()
                    else " 1                     ! NTIP\n")
            self._nws(f)
            self._ramp1(f)
            f.write("9.81                   ! G\n")
            f.write(f"{tau0:0.6f}                ! TAU0\n")
            f.write(f"{self.s.dt:0.3f}                   ! DT\n")
            f.write("0.00                   ! STATIM\n")
            f.write("0.00                   ! REFTIM\n")
            self._wtiminc(f)
            f.write(f"{self.sim_length:0.4f}           ! RNDAY\n")
            self._ramp2(f)
            a00, b00, c00 = self.phys.time_weighting_coefficients()
            f.write(f"{a00:0.2f} {b00:0.2f} {c00:0.2f}    ! A00 B00 C00\n")
            f.write(f"{self.phys.h0():0.3f} 0 0 {self.phys.velmin():0.3f}         ! H0\n")
            lon0, lat0 = self._slam0_sfea0()
            f.write(f"{lon0:0.2f} {lat0:0.2f}         ! SLAM0 SFEA0\n")
            self._friction(f, nodal_att)
            self._turbulence(f)
            f.write("0.0                   ! CORI\n")
            self._tides(f)
            f.write("110.0        ! ANGINN\n")
            if self.s.mesh.n_rivers > 0:
                f.write("-1           ! NFFR\n")
            self._stations(f)
            self._global_output(f)
            f.write(f"5 {int((self.sim_length * 86400.0) / self.s.dt):d} ! NHSTAR\n")
            f.write("1 0 1.e-7 35 0 ! ITITER\n")
            self._netcdf_metadata(f)
            self._namelists(f)

    def _header(self, f: TextIO) -> None:
        f.write(self.s.name + "_" + self.s.mesh_name + "\n")
        f.write("nos-stofs-workflow\n")
        f.write("1 20.0 1 50 1000.0  ! NFOVER\n")
        f.write("0                   ! NABOUT\n")
        f.write(f"{math.floor(3600.0 / self.s.dt):d}                 ! NSCREEN\n")

    def _hotstart(self, f: TextIO) -> None:
        if self.s.coldstart_time == self.s.start_time:
            f.write("0                   ! IHOT\n")
        elif self.s.hotstart_unit in (67, 567):
            f.write("567                 ! IHOT\n")
        else:
            f.write("568                 ! IHOT\n")

    def _coordinate_system(self, f: TextIO, output: Path) -> None:
        if self.phys.coordinate_rotation():
            f.write(f"{-self.phys.coordinate_system():d}                   ! ICS\n")
            write_rotm(output.parent / "fort.rotm", self.phys)
        else:
            f.write(f"{self.phys.coordinate_system():d}                   ! ICS\n")

    def _solver(self, f: TextIO) -> None:
        if self.phys.solver() == "implicit":
            d6 = "3" if self.phys.implicit_gravity_wave() else "1"
        else:
            d6 = "2 "
        d1 = "5" if self.phys.turbulence_model() == "smagorinsky" else "1"
        im = d1 + "1111" + d6
        if im == "111111":
            im = "0"
        f.write(im + " ! IM \n")
        f.write("1                  ! NOLIBF\n")
        f.write("2                  ! NOLIFA\n")
        if self.phys.advection():
            f.write("1                  ! NOLICA\n")
            f.write("1                  ! NOLICAT\n")
        else:
            f.write("0                  ! NOLICA\n")
            f.write("0                  ! NOLICAT\n")

    def _nodal_attributes(self, f: TextIO) -> Tuple[List[str], float]:
        nodal_att = list(self.s.attributes)
        if self.phys.turbulence_model() == "smagorinsky":
            evis = "average_horizontal_eddy_viscosity_in_sea_water_wrt_depth"
            if evis in nodal_att:
                nodal_att.remove(evis)
        if "primitive_weighting_in_continuity_equation" not in nodal_att:
            tau0 = self.phys.tau0()
        else:
            tau0 = -3.0
        for drop in ("surface_directional_effective_roughness_length",
                     "surface_canopy_coefficient"):
            if drop in nodal_att:
                nodal_att.remove(drop)
        f.write(f"{len(nodal_att):d}       ! NWP\n")
        for a in nodal_att:
            f.write(a + "\n")
        return nodal_att, tau0

    def _ramp1(self, f: TextIO) -> None:
        if self.s.mesh.n_type52 > 0:
            f.write("2                      ! NRAMP\n")
        else:
            f.write("1                      ! NRAMP\n")

    def _ramp2(self, f: TextIO) -> None:
        if self.s.mesh.n_type52 > 0:
            total = self.s.ramp + self.s.flux_settling
            f.write(f"{total:0.2f} 4.0 {self.s.flux_settling:0.2f}            ! DRAMP\n")
        else:
            f.write(f"{self.s.ramp:0.2f}                        ! DRAMP\n")

    def _nws_value(self) -> int:
        sign, _ = _NWS_BASE[self.s.nws]
        ncice = self.s.nws if self.s.ice else 0
        return sign * (ncice * 1000 + abs(self.s.nws))

    def _nws(self, f: TextIO) -> None:
        f.write(f"{self._nws_value():<27d}! NWS\n")

    def _wtiminc(self, f: TextIO) -> None:
        if self.s.nws != 14:
            return
        parts = [str(int(self.s.wind_dt))]
        comments = ["WTIMINC"]
        if self.s.ice:
            parts.append(str(int(self.s.wind_dt)))
            comments.append("CICE_TIMINC")
        f.write(f"{' '.join(parts):<27s}! {' '.join(comments)}\n")

    def _friction(self, f: TextIO, nodal_att: List[str]) -> None:
        if "mannings_n_at_sea_floor" not in nodal_att:
            value, note = self.phys.quadratic_friction_coefficient(), "CF"
        else:
            value, note = self.phys.bottom_friction_limit(), "FFACTOR"
        f.write(f"{value:0.5f} {self.phys.hbreak():0.5f} {self.phys.ftheta():0.5f} "
                f"{self.phys.fgamma():0.5f} ! {note:s}\n")

    def _turbulence(self, f: TextIO) -> None:
        if self.phys.turbulence_model() == "smagorinsky":
            f.write(f"{-self.phys.smagorinsky_coefficient():0.4f}           ! ESL\n")
        else:
            f.write(f"{self.phys.eddy_viscosity_coefficient():0.4f}               ! ESL\n")

    def _tides(self, f: TextIO) -> None:
        names = self.s.tide_constituents
        if self.phys.use_full_tide_potential() and not self.phys.use_self_attraction_and_loading():
            f.write("0 ! NTIF - Using analytical solution\n")
        else:
            f.write(f"{len(names):d}                     "
                    f"! NTIF - Simulation start: {self.s.coldstart_time.isoformat():s}, "
                    f"duration: {self.sim_length:0.2f}\n")
            for name in names:
                f.write("\n".join(self.s.tides[name].potential_lines()) + "\n")
        f.write("0      ! NBFR\n")

    def _stations(self, f: TextIO) -> None:
        if self.s.station_file:
            stations = read_station_file(self.s.station_file)
            self._station_block(f, stations, "NOUTE")
            self._station_block(f, stations, "NOUTV")
            if self.s.nws != 0:
                self._station_block(f, stations, "NOUTW")
        else:
            f.write("0 0.0 0.0 0   !NOUTE\n")
            f.write("0\n")
            f.write("0 0.0 0.0 0   !NOUTV\n")
            f.write("0\n")
            if self.s.nws != 0:
                f.write("0 0.0 0.0 0   !NOUTW\n")
                f.write("0\n")

    def _station_block(self, f: TextIO, stations: list, ident: str) -> None:
        f.write(f"-5 0.0 {self.sim_length:0.2f} {self._output_steps():d}   ! {ident:s}\n")
        f.write(f"{len(stations):d} ! Number of stations\n")
        for st in stations:
            f.write(f"{st[0]:0.6f} {st[1]:0.6f} ! {st[2]:s} \n")

    def _output_steps(self) -> int:
        return int(self.s.output_minutes * 60.0 / self.s.dt)

    def _global_output(self, f: TextIO) -> None:
        n = self._output_steps()
        f.write(f"-5 0.0 {self.sim_length:0.2f} {n:d} !NOUTGE\n")
        noutgv = -5 if self.phys.output_option("velocity") else 0
        f.write(f"{noutgv:d} 0.0 {self.sim_length:0.2f} {n:d} !NOUTGV\n")
        if self.s.nws != 0:
            noutgw = -5 if self.phys.output_option("meteorology") else 0
            f.write(f"{noutgw:d} 0.0 {self.sim_length:0.2f} {n:d} !NOUTGW\n")
        f.write("0 ! NHARFR\n")
        f.write("40.0 50.0 5 0.0 ! THAS\n")
        f.write("1 1 1 1 ! NHASE\n")

    def _netcdf_metadata(self, f: TextIO) -> None:
        f.write(self.s.name + "\n")
        f.write("The Water Institute\n")
        f.write("padcirc\n")
        f.write("netCDF\n")
        f.write("one\n")
        f.write("no_comments\n")
        f.write(socket.gethostname() + "\n")
        f.write("CF3\n")
        f.write("zcobell@thewaterinstitute.org\n")
        f.write(self.s.coldstart_time.strftime("%Y-%m-%d %H:%M:%S\n"))

    def _namelists(self, f: TextIO) -> None:
        if self.s.nws != 0:
            f.write(self._swan_output_line() + "\n")
            f.write(f"&MetControl DragLawString='{self.phys.wind_drag_formula():s}'"
                    f" WindDragLimit='{self.phys.wind_drag_limit():0.5f}' "
                    "invertedBarometerOnElevationBoundary=.true. /\n")
        f.write("&wetDryControl slim=")
        slim = (self.phys.slope_limiter_value() if self.phys.slope_limiter_active()
                else 1000000000.0)
        f.write(f"{slim:0.6f} ")
        f.write("windlim=.true. " if self.phys.wind_limiter_active() else "windlim=.false. ")
        f.write("directvelWD=.true. " if self.phys.use_direct_velmin_calculation()
                else "directvelWD=.false. ")
        f.write("useHF=.true. " if self.phys.use_hf_calculation() else "useHF=.false. ")
        if self.phys.station_partial_wet_fix_active():
            f.write("StatPartWetFix=.true. ")
            f.write(f"How2FixStatPartWet = {self.phys.station_partial_wet_fix_option():d}")
        else:
            f.write("StatPartWetFix=.false. ")
        f.write("/\n")
        inundation = ".true." if self.phys.output_option("inundation") else ".false."
        f.write(f"&inundationOutputControl inundationOutput={inundation} /\n")
        if self.phys.use_full_tide_potential():
            f.write(
                "&TidalPotentialControl\n"
                "   UseFullTIPFormula=.true.,\n"
                "   TIPOrder=4,\n"
                "   TIPStartDate='{:s}',\n"
                "   MoonSunPositionComputeMethod='JM',\n"
                "   MoonSunCoordFile='none',\n"
                "   IncludeNutation=.true.,\n"
                "   k2Value=0.302,\n"
                "   h2Value=0.609 / \n".format(
                    self.s.coldstart_time.strftime("%Y-%m-%d %H:%M:%S")))
        vew = ".true." if self.phys.use_vew1d_wet_perimeter() else ".false."
        f.write(f"&VEW1DChannelControl activateVEW1DChannelWetPerimeter={vew} /\n")

    def _swan_output_line(self) -> str:
        t, fl = ".true.", ".false."
        hs = t if self.phys.output_option("wave_height") else fl
        tps = t if self.phys.output_option("wave_peak_period") else fl
        mean = t if self.phys.output_option("wave_mean_period") else fl
        dirn = t if self.phys.output_option("wave_direction") else fl
        return (f"&SWANOutputControl SWAN_OutputTPS={tps:s}, "
                f"SWAN_OutputTMM10={mean:s}, SWAN_OutputTM01={mean:s}, "
                f"SWAN_OutputHS={hs:s}, SWAN_OutputTM02={mean:s} "
                f"SWAN_OutputDIR={dirn:s} /")


def write_rotm(path, phys: AdcircConfiguration) -> None:
    with open(path, "w") as f:
        f.write("znorth_in_spherical_coors\n")
        f.write(f"{phys.coordinate_rotation_x():0.5f} "
                f"{phys.coordinate_rotation_y():0.5f} ! Spherical coordinate rotation \n")


def read_station_file(path) -> list:
    stations: list = []
    with open(path) as f:
        for line in f:
            clean = line.strip()
            if "!" in clean:
                end = clean.find("!") - 1
                coords, name = clean[0:end], clean[end + 2:]
            else:
                coords, name = clean, f"station_{len(stations):d}"
            parts = coords.split(",") if "," in coords else coords.split()
            stations.append([float(parts[0]), float(parts[1]), name])
    if not stations:
        raise ValueError("No stations found in file")
    return stations


def write_fort15(spec: Fort15Spec, output) -> None:
    Fort15Writer(spec).write(output)
