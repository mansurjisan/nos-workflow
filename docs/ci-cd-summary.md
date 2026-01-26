# NOS-Workflow CI/CD Pipeline Summary

## What We Built

### 1. GitHub Actions Pipeline
**File:** `.github/workflows/build-singularity.yml`

- Automated Singularity container builds on push to main
- Weekly scheduled builds (Sunday 2 AM UTC)
- Publishes to:
  - **GitHub Releases** - downloadable .sif files
  - **Sylabs Cloud** - `library://mjisan/nos-workflow/nos-workflow:latest`
- Runs container tests (ADCIRC, SCHISM, ecFlow, Python packages)

### 2. Jenkins Pipeline
**File:** `Jenkinsfile.parallelworks`

- Runs on NOAA ParallelWorks HPC
- Poll SCM trigger (every 5 minutes)
- Builds container with `--fakeroot`
- Integration tests with real data paths
- Archives containers to `/lustre/mjisan/containers/`

### 3. Singularity Container
**File:** `containers/nos-workflow.def`

- Converts Docker workflow to Singularity/Apptainer
- Includes: ADCIRC, SCHISM, ecFlow, SLURM, wgrib2, NCEP libraries
- STOFS workflow CLI (`stofs prep-forecast`, etc.)

---

## Key Challenges Solved

| Issue | Solution |
|-------|----------|
| ecFlow build race condition | Changed to `-j1` (single-threaded) |
| wgrib2 TAR ownership errors | `export TAR_OPTIONS="--no-same-owner"` |
| Sylabs Cloud auth failures | Fixed remote setup, `-U` flag for unsigned |
| Wrong Sylabs username | Changed `mansurjisan` → `mjisan` |
| Git clone fails in container | Use `%setup` section to copy files |
| `/tmp` cleared during build | Changed to `/opt/nos-workflow-repo` |
| Build directory conflicts | Use `rm -rf` + `mkdir -p` + absolute paths |

---

## Container Distribution

| Platform | Location |
|----------|----------|
| Sylabs Cloud | `library://mjisan/nos-workflow/nos-workflow:latest` |
| Docker Hub | `mjisan/stofsworkflow:nightly` |
| GitHub Releases | https://github.com/mansurjisan/nos-workflow/releases/latest |

---

## Files Created/Modified

```
nos-workflow/
├── .github/workflows/
│   └── build-singularity.yml    # GitHub Actions workflow
├── containers/
│   └── nos-workflow.def         # Singularity definition
├── Jenkinsfile.parallelworks    # Jenkins pipeline for HPC
├── docs/
│   └── hercules-deployment-guide.md
└── README.md                    # Updated with CI/CD badges
```

---

## Result

Fully automated CI/CD pipeline that:

1. Builds Singularity containers on every push
2. Tests on HPC infrastructure (ParallelWorks)
3. Publishes to multiple registries
4. Enables one-command deployment:

```bash
singularity pull library://mjisan/nos-workflow/nos-workflow:latest
```
