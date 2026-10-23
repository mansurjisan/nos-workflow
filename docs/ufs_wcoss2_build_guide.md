# Building the UFS-Coastal executables for nos-workflow on WCOSS2

Applies to WCOSS2 (Cactus or Dogwood). Update this guide in the same PR as any change to the build flags or the source tree.

## 1. What you build

nos-workflow runs coupled executables from the oceanmodeling `ufs-weather-model` fork. Build three of them, plus the tools.

| Executable | App | Flags (besides `-DAPP`) | Used by |
|---|---|---|---|
| `fv3_coastalS.exe` | `CSTLS` | `USE_ATMOS=ON NO_PARMETIS=ON OLDIO=ON BUILD_TOOLS=ON` | SECOFS (`secofs_ufs`): DATM + SCHISM |
| `fv3_coastalSW.exe` | `CSTLSW` | `USE_ATMOS=ON USE_WW3=ON PDLIB=ON NO_PARMETIS=ON OLDIO=ON BUILD_TOOLS=ON` | SECOFS with waves (`secofs_ufs_ww3`): DATM + SCHISM + WW3 |
| `fv3_stofs_3d_atl.exe` | `CSTLS` | `USE_ATMOS=ON NO_PARMETIS=ON OLDIO=ON BUILD_TOOLS=ON PREC_EVAP=ON` | STOFS-3D-ATL coupled (`stofs_3d_atl_ufs`) |

**Always build with `-DNO_PARMETIS=ON` on WCOSS2.** The ParMETIS library cannot be used there: a bug in it corrupts memory in SCHISM's mesh partitioning (`partition_hgrid`) at the rank counts these systems use (about 2900 and more), so runs crash or hang at random at startup. With `NO_PARMETIS=ON`, SCHISM skips ParMETIS and reads a precomputed `partition.prop` from `fix/<OFS>/` instead (section 6). Do not use the original issue 183 compile line as it is, because it has `-DNO_PARMETIS=OFF`. WW3 is not affected: its own decomposition uses SCOTCH.

Tools installed with them:

| File | Source |
|---|---|
| `schism_combine_hotstart7.exe` | `combine_hotstart7` from a CSTLS build tree, renamed |
| `combine_output11`, `combine_output11_MPI` | SCHISM utilities from a CSTLS build tree |
| `ww3_bound` (also `ww3_grid`, `ww3_ounp`, `ww3_strt`) | WW3 tools from the CSTLSW build tree (`BUILD_TOOLS=ON`), wave config only |

The standalone ATL executable is not a UFS build. It is the operational binary, copied from `/apps/prod/schism/5.14.0/bin/pschism_WCOSS2_VL` (see the STOFS-3D-ATL run guide).

All three are built from the same source tree. Keep `fv3_stofs_3d_atl.exe` separate from `fv3_coastalS.exe`: the ATL build adds `PREC_EVAP`.

## 2. Get the source

On WCOSS2, build from the maintainer's UFS source tree, `/lfs/h1/nos/estofs/noscrub/mansur.jisan/ufs-weather-model`. It is the oceanmodeling `ufs-weather-model` fork, branch `feature/coastal_app`, at commit `8e4a4742be00a67fe49aca43296e93a9b69c9964` (2026-07-28), with local patches that a fresh GitHub clone does not have. It is used for all three builds. Do not re-clone from GitHub, and do not build inside the maintainer's tree. If `ls` on the path fails, ask the maintainer for read access.

Do not use the other checkout, `/lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/ufs-weather-model`. It carries a local SCHISM change (an "ihot=1 tidal phase fix") that advances the tidal boundary phases by the hotstart time and shifts the tides. Section 6 has the check.

Copy the tree, keeping the submodules, the `.git` directories and the local edits. The old build trees and executables are left out, because you rebuild them. Set `DST` to your own noscrub area:
```bash
SRC=/lfs/h1/nos/estofs/noscrub/mansur.jisan/ufs-weather-model
DST=/lfs/h1/nos/estofs/noscrub/$LOGNAME/ufs-weather-model
mkdir -p $DST
rsync -a --exclude='tests/build_*' --exclude='tests/fv3_*.exe' $SRC/ $DST/
cd $DST
```
Do not run `git submodule update` or `git checkout` in the copy. Either one can overwrite the local patches.

### 2.1 Local patches

| Build | Patch | File |
|---|---|---|
| ATL | `schism_esmf_cap_wcoss2_local.patch` | `SCHISM-interface/SCHISM-ESMF/src/schism/schism_nuopc_cap.F90` |
| ATL | `cmeps_wcoss2_local.patch` | `CMEPS-interface/CMEPS/mediator/esmFldsExchange_coastal_mod.F90` |
| CSTLSW | CMEPS `wav2ocn_smapname`: reads the `wav2ocn_smapname` attribute | `CMEPS-interface/CMEPS/mediator/esmFldsExchange_coastal_mod.F90` |
| CSTLSW | WW3 currents hardening: guards the `W3SIN4` tail index and zeroes non-finite spectra at the PDLIB solver exit | `WW3/model/src/w3src4md.F90`, `WW3/model/src/w3profsmd_pdlib.F90` |
| CSTLSW | WW3 implicit reset fix: restores the per-step reset of the implicit solver's accumulation arrays | `WW3/model/src/w3wavemd.F90` |

