help([[
loads UFS-Coastal Model prerequisites on Hercules (MSU RDHPCS)

Runtime libraries for fv3_coastalS.exe (DATM+SCHISM via oceanmodeling/
ufs-weather-model, branch feature/coastal_app, APP=CSTLS), plus the
external binaries and Python stack nos-workflow/nos-utils need for prep.

Versions below mirror modulefiles/ufs_hercules.intel.lua and
modulefiles/ufs_common.lua from the ufs-coastal fork itself (spack-stack
spack-stack-1.9.2, env ue-oneapi-2024.1.0) -- the same libraries the exe
was built against. If the exe was rebuilt against a different spack-stack
env, update this file and run.hercules.ver together.
]])

-- spack-stack unified env (compiler + MPI + science libraries)
spack_stack_ver=os.getenv("spack_stack_ver") or "1.9.2"
spack_stack_env=os.getenv("spack_stack_env") or "ue-oneapi-2024.1.0"
spack_stack_root=os.getenv("spack_stack_root") or "/apps/contrib/spack-stack"
local stack_base = pathJoin(spack_stack_root, "spack-stack-" .. spack_stack_ver, "envs", spack_stack_env, "install")

prepend_path("MODULEPATH", pathJoin(stack_base, "modulefiles/Core"))

stack_intel_ver=os.getenv("stack_intel_ver") or "2024.2.1"
load(pathJoin("stack-oneapi", stack_intel_ver))

stack_impi_ver=os.getenv("stack_impi_ver") or "2021.13"
-- The MPI module lives under a compiler/MPI-specific Core subtree. This
-- second, unconditional MODULEPATH prepend mirrors upstream
-- ufs_hercules.intel.lua, which also prepends both Core paths statically
-- up front rather than gating the second one on stack-oneapi being loaded.
prepend_path("MODULEPATH", pathJoin(stack_base, "modulefiles/intel-oneapi-mpi", stack_impi_ver .. "-sqiixt7/gcc/13.3.0"))
load(pathJoin("stack-intel-oneapi-mpi", stack_impi_ver))

-- Libraries fv3_coastalS.exe is linked against (must match the build env).
local ufs_modules = {
  {["jasper"]          = "2.0.32"},
  {["libpng"]          = "1.6.37"},
  {["hdf5"]            = "1.14.3"},
  {["netcdf-c"]        = "4.9.2"},
  {["netcdf-fortran"]  = "4.6.1"},
  {["parallelio"]      = "2.6.2"},
  {["esmf"]            = "8.8.0"},
  {["fms"]             = "2024.02"},
  {["bacio"]           = "2.4.1"},
  {["crtm"]            = "2.4.0.1"},
  {["g2"]              = "3.5.1"},
  {["g2tmpl"]          = "1.13.0"},
  {["ip"]              = "5.1.0"},
  {["sp"]              = "2.5.0"},
  {["w3emc"]           = "2.10.0"},
  {["gftl-shared"]     = "1.9.0"},
  {["mapl"]            = "2.53.4-esmf-8.8.0"},
  {["scotch"]          = "7.0.4"},
  {["zlib"]            = "1.2.13"},
}

for i = 1, #ufs_modules do
  for name, default_version in pairs(ufs_modules[i]) do
    local env_version_name = string.gsub(name, "-", "_") .. "_ver"
    load(pathJoin(name, os.getenv(env_version_name) or default_version))
  end
end

-- Prep-stage external binaries. NEEDS-ON-MACHINE: this wgrib2 build's
-- IPOLATES support is unverified on Hercules -- nos_utils.io.grib_extract
-- needs IPOLATES for -new_grid regridding of HRRR's Lambert Conformal grid,
-- and without it that regrid step fails at prep time, not here.
nco_ver=os.getenv("nco_ver") or "5.2.4"
load(pathJoin("nco", nco_ver))

wgrib2_ver=os.getenv("wgrib2_ver") or "3.6.0"
load(pathJoin("wgrib2", wgrib2_ver))

-- Python: nos-utils/nos_workflow runtime deps. numpy/netCDF4/pyyaml/pandas/
-- xarray are confirmed spack-stack packages in this env; py-scipy is NOT
-- confirmed to exist in this spack-stack env, so it is a soft try_load
-- below, not a hard load that would abort module load if missing.
stack_python_ver=os.getenv("stack_python_ver") or "3.11.7"
load(pathJoin("stack-python", stack_python_ver))

py_numpy_ver=os.getenv("py_numpy_ver") or "1.23.4"
load(pathJoin("py-numpy", py_numpy_ver))

py_netcdf4_ver=os.getenv("py_netcdf4_ver") or "1.7.1.post2"
load(pathJoin("py-netcdf4", py_netcdf4_ver))

py_pyyaml_ver=os.getenv("py_pyyaml_ver") or "6.0.2"
load(pathJoin("py-pyyaml", py_pyyaml_ver))

py_pandas_ver=os.getenv("py_pandas_ver") or "2.2.3"
load(pathJoin("py-pandas", py_pandas_ver))

py_xarray_ver=os.getenv("py_xarray_ver") or "2024.7.0"
load(pathJoin("py-xarray", py_xarray_ver))

-- UNVERIFIED: py-scipy was absent from every Hercules module list found
-- during research. nos_utils forcing/interp modules import scipy
-- unconditionally, so if this try_load is a no-op on your Hercules (module
-- not found), prep will fail with an ImportError, not here.
py_scipy_ver=os.getenv("py_scipy_ver") or "1.11.3"
try_load(pathJoin("py-scipy", py_scipy_ver))

setenv("CC", "mpiicc")
setenv("CXX", "mpiicpc")
setenv("FC", "mpiifort")
setenv("CMAKE_Platform", "hercules.intel")

whatis("Description: UFS-Coastal (DATM+SCHISM) runtime environment for Hercules")
