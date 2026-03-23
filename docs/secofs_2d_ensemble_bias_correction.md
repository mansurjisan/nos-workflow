# SECOFS 2D Barotropic Ensemble with Bias Correction

## Motivation

The 3D operational SECOFS (Southeast Coastal Ocean Forecast System) produces high-quality water level forecasts using a 63-level SCHISM model with full baroclinic physics. However, running an ensemble of 3D models is prohibitively expensive on HPC — a single deterministic run requires ~1080 MPI tasks on 10 nodes.

A 2D barotropic version of the same grid (3 vertical levels, no density physics) runs significantly faster, making it feasible to produce ensemble forecasts with 7-15 members at a fraction of the cost. The challenge: the 2D model lacks baroclinic effects (density-driven currents, Gulf Stream transport, steric sea level) that contribute ~0.5-1.2 m of mean sea level at many stations.

The solution: run one expensive 3D deterministic forecast and multiple cheap 2D ensemble members, then combine them using an anomaly-based bias correction that anchors the ensemble to the 3D physics.

## The Problem: Why 2D Differs from 3D

### Boundary Condition Fix (Primary)

The original 2D configuration used `iettype=5, ifltype=3` at the ocean boundary — imposing subtidal sea surface height from RTOFS without matching subtidal transport. This created a mass imbalance that drained the domain by ~1 m over 2 days.

**Fix**: Both elevation and velocity boundary types set to `3` (tidal only), producing dynamically consistent `3 3 0 0` boundaries. This eliminated the domain-wide drawdown.

### Missing Baroclinic Physics (Residual)

After the boundary fix, residual differences remain:

| Region | Mean Bias | De-meaned RMSE | Cause |
|--------|-----------|----------------|-------|
| South Florida / Keys | -1.2 m | 0.14 m | Missing Gulf Stream / steric setup |
| West Florida shelf | -1.0 m | 0.30 m | Missing density currents + over-energetic tides |
| Chesapeake / Mid-Atlantic | -0.4 m | 0.15 m | Smaller baroclinic contribution |

The mean bias cannot be fixed by friction tuning — it reflects physics the 2D model fundamentally cannot produce. Regional friction tuning (increasing roughness on the West Florida shelf) reduced tidal amplitude overshoot but slightly degraded correlation.

### Key Finding: V2 Baseline Has Best Correlations

Testing showed that the untuned V2 baseline (3 3 0 0 boundaries, original roughness) produces the highest correlations with the 3D model (domain median r = 0.88). Friction tuning improved amplitude match but degraded phase/shape. This means the 2D model captures the right variability pattern — it just needs mean and amplitude correction.

## Solution: Anomaly-Based Ensemble Bias Correction

### Core Equation

For each ensemble member at each station:

```
WL_final(t) = WL_3d_det(t) + a_i * (WL_2d_member(t) - WL_2d_control(t))
```

Where:
- `WL_3d_det(t)` — 3D deterministic water level (carries full baroclinic physics)
- `WL_2d_member(t)` — 2D ensemble member water level (perturbed atmospheric forcing)
- `WL_2d_control(t)` — 2D control member (same forcing as 3D deterministic)
- `a_i` — per-station amplitude scaling factor

### Why This Works

The 3D deterministic run provides the **baseline physics**: mean sea level, density-driven circulation, Gulf Stream effects, steric height. The 2D ensemble contributes only the **perturbation anomaly** — how each different weather scenario changes water levels relative to the control. The anomaly is scaled by `a_i` to match the 3D model's amplitude response.

Properties:
- **Fixes mean bias**: The baseline is the 3D solution, not the 2D
- **Fixes amplitude bias**: `a_i` scales 2D anomalies to match 3D variability
- **Preserves timing**: The correction is multiplicative on the anomaly, not the signal
- **Preserves ensemble spread**: Different members still produce different anomalies
- **Same coefficients for all members**: Trained once from control vs 3D, applied uniformly

### Computing a_i

The amplitude scaling factor is the ratio of de-meaned standard deviations:

```
a_i = std(WL_3d_det - mean(WL_3d_det)) / std(WL_2d_ctl - mean(WL_2d_ctl))
```

Safeguards:
- **Correlation floor** (default 0.3): If the 2D and 3D signals are uncorrelated at a station (e.g., Panama City Beach, r = 0.21), `a_i` is set to 1.0 to avoid scaling noise
- **Amplitude clipping** (default [0.1, 5.0]): Prevents extreme scaling at weak-signal stations
- **Station identity validation**: Coefficients include a station order list that is checked at apply time to prevent misalignment

### Results (Proof of Concept, Single Cycle)

Training and evaluating on the same cycle (2026-03-18 12Z):

| Metric | Raw 2D | After Correction |
|--------|--------|-----------------|
| Domain Mean RMSE | 0.668 m | **0.175 m** (74% reduction) |
| Domain Median RMSE | 0.557 m | **0.167 m** (70% reduction) |
| Stations improved | — | **272/272** (100%) |

Key stations:
- Key West: 1.21 m → 0.13 m
- Cedar Key: 1.08 m → 0.21 m
- Sewells Point: 0.43 m → 0.13 m

**Note**: These results are on training data. Production use requires training on multiple past cycles and evaluating on held-out cycles.

## Implementation

### Architecture

