#!/usr/bin/env python3
"""
Test script to verify the ihot=2 NUOPC cap fix.

Simulates the exact arithmetic of schism_step's nws=4 block
with dummy owned/ghost node values matching SECOFS configuration.

SECOFS parameters:
  dt = 120 s
  wtiminc = 3600 s (coupling timestep)
  iths_save = 180 (from 6-hour nowcast hotstart)
  num_schism_steps = 30 (3600/120)
  pr_init = 100000 Pa (misc_subs initialization)
  pr_import = 101325 Pa (DATM/GFS atmospheric pressure)
  windx_init = 0 m/s (misc_subs initialization)
  windx_import = 8.5 m/s (typical 10m wind from DATM)
"""

import sys

# ============================================================
# SECOFS Configuration
# ============================================================
dt = 120.0            # SCHISM timestep (seconds)
wtiminc = 3600.0      # Coupling timestep (seconds)
iths_save = 180       # Hotstart step counter (6hr nowcast)
num_schism_steps = 30  # Steps per ModelAdvance (3600/120)
rho0 = 1025.0         # Water density (kg/m³)
dx = 500.0            # Typical element size (m)

# Initial values from misc_subs.F90 (lines 291-296)
pr_init = 1.0e5       # 100,000 Pa
windx_init = 0.0      # 0 m/s

# Values from DATM Import (only fills owned nodes)
pr_import = 101325.0  # ~1 atm from GFS
windx_import = 8.5    # Typical 10m wind (m/s)