The patches are already applied in the maintainer tree, so the copy has them. Confirm that the patched files show as modified in your copy:
```bash
cd $DST
git -C SCHISM-interface/SCHISM-ESMF diff --stat
git -C CMEPS-interface/CMEPS diff --stat
git -C WW3 diff --stat
grep -c "PDLIB scrub" WW3/model/src/w3profsmd_pdlib.F90      # 1 or more
```
Each `diff --stat` must list the files in the table above.


## 3. Modules

Run the three blocks in this order, in the shell you build from. This is the module sequence from the UFS Coastal WCOSS2 installation record (oceanmodeling/ufs-weather-model issue 183).
```bash
module purge
module reset

module load PrgEnv-intel/8.1.0
module load intel/19.1.3.304
module load craype/2.7.13
module load cray-mpich/8.1.12
module load cmake/3.20.2
module load zlib/1.2.11
module load jasper/2.0.25
module load libpng/1.6.37
module load zstd/1.5.0

# HDF5/NetCDF stack
module load hdf5-D/1.14.0
module load netcdf-D/4.9.2
module load pnetcdf-D/1.12.2
module load pio-D/2.5.10

# ESMF/FMS specific modules
module load esmf-D/8.8.0
module load fms-D/2024.01
module load gftl-shared/1.6.1
module load mapl-D/2.53.0

# NCO/NCEP libraries
module load bacio/2.4.1
module load w3emc/2.12.0
module load g2/3.5.1
module load g2tmpl/1.13.0
module load ip/4.0.0
module load sp/2.3.3
module load crtm/2.4.0

# SCHISM specific
module load scotch/7.0.4
```
If `compile.sh` fails on module errors, start a new shell and load the modules again, in this order.

## 4. Build

`compile.sh` takes: machine, CMake flags, build name, compiler, clean-before, clean-after. It writes the executable to `tests/fv3_<name>.exe` and uses `tests/build_fv3_<name>` as the build tree. With `NO` as the last argument the build tree is kept. Keep it for the CMakeCache check and for the SCHISM tools.

Run the builds one after the other from the same copy, in a login shell or a short batch job.

### 4.1 CSTLS: fv3_coastalS.exe (SECOFS)

```bash
cd $DST/tests
./compile.sh wcoss2 "-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_TOOLS=ON" coastalS intel YES NO
```
This is the issue 183 compile line with `NO_PARMETIS=ON` (section 1: ParMETIS cannot be used on WCOSS2). A `NO_PARMETIS` build reads a precomputed `partition.prop` (section 6).

Check:
```bash
ls -l fv3_coastalS.exe
grep -E "^APP|USE_ATMOS|NO_PARMETIS|OLDIO|BUILD_TOOLS" build_fv3_coastalS/CMakeCache.txt
```
Expect `APP:STRING=CSTLS` and the four options `ON`.

### 4.2 CSTLSW: fv3_coastalSW.exe (SECOFS + WW3)

The three wave patches (section 2.1: one CMEPS, two WW3) must be present.
```bash
cd $DST/tests
./compile.sh wcoss2 "-DAPP=CSTLSW -DUSE_ATMOS=ON -DUSE_WW3=ON -DPDLIB=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_TOOLS=ON" coastalSW intel YES NO
```
`BUILD_TOOLS=ON` makes this one build also produce the WW3 tools (`ww3_grid`, `ww3_bound`, `ww3_ounp`, `ww3_strt`), so the tools and the coupled executable share one switch configuration.
`USE_WW3` is required. Without it the `RADFLAG` parameters in the SCHISM param.nml are ignored and there is no wave radiation stress in SCHISM. `PDLIB` selects the WW3 switch `meshcap_pdlib`. WW3 decomposes with SCOTCH (module `scotch/7.0.4`), so `NO_PARMETIS` does not affect it.

Check:
```bash
ls -l fv3_coastalSW.exe
grep -E "^APP|USE_WW3|PDLIB|NO_PARMETIS|OLDIO|BUILD_TOOLS" build_fv3_coastalSW/CMakeCache.txt
strings fv3_coastalSW.exe | grep -c "PDLIB scrub"      # 1 or more: WW3 hardening is in
find build_fv3_coastalSW -name 'ww3_*' -type f -perm -111
```

### 4.3 ATL coupled: fv3_stofs_3d_atl.exe

The ATL patches (section 2.1) must be present.
```bash
cd $DST/tests
./compile.sh wcoss2 "-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_TOOLS=ON -DPREC_EVAP=ON" stofs_atl_pe intel YES NO
grep -E "PREC_EVAP|NO_PARMETIS|OLDIO|USE_ATMOS|^APP" build_fv3_stofs_atl_pe/CMakeCache.txt
```
Expect all four options `ON` and `APP=CSTLS`.