```
3D Deterministic (secofs)          2D Ensemble (secofs_2d_ufs)
         |                                    |
  stations.nc                     member_000 (control)
         |                         member_001 (GEFS p01)
         |                         member_002 (GEFS p02)
         |                                ...
         |                         member_007 (GEFS p07)
         |                                    |
         +-----------> JNOS_OFS_ENSEMBLE_POST <-----------+
                              |
                    Step 1: Combine staout → station NetCDF
                    Step 1.5: Bias correction
                      - Train: control vs 3D det → coefficients.json
                      - Apply: correct each member → corrected_wl.csv
                    Step 2: Ensemble statistics
```

### Workflow

1. **Prep** (`JNOS_OFS_PREP`): Generate atmospheric forcing, river forcing, tidal boundaries. Shared between 3D det and 2D ensemble.

2. **3D Deterministic** (`JNOS_OFS_NOWCAST` → `JNOS_OFS_FORECAST`): Full 3D SECOFS run producing station timeseries. This is the physics anchor.

3. **2D Ensemble** (`JNOS_OFS_ENSEMBLE_MEMBER` × N): Each member runs with different GEFS atmospheric forcing. Member 000 uses GFS+HRRR (same as 3D det), members 001+ use individual GEFS perturbation members.

4. **Post-Processing** (`JNOS_OFS_ENSEMBLE_POST`):
   - Combines per-member staout text files into station NetCDF
   - Trains bias correction coefficients from member 000 vs 3D det
   - Applies correction to each perturbed member
   - Computes ensemble statistics (mean, spread, percentiles)

### File Locations

| File | Path |
|------|------|
| Bias correction script | `ush/python/nos_ofs/ensemble/ensemble_bias_correct.py` |
| Trained coefficients | `$COMOUT/ensemble/${cycle}/bias_coefficients.json` |
| Corrected member output | `$COMOUT/ensemble/${cycle}/member_{ID}/corrected_wl.csv` |
| 3D det station NC | `$COM3D/secofs.${cycle}.${PDY}.stations.{nowcast\|forecast}.nc` |
| Post-processing ex-script | `scripts/nosofs/exnos_ofs_post.sh` |
| Ensemble post J-job | `jobs/JNOS_OFS_ENSEMBLE_POST` |

### CLI Usage

**Train coefficients** (typically done automatically in post job):
```bash
python3 ensemble_bias_correct.py train \
    --ctl-ncast <2d_control_nowcast_staout_1> \
    --ctl-fcast <2d_control_forecast_staout_1> \
    --det-ncast <3d_det_nowcast_stations.nc> \
    --det-fcast <3d_det_forecast_stations.nc> \
    --station-in <station.in> \
    --nc-base YYYYMMDDHH --fc-base YYYYMMDDHH \
    --corr-floor 0.3 \
    -o bias_coefficients.json
```

**Apply correction to a member**:
```bash
python3 ensemble_bias_correct.py apply \
    --coefficients bias_coefficients.json \
    --det-ncast <3d_det_nowcast_stations.nc> \
    --det-fcast <3d_det_forecast_stations.nc> \
    --ctl-ncast <2d_control_nowcast_staout_1> \
    --ctl-fcast <2d_control_forecast_staout_1> \
    --member-ncast <2d_member_nowcast_staout_1> \
    --member-fcast <2d_member_forecast_staout_1> \
    --station-in <station.in> \
    --nc-base YYYYMMDDHH --fc-base YYYYMMDDHH \
    -o corrected_member_wl.csv
```

**Launch full ensemble** (includes bias correction in post):
```bash
./launch_secofs_2d_ufs_ensemble.sh 12 7 --with-det --pdy 20260318
```

### Coefficients JSON Structure

```json
{
  "coefficients": [
    {
      "station": "Cedar_Key(8727520)",
      "a_i": 0.679,
      "ctl_std": 0.6458,
      "det_std": 0.4388,
      "ctl_mean": -0.3821,
      "det_mean": 0.6542,
      "corr": 0.890,
      "n_samples": 330,
      "clipped": false,
      "gate_reason": ""
    }
  ],
  "station_order": ["Cedar_Key(8727520)", "..."],
  "training": {
    "nc_base": "2026031812",
    "fc_base": "2026031818",
    "amp_clip": [0.1, 5.0],
    "corr_floor": 0.3
  }
}
```

## Limitations and Future Work

### Current Limitations

1. **Single-cycle training**: Coefficients are currently computed from one cycle. For production, train on multiple past cycles and validate on held-out data.

2. **Station-level only**: Correction applies to the 272 station timeseries, not spatial fields. Corrected 2D maps would require a Laplacian diffusion approach (similar to STOFS-2D-GLO bias correction).

3. **Spread compression**: The `a_i` scaling (typically 0.5-0.7 for Gulf stations) compresses ensemble spread along with fixing amplitude. Mean spread preservation is ~70% of raw. Whether this is sufficient depends on the application.

4. **Calm weather bias**: The proof-of-concept was tested during a calm period (March 2026). Ensemble spread is naturally small in benign conditions. The real test is during high-impact weather events where GEFS member divergence is large.

### Future Improvements

1. **Multi-cycle training**: Accumulate `a_i` statistics across many cycles for robust coefficients.

2. **Separate nowcast/forecast coefficients**: The amplitude relationship may differ between the assimilation-constrained nowcast and the free-running forecast.

3. **Constituent-level scaling**: Instead of bulk `a_i`, scale individual tidal constituents (M2, S2, etc.) separately for tide-specific amplitude correction.

4. **Spatial field correction**: Adapt the STOFS-2D-GLO Laplacian diffusion approach to interpolate station-level bias corrections across the SCHISM mesh for corrected 2D spatial products.

5. **V2 vs friction-tuned control**: The choice of which 2D configuration produces the best ensemble anomalies (V2 baseline vs regional friction tuning) should be tested across multiple weather regimes.