def simulate(label, use_exchange, use_wtime_fix):
    """
    Simulate the first ModelAdvance for ihot=2 forecast.

    Args:
        label: Description string
        use_exchange: If True, exchange ghost nodes before copy (the fix)
        use_wtime_fix: If True, set wtime1=iths_save*dt (the fix)
    """
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    # --------------------------------------------------------
    # State after schism_init + SetClock (before ModelAdvance)
    # --------------------------------------------------------
    # All nodes initialized by misc_subs (lines 291-296)
    pr2_owned = pr_init      # 100000
    pr2_ghost = pr_init      # 100000
    windx2_owned = windx_init  # 0
    windx2_ghost = windx_init  # 0

    pr1_owned = pr_init
    pr1_ghost = pr_init
    windx1_owned = windx_init
    windx1_ghost = windx_init

    print(f"\n--- After misc_subs init ---")
    print(f"  pr2(owned)={pr2_owned:.0f}  pr2(ghost)={pr2_ghost:.0f}")
    print(f"  windx2(owned)={windx2_owned:.1f}  windx2(ghost)={windx2_ghost:.1f}")

    # --------------------------------------------------------
    # SCHISM_Import: fills ONLY owned nodes
    # --------------------------------------------------------
    pr2_owned = pr_import      # 101325 from DATM
    windx2_owned = windx_import  # 8.5 m/s from DATM
    # Ghost nodes UNTOUCHED by Import

    print(f"\n--- After SCHISM_Import ---")
    print(f"  pr2(owned)={pr2_owned:.0f}  pr2(ghost)={pr2_ghost:.0f}  gap={pr2_owned-pr2_ghost:.0f} Pa")
    print(f"  windx2(owned)={windx2_owned:.1f}  windx2(ghost)={windx2_ghost:.1f}  gap={windx2_owned-windx2_ghost:.1f} m/s")

    # --------------------------------------------------------
    # First-call fix in ModelAdvance
    # --------------------------------------------------------
    if use_exchange:
        # FIX: exchange_p2d BEFORE copy
        pr2_ghost = pr2_owned       # Ghost gets correct value from neighbor
        windx2_ghost = windx2_owned
        print(f"\n--- After exchange_p2d (FIX) ---")
        print(f"  pr2(ghost)={pr2_ghost:.0f}  windx2(ghost)={windx2_ghost:.1f}")

    # Copy "2" -> "1" (standard first-call fix)
    pr1_owned = pr2_owned
    pr1_ghost = pr2_ghost
    windx1_owned = windx2_owned
    windx1_ghost = windx2_ghost

    # Set output arrays
    pr_owned = pr2_owned
    pr_ghost = pr2_ghost
    windx_owned = windx2_owned
    windx_ghost = windx2_ghost

    # Set time brackets
    if use_wtime_fix:
        wtime1 = float(iths_save) * dt   # 21600
        wtime2 = wtime1 + wtiminc         # 25200
    else:
        wtime1 = 0.0
        wtime2 = wtiminc                   # 3600

    print(f"\n--- After first-call fix ---")
    print(f"  pr1(owned)={pr1_owned:.0f}  pr1(ghost)={pr1_ghost:.0f}")
    print(f"  windx1(owned)={windx1_owned:.1f}  windx1(ghost)={windx1_ghost:.1f}")
    print(f"  wtime1={wtime1:.0f}  wtime2={wtime2:.0f}")

    # --------------------------------------------------------
    # Simulate schism_step loop (first 10 steps)
    # --------------------------------------------------------
    it_start = iths_save + 1   # 181

    print(f"\n--- schism_step loop (it={it_start} to {it_start+num_schism_steps-1}) ---")
    print(f"  {'Step':>5} {'time':>8} {'time>wt2':>8} {'wtime1':>8} {'wtime2':>8} "
          f"{'wtratio':>8} {'pr_own':>8} {'pr_gho':>8} {'dpr':>8} {'wx_gho':>8} {'accel':>8}")
    print(f"  {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8} "
          f"{'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    max_dpr = 0.0
    max_accel = 0.0
    max_windx_ghost = 0.0

    for step in range(num_schism_steps):
        it = it_start + step
        time = it * dt

        # --- nws=4 block in schism_step ---
        bracket_advance = time > wtime2

        if bracket_advance:
            # Bracket advance (lines 589-680 of schism_step.F90)
            wtime1 = wtime2
            wtime2 = wtime2 + wtiminc

            # Copy "2" -> "1" (BEFORE exchange)
            pr1_owned = pr2_owned
            pr1_ghost = pr2_ghost
            windx1_owned = windx2_owned
            windx1_ghost = windx2_ghost

            # exchange_p2d (AFTER copy, inside bracket advance)
            # This fixes ghost nodes in "2" arrays
            pr2_ghost = pr2_owned
            windx2_ghost = windx2_owned

        # Interpolation (lines 683-688)
        wtratio = (time - wtime1) / wtiminc

        pr_owned = pr1_owned + wtratio * (pr2_owned - pr1_owned)
        pr_ghost = pr1_ghost + wtratio * (pr2_ghost - pr1_ghost)
        windx_owned_val = windx1_owned + wtratio * (windx2_owned - windx1_owned)
        windx_ghost_val = windx1_ghost + wtratio * (windx2_ghost - windx1_ghost)

        dpr = abs(pr_ghost - pr_owned)
        accel = dpr / dx / rho0  # m/s² from pressure gradient

        max_dpr = max(max_dpr, dpr)
        max_accel = max(max_accel, accel)
        max_windx_ghost = max(max_windx_ghost, abs(windx_ghost_val))

        # Print first 10 steps, then every 5th
        if step < 10 or step % 5 == 0 or step == num_schism_steps - 1:
            print(f"  {it:5d} {time:8.0f} {'YES' if bracket_advance else 'no':>8} "
                  f"{wtime1:8.0f} {wtime2:8.0f} {wtratio:8.3f} "
                  f"{pr_owned:8.0f} {pr_ghost:8.0f} {dpr:8.0f} "
                  f"{windx_ghost_val:8.1f} {accel:8.4f}")

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------
    vel_impulse = max_accel * dt
    print(f"\n--- Summary ---")
    print(f"  Max pressure error at ghost boundary: {max_dpr:.0f} Pa")
    print(f"  Max acceleration from pressure gradient: {max_accel:.4f} m/s²")
    print(f"  Max velocity impulse in one step ({dt:.0f}s): {vel_impulse:.2f} m/s")
    print(f"  Max ghost wind speed: {max_windx_ghost:.1f} m/s (normal: {windx_import:.1f})")

    if max_dpr > 2000:
        print(f"\n  *** DANGEROUS: {max_dpr:.0f} Pa pressure error will cause blowup! ***")
        eta_est = vel_impulse * dt * 10 / dx  # rough η estimate
        print(f"  *** Estimated water level perturbation: ~{eta_est:.1f} m ***")
    elif max_dpr > 100:
        print(f"\n  ** Minor ghost pressure error ({max_dpr:.0f} Pa) — tolerable (same as ihot=1)")
    else:
        print(f"\n  OK: Ghost pressure error negligible ({max_dpr:.0f} Pa)")

    return max_dpr


# ============================================================
# Run all scenarios
# ============================================================
print("=" * 70)
print("  SCHISM ihot=2 NUOPC Cap Fix Verification")
print("  Using SECOFS dummy values")
print("=" * 70)
print(f"\n  dt={dt}s, wtiminc={wtiminc}s, iths_save={iths_save}")
print(f"  pr_init={pr_init:.0f} Pa (misc_subs), pr_import={pr_import:.0f} Pa (DATM)")
print(f"  windx_init={windx_init} m/s, windx_import={windx_import} m/s")

# Scenario 1: Current buggy code (no exchange, wtime1=0)
dpr1 = simulate(
    "SCENARIO 1: CURRENT CODE (BUGGY) — no exchange, wtime1=0",
    use_exchange=False,
    use_wtime_fix=False
)

# Scenario 2: wtime fix only (no exchange)  — fallback option
dpr2 = simulate(
    "SCENARIO 2: WTIME FIX ONLY — no exchange, wtime1=iths_save*dt",
    use_exchange=False,
    use_wtime_fix=True
)

# Scenario 3: exchange fix only (no wtime fix)
dpr3 = simulate(
    "SCENARIO 3: EXCHANGE FIX ONLY — exchange, wtime1=0",
    use_exchange=True,
    use_wtime_fix=False
)

# Scenario 4: Both fixes (the full fix)
dpr4 = simulate(
    "SCENARIO 4: FULL FIX — exchange + wtime1=iths_save*dt",
    use_exchange=True,
    use_wtime_fix=True
)

# ============================================================
# Also simulate ihot=1 (nowcast) to verify no regression
# ============================================================
print(f"\n{'='*70}")
print(f"  SCENARIO 5: ihot=1 NOWCAST (regression check)")
print(f"{'='*70}")

# For ihot=1: iths_save=0, it starts at 1
print(f"\n  ihot=1: iths_save=0, it=1, time starts at {1*dt:.0f}")
iths_save_bak = iths_save

# Temporarily override for ihot=1
iths_save = 0
dpr5 = simulate(
    "SCENARIO 5: ihot=1 WITH FULL FIX (must match old behavior)",
    use_exchange=True,
    use_wtime_fix=True
)
iths_save = iths_save_bak

# ============================================================
# Final comparison
# ============================================================
print(f"\n\n{'='*70}")
print(f"  COMPARISON SUMMARY")
print(f"{'='*70}")
print(f"\n  {'Scenario':<50} {'Max dpr (Pa)':>12} {'Verdict':>12}")
print(f"  {'-'*50} {'-'*12} {'-'*12}")
print(f"  {'1. Current buggy code':<50} {dpr1:>12.0f} {'CRASH':>12}")
print(f"  {'2. Wtime fix only (fallback)':<50} {dpr2:>12.0f} {'OK':>12}")
print(f"  {'3. Exchange fix only':<50} {dpr3:>12.0f} {'OK':>12}")
print(f"  {'4. Full fix (exchange + wtime)':<50} {dpr4:>12.0f} {'BEST':>12}")
print(f"  {'5. ihot=1 with full fix (regression)':<50} {dpr5:>12.0f} {'OK':>12}")
print()

if dpr4 == 0:
    print("  RESULT: Full fix eliminates ghost pressure error completely.")
else:
    print(f"  RESULT: Full fix reduces error to {dpr4:.0f} Pa (from {dpr1:.0f}).")

if dpr5 <= dpr2:
    print("  REGRESSION: ihot=1 behavior is identical or better. No regression.")
else:
    print("  WARNING: ihot=1 behavior is worse! Check the fix.")