`PREC_EVAP` matters. Without it SCHISM ignores precipitation, and the operational river sinks (1,986,300) drain the domain.

## 5. Install into nos-workflow exec/

Set `EXE` to the `exec/` directory of your nos-workflow clone. Use `cp -p`.
```bash
EXE=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/exec
mkdir -p $EXE
cp -p $DST/tests/fv3_coastalS.exe $EXE/fv3_coastalS.exe
cp -p $DST/tests/fv3_coastalSW.exe $EXE/fv3_coastalSW.exe
cp -p $DST/tests/fv3_stofs_atl_pe.exe $EXE/fv3_stofs_3d_atl.exe
```
SCHISM tools, from the CSTLS build tree:
```bash
B=$DST/tests/build_fv3_coastalS
find $B -name 'combine_*' -type f -perm -111
cp -p <path to combine_hotstart7> $EXE/schism_combine_hotstart7.exe
cp -p <path to combine_output11> $EXE/combine_output11
cp -p <path to combine_output11_MPI> $EXE/combine_output11_MPI
```
Use the paths that `find` prints.

WW3 tool for the wave config, from the CSTLSW build tree (use the path the `find` in section 4.2 prints):
```bash
cp -p <path to ww3_bound> $EXE/ww3_bound
```

If you use a shared `exec/`, do not overwrite a binary a running cycle uses. Copy under a new name and switch after the cycle.

## 6. Check

Libraries resolve:
```bash
for f in fv3_coastalS.exe fv3_coastalSW.exe fv3_stofs_3d_atl.exe \
         schism_combine_hotstart7.exe combine_output11_MPI; do
  echo "== $f"; ldd $EXE/$f | grep "not found"
done
```
Nothing may print under a name. Run it with the modules of section 3 loaded.

Build flags: the CMakeCache greps in section 4. A build without the right flag runs, then fails or gives wrong results at run time.

`partition.prop`: every `NO_PARMETIS` build needs the matching file in `fix/<OFS>/`, with the rank count of the run.

| System | File | Ranks |
|---|---|---|
| SECOFS | `fix/secofs_ufs/secofs_ufs.partition.prop` | 2794 |
| STOFS-3D-ATL | `fix/stofs_3d_atl_ufs/...partition.prop` | 4912 (the operational file) |

The ATL file is one of the operational fix files that `tools/fetch_stofs_3d_atl_fix.sh` fetches; the script checks that it has 4912 ranks. In UFS mode a missing `partition.prop` is skipped silently at staging. The run then aborts at SCHISM startup. Look for `Staged partition.prop` in the prep or nowcast log.

Tidal phase: no executable may carry the local "tidal phase fix" (section 2):
```bash
for f in fv3_coastalS.exe fv3_coastalSW.exe fv3_stofs_3d_atl.exe; do
  echo "$f $(strings $EXE/$f | grep -c 'tidal phase fix')"     # each must be 0
done
```

## 7. Troubleshooting

| Symptom | Cause and action |
|---|---|
| ParMETIS crash or hang at startup (`partition_hgrid`, about 2900 ranks) | The build uses ParMETIS. Rebuild with `-DNO_PARMETIS=ON` and stage `partition.prop`. |
| Run aborts at SCHISM startup, no ParMETIS | `NO_PARMETIS` build and no `partition.prop` in `fix`. Stage it with the right rank count. |
| ATL domain drains or the water level falls | `fv3_stofs_3d_atl.exe` built without `PREC_EVAP`. Check CMakeCache and rebuild. |
| SECOFS boundary tide shifted by the restart time | Built from the `packages/ufs-weather-model` checkout, which carries the "ihot=1 tidal phase fix". Rebuild from the maintainer tree of section 2. |
| `RADFLAG` ignored, no wave effect in SCHISM | Executable built without `USE_WW3`. |
| Wave run crashes with currents on (SIGSEGV in `W3SIN4`) | WW3 hardening patch missing. `strings fv3_coastalSW.exe` must show `PDLIB scrub`. |
| Wave field weak, local wind sea missing | WW3 implicit reset patch missing (`w3wavemd.F90`). Check `git -C WW3 diff --stat` and rebuild. |
| Wave run aborts in ESMF `MeshDual` | CMEPS `wav2ocn_smapname` patch missing, so the regrid does not use the weights file. |
| Wave prep: `ww3_bound` not found | Install `exec/ww3_bound` (section 5). |
| `combine_output11_MPI` SIGSEGV | Needs `ulimit -s unlimited` and an exclusive node. The coupled cards set both. The coupled post log shows "no field stacks staged" and there is no `station.profile` without it. |
| CMake cannot find SCOTCH (wave build) | `scotch/7.0.4` not loaded. Load the modules of section 3 again. |
| `ldd` shows `not found` | Modules not loaded in the shell. Load section 3 and check again. |
