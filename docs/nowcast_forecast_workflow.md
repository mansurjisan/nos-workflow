# Nowcast/Forecast Workflow Diagrams

## Before vs After: Why Unify?

### BEFORE — Two Completely Separate Code Paths

```mermaid
flowchart TB
    subgraph BEFORE["BEFORE: Separate Implementations"]
        direction TB

        subgraph COMF_OLD["SECOFS (COMF) — exnos_ofs_nowcast_forecast.sh"]
            direction TB
            CO1["nos_ofs_launch.sh secofs"] --> CO2["nos_ofs_nowcast_forecast.sh nowcast"]
            CO2 --> CO3["nos_ofs_archive.sh nowcast"]
            CO3 --> CO4["nos_ofs_nowcast_forecast.sh forecast"]
            CO4 --> CO5["nos_ofs_archive.sh forecast"]
        end

        subgraph STOFS_OLD["STOFS — exstofs_3d_atl_now_forecast.sh"]
            direction TB
            SO1["Link 19 static files"] --> SO2["Copy all forcing files"]
            SO2 --> SO3["Find hotstart from prev cycle"]
            SO3 --> SO4["Copy param.nml for full 5.5 days"]
            SO4 --> SO5["mpiexec pschism<br/>Single continuous run<br/>rnday=5.5, 132h"]
            SO5 --> SO6["Combine distributed hotstart"]
            SO6 --> SO7["Archive outputs"]
        end

        COMF_OLD ~~~ STOFS_OLD
    end

    style BEFORE fill:#fee,stroke:#c33
    style COMF_OLD fill:#fff5f5,stroke:#d88
    style STOFS_OLD fill:#fff5f5,stroke:#d88
```

**Problems with the old approach:**
- COMF and STOFS have **zero shared code** for nowcast/forecast
- STOFS runs a **single monolithic 5.5-day simulation** — no separate nowcast/forecast phases
- Adding a new OFS means writing **a brand-new ex-script from scratch**
- Bug fixes in one framework **never propagate** to the other
- Different error handling, different logging, different conventions
- **563 lines** (STOFS) + **237 lines** (COMF) = **800 lines** of separate logic

---

### AFTER — Unified 4-Step Framework

```mermaid
flowchart TB
    subgraph AFTER["AFTER: Shared Pipeline via nos_ofs_model_run.sh"]
        direction TB

        subgraph SHARED["Shared Interface — Both Systems Call Same Functions"]
            direction TB
            F1["stage_model_files(phase)"]
            F2["prepare_restart(phase)"]
            F3["execute_model(phase)"]
            F4["archive_outputs(phase)"]
            F1 --> F2 --> F3 --> F4
        end

        subgraph DISPATCH["Framework Dispatch — case OFS_FRAMEWORK"]
            direction LR
            subgraph COMF_INT["comf internals"]
                direction TB
                CI1["_comf_stage_files<br/>→ nos_ofs_launch.sh"]
                CI2["_comf_prepare_restart<br/>→ no-op"]
                CI3["_comf_execute_model<br/>→ nos_ofs_nowcast_forecast.sh"]
                CI4["_comf_archive_outputs<br/>→ nos_ofs_archive.sh"]
            end
            subgraph STOFS_INT["stofs internals"]
                direction TB
                SI1["_stofs_stage_files<br/>→ link + copy files"]
                SI2["_stofs_prepare_restart<br/>→ find/combine hotstart"]
                SI3["_stofs_execute_model<br/>→ mpiexec pschism"]
                SI4["_stofs_archive_outputs<br/>→ copy logs to COMOUT"]
            end
        end

        SHARED --> DISPATCH
    end

    style AFTER fill:#efe,stroke:#3a3
    style SHARED fill:#f0fff0,stroke:#6b6
    style COMF_INT fill:#f5f5ff,stroke:#88d
    style STOFS_INT fill:#fff5f0,stroke:#da8
```

**Benefits of the unified approach:**
- Both systems use the **same 4 function calls** in the same order
- STOFS now runs **two separate phases** (nowcast + forecast) matching COMF
- Adding a new OFS = just implement `_newframework_*` internal functions
- **138 lines** (STOFS) + **181 lines** (COMF) = **319 lines** (down from 800)
- Shared error handling and logging patterns
- One place to add monitoring, metrics, or workflow improvements

---

### Code Reduction

```mermaid
graph LR
    subgraph BEFORE["BEFORE"]
        direction TB
        B1["STOFS ex-script<br/>563 lines"]
        B2["COMF ex-script<br/>237 lines"]
        B3["Shared code<br/>0 lines"]
    end

    subgraph AFTER["AFTER"]
        direction TB
        A1["STOFS ex-script<br/>138 lines"]
        A2["COMF ex-script<br/>181 lines"]
        A3["Shared library<br/>nos_ofs_model_run.sh<br/>~480 lines"]
    end

    BEFORE -->|"Refactor"| AFTER

    style B1 fill:#fdd,stroke:#c33
    style B2 fill:#fdd,stroke:#c33
    style B3 fill:#fee,stroke:#ccc
    style A1 fill:#dfd,stroke:#3a3
    style A2 fill:#dfd,stroke:#3a3
    style A3 fill:#ddf,stroke:#33c
```

---

### Execution Pattern Comparison

```mermaid
flowchart LR
    subgraph OLD_STOFS["BEFORE: STOFS — Single Run"]
        direction TB
        OS1["Feb 9 12z"]
        OS2["Single SCHISM execution<br/>rnday=5.5<br/>132 hours continuous"]
        OS3["Feb 15 00z"]
        OS1 --> OS2 --> OS3
    end

    subgraph NEW_STOFS["AFTER: STOFS — Two Phases"]
        direction TB
        NS1["Feb 9 12z"]
        NS2["Nowcast SCHISM<br/>rnday=1.0, 24h<br/>576 steps"]
        NS3["Feb 10 12z<br/>Combine hotstart<br/>Swap param.nml"]
        NS4["Forecast SCHISM<br/>rnday=4.5, 108h<br/>2592 steps"]
        NS5["Feb 15 00z"]
        NS1 --> NS2 --> NS3 --> NS4 --> NS5
    end

    subgraph SECOFS["SECOFS — Two Phases (unchanged)"]
        direction TB
        SE1["Feb 9 18z"]
        SE2["Nowcast SCHISM<br/>rnday=0.25, 6h<br/>180 steps"]
        SE3["Feb 10 00z<br/>Restart handoff"]
        SE4["Forecast SCHISM<br/>rnday=2.0, 48h<br/>1440 steps"]
        SE5["Feb 12 00z"]
        SE1 --> SE2 --> SE3 --> SE4 --> SE5
    end

    style OLD_STOFS fill:#fee,stroke:#c33
    style NEW_STOFS fill:#efe,stroke:#3a3
    style SECOFS fill:#eef,stroke:#33c
```

**Key change**: STOFS went from one monolithic 5.5-day run to two separate phases (24h + 108h), matching COMF's pattern. Same total simulation coverage, same physics — just split at the nowcast/forecast boundary.

---

### Adding a New OFS — Before vs After

The shared library dispatches by **framework** (comf or stofs), not by individual OFS.
All COMF systems (secofs, cbofs, dbofs, leofs, ngofs2, sfbofs, gomofs, ...) share `_comf_*` functions.
Adding a new OFS within an existing framework requires **no changes** to `nos_ofs_model_run.sh`.

```mermaid
flowchart TB
    subgraph DISPATCH["nos_ofs_model_run.sh — Framework Dispatch"]
        direction TB
        D1{"OFS_FRAMEWORK?"}
        D1 -->|comf| COMF["_comf_* functions"]
        D1 -->|stofs| STOFS["_stofs_* functions"]
    end

    subgraph COMF_OFS["All COMF OFS — same code path, zero changes needed"]
        direction LR
        C1[secofs]
        C2[cbofs]
        C3[dbofs]
        C4[leofs]
        C5[ngofs2]
        C6[gomofs]
        C7["new_ofs?"]
    end

    subgraph STOFS_OFS["All STOFS OFS — same code path"]
        direction LR
        S1[stofs_3d_atl]
        S2[stofs_3d_pac]
    end

    COMF --> COMF_OFS
    STOFS --> STOFS_OFS

    style DISPATCH fill:#f0f0ff,stroke:#66c
    style COMF_OFS fill:#f0fff0,stroke:#6b6
    style STOFS_OFS fill:#fff5f0,stroke:#da8
    style C7 fill:#dfd,stroke:#3a3,stroke-width:3px
```

```mermaid
flowchart LR
    subgraph BEFORE_NEW["BEFORE: Adding New COMF OFS"]
        direction TB
        BN1["Copy exnos_ofs_nowcast_forecast.sh"] --> BN2["Modify 237 lines<br/>for new OFS specifics"]
        BN2 --> BN3["Duplicate error handling<br/>logging, archiving"]
        BN3 --> BN4["Hope you didn't miss<br/>any edge cases"]
    end

    subgraph AFTER_NEW["AFTER: Adding New COMF OFS"]
        direction TB
        AN1["Create YAML config<br/>parm/systems/new_ofs.yaml"] --> AN2["Create PBS script<br/>pbs/jnos_newofs_*.pbs"]
        AN2 --> AN3["Done — shared library<br/>handles everything via<br/>existing _comf_* functions"]
    end

    style BEFORE_NEW fill:#fee,stroke:#c33
    style AFTER_NEW fill:#efe,stroke:#3a3
```

You only modify `nos_ofs_model_run.sh` if adding an entirely new **framework** (rare — currently just `comf` and `stofs`).

---

## Unified 4-Step Framework

Both SECOFS (COMF) and STOFS use the same interface from `nos_ofs_model_run.sh`.
The framework-specific internals differ, but the calling pattern is identical.

```mermaid
graph TD
    A[PBS Job Submitted] --> B[JNOS_OFS_NOWCST_FCST<br/>J-job]
    B --> C{OFS_FRAMEWORK?}
    C -->|comf| D[exnos_ofs_nowcast_forecast.sh]
    C -->|stofs| E[exstofs_3d_atl_now_forecast.sh]
    D --> F[source nos_ofs_model_run.sh]
    E --> F
    F --> G[Unified 4-Step Pipeline]
```

---

## SECOFS (COMF Framework) — 00z Cycle

```mermaid
flowchart TD
    subgraph PBS["PBS Job: jnos_secofs_nowfcst_00.pbs"]
        A[Load modules<br/>OFS=secofs, cyc=00]
    end

    subgraph JJOB["J-job: JNOS_OFS_NOWCST_FCST"]
        B[Set OFS_FRAMEWORK=comf]
        C[Load YAML config<br/>parm/systems/secofs.yaml]
        D[Set LD_PRELOAD for<br/>NetCDF Fortran lib]
    end

    subgraph EXSCRIPT["Ex-script: exnos_ofs_nowcast_forecast.sh"]
        E[Config loading<br/>YAML/CTL 3-tier fallback]
        F[source nos_ofs_model_run.sh]
    end

    subgraph NOWCAST["NOWCAST PHASE — 6 hours"]
        G["stage_model_files('nowcast')"]
        G1[_comf_stage_files<br/>nos_ofs_launch.sh secofs nowcast]
        G2[Search for restart file<br/>Compute time windows<br/>Copy grid + forcing to DATA]

        H["execute_model('nowcast')"]
        H1[_comf_execute_model<br/>nos_ofs_nowcast_forecast.sh nowcast]
        H2[Configure param.nml<br/>rnday=0.25, start=Feb 9 18z]
        H3["mpiexec -n 1200 schism_secofs<br/>SCHISM runs: Feb 9 18z → Feb 10 00z<br/>dt=120s, 180 steps"]
        H4[Produces:<br/>schout_*.nc + rst.nowcast.nc]

        I["archive_outputs('nowcast')"]
        I1[_comf_archive_outputs<br/>nos_ofs_archive.sh nowcast]
        I2[Copy nowcast outputs<br/>to COMOUT]
    end

    subgraph FORECAST["FORECAST PHASE — 48 hours"]
        J["execute_model('forecast')"]
        J1[_comf_execute_model<br/>nos_ofs_nowcast_forecast.sh forecast]
        J2[Configure param.nml<br/>rnday=2.0, start=Feb 10 00z]
        J3[rst.nowcast.nc → hotstart.nc]
        J4["mpiexec -n 1200 schism_secofs<br/>SCHISM runs: Feb 10 00z → Feb 12 00z<br/>dt=120s, 1440 steps"]
        J5[Produces:<br/>schout_*.nc + rst.forecast.nc]

        K["archive_outputs('forecast')"]
        K1[_comf_archive_outputs<br/>nos_ofs_archive.sh forecast]
        K2[Copy forecast outputs<br/>to COMOUT]
    end

    L["END OF NOWCAST/FORECAST SUCCESSFULLY"]

    PBS --> A --> JJOB
    B --> C --> D
    JJOB --> EXSCRIPT
    E --> F

    F --> G --> G1 --> G2
    G2 --> H --> H1 --> H2 --> H3 --> H4
    H4 --> I --> I1 --> I2

    I2 --> J --> J1 --> J2 --> J3 --> J4 --> J5
    J5 --> K --> K1 --> K2

    K2 --> L
```

---

## STOFS-3D Atlantic (STOFS Framework) — 12z Cycle

```mermaid
flowchart TD
    subgraph PBS["PBS Job: jnos_stofs3datl_nowfcst_12.pbs"]
        A[Load modules<br/>OFS=stofs_3d_atl, cyc=12]
    end

    subgraph JJOB["J-job: JNOS_OFS_NOWCST_FCST"]
        B[Set OFS_FRAMEWORK=stofs]
        C[Load YAML config<br/>parm/systems/stofs_3d_atl.yaml]
        D[Compute time vars<br/>PDYHH_NCAST_BEGIN, PDYHH_FCAST_BEGIN]
    end

    subgraph EXSCRIPT["Ex-script: exstofs_3d_atl_now_forecast.sh"]
        E[source nos_ofs_model_run.sh]
    end

    subgraph NOWCAST["NOWCAST PHASE — 24 hours"]
        G["stage_model_files('nowcast')"]
        G1[_stofs_stage_files<br/>Link static files from FIXstofs3d]
        G2[Copy forcing from COMOUTrerun<br/>bctides, river, sflux, OBC, nudging]
        G3[Copy nowcast param.nml<br/>rnday=1.0, start=Feb 9 12z]

        H["prepare_restart('nowcast')"]
        H1[_stofs_prepare_restart<br/>Search 0-4 days back for<br/>hotstart.stofs3d.nc > 20GB]
        H2{Found?}
        H3[Use previous cycle hotstart]
        H4[Use coldstart file from fix/]

        I["execute_model('nowcast')"]
        I1[_stofs_execute_model<br/>Validate: param.nml, bctides.in,<br/>hgrid.gr3, vgrid.in]
        I2["mpiexec -n 4320 stofs_3d_atl_pschism 6<br/>SCHISM runs: Feb 9 12z → Feb 10 12z<br/>dt=150s, 576 steps"]
        I3[Produces:<br/>schout_*.nc<br/>hotstart_00000_576.nc distributed files]

        J["archive_outputs('nowcast')"]
        J1[Copy nowcast log to COMOUT]
    end

    subgraph FORECAST["FORECAST PHASE — 108 hours"]
        K["prepare_restart('forecast')"]
        K1[_stofs_prepare_restart<br/>exstofs_3d_atl_hot_restart_prep.sh]
        K2[Find distributed hotstart<br/>files at step 576]
        K3[stofs_3d_atl_combine_hotstart<br/>Merge into single hotstart.nc]
        K4[Copy forecast param.nml<br/>rnday=4.5, start=Feb 10 12z]
        K5["Set ihot=2 in param.nml<br/>Clean nowcast schout_*.nc<br/>Create mirror.out, flux.out, staout_*"]

        M["execute_model('forecast')"]
        M1[_stofs_execute_model<br/>Validate inputs]
        M2["mpiexec -n 4320 stofs_3d_atl_pschism 6<br/>SCHISM runs: Feb 10 12z → Feb 15 00z<br/>dt=150s, 2592 steps"]
        M3[Produces:<br/>schout_*.nc<br/>hotstart distributed files]

        N["archive_outputs('forecast')"]
        N1[Copy forecast log to COMOUT]
    end

    L["Finished SUCCESSFULLY"]

    PBS --> A --> JJOB
    B --> C --> D
    JJOB --> EXSCRIPT --> E

    E --> G --> G1 --> G2 --> G3
    G3 --> H --> H1 --> H2
    H2 -->|Yes| H3
    H2 -->|No| H4
    H3 --> I
    H4 --> I
    I --> I1 --> I2 --> I3
    I3 --> J --> J1

    J1 --> K --> K1 --> K2 --> K3 --> K4 --> K5
    K5 --> M --> M1 --> M2 --> M3
    M3 --> N --> N1

    N1 --> L
```

---

## Side-by-Side Comparison

```mermaid
graph LR
    subgraph SECOFS["SECOFS (COMF)"]
        direction TB
        S1["stage_model_files<br/>→ nos_ofs_launch.sh"]
        S2["execute_model nowcast<br/>→ nos_ofs_nowcast_forecast.sh<br/>6h, 1200 cores"]
        S3["archive_outputs nowcast<br/>→ nos_ofs_archive.sh"]
        S4["execute_model forecast<br/>→ nos_ofs_nowcast_forecast.sh<br/>48h, 1200 cores"]
        S5["archive_outputs forecast<br/>→ nos_ofs_archive.sh"]
        S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph STOFS["STOFS-3D Atlantic"]
        direction TB
        T1["stage_model_files<br/>→ link/copy files directly"]
        T2["prepare_restart nowcast<br/>→ search for hotstart"]
        T3["execute_model nowcast<br/>→ mpiexec pschism<br/>24h, 4320 cores"]
        T4["archive_outputs nowcast"]
        T5["prepare_restart forecast<br/>→ combine_hotstart + param.nml swap"]
        T6["execute_model forecast<br/>→ mpiexec pschism<br/>108h, 4320 cores"]
        T7["archive_outputs forecast"]
        T1 --> T2 --> T3 --> T4 --> T5 --> T6 --> T7
    end
```

---

## Timeline Comparison

```mermaid
gantt
    title Model Run Timeline — Feb 10, 2026
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %b %d %Hz

    section SECOFS 00z
    Nowcast (6h)     :s_nc, 2026-02-09 18:00, 6h
    Forecast (48h)   :s_fc, after s_nc, 48h

    section STOFS 12z
    Nowcast (24h)    :t_nc, 2026-02-09 12:00, 24h
    Forecast (108h)  :t_fc, after t_nc, 108h
```

---

## Split-Job Mode for Production (ecFlow)

### Why Split?

The combined `JNOS_OFS_NOWCST_FCST` job runs both phases in a single PBS allocation.
This works for development but production ecFlow needs:

- **Independent retries** — if forecast fails, re-run only the forecast
- **Separate monitoring** — ecFlow tracks each task's status independently
- **Resource flexibility** — nowcast and forecast can have different walltimes
- **Dependency management** — post-processing triggers only after forecast completes

### Evolution of the Workflow

```mermaid
graph TD
    subgraph "Original STOFS (IT-STOFS)"
        P0[prep_nowcast] --> NF0["now_forecast<br/>(single continuous run)"]
        NF0 --> PO0A[post_1]
        PO0A --> PO0B[post_2]
        PO0B --> RS0[temp_salt_restart]
    end

    subgraph "Combined Mode (Dev)"
        P2[PREP] --> NF["NOWCAST → FORECAST<br/>(shared $DATA)"]
        NF --> PO2[POST]
    end

    subgraph "Split-Job Mode (Production)"
        P1[PREP] --> NC[NOWCAST]
        NC -->|"afterok dependency"| FC[FORECAST]
        FC --> PO1[POST]
        NC -.->|"hotstart via $COMOUT"| FC
    end

    style NF0 fill:#854d0e,color:#fff
    style NF fill:#2d6a4f,color:#fff
    style NC fill:#2d6a4f,color:#fff
    style FC fill:#2d6a4f,color:#fff
```

### Script Hierarchy

```mermaid
graph TD
    ECF_NC["ecf/stofs_3d_atl_nowcast.ecf"] -.->|"ecFlow trigger"| ECF_FC["ecf/stofs_3d_atl_forecast.ecf"]

    ECF_NC --> JNC["jobs/JNOS_OFS_NOWCAST"]
    ECF_FC --> JFC["jobs/JNOS_OFS_FORECAST"]

    JNC --> ENC["scripts/.../exnos_ofs_nowcast.sh"]
    JFC --> EFC["scripts/.../exnos_ofs_forecast.sh"]

    ENC --> LIB["ush/nos_ofs_model_run.sh<br/><i>stage → restart → execute → archive</i>"]
    EFC --> LIB

    JNC & JFC --> CFG["ush/nos_ofs_config.sh<br/>+ parm/systems/stofs_3d_atl.yaml"]

    LIB -->|"nowcast: combine + archive"| COMOUT[("$COMOUT<br/>hotstart.stofs3d.nc")]
    COMOUT -->|"forecast: retrieve"| LIB

    style COMOUT fill:#2d6a4f,color:#fff
    style LIB fill:#1e3a5f,color:#fff
```

Each layer has a single responsibility:

| Layer | Files | Responsibility |
|-------|-------|----------------|
| **ecf/PBS** | `ecf/*.ecf` or `pbs/*.pbs` | Resource allocation, modules, env vars |
| **J-Job** | `jobs/JNOS_OFS_NOWCAST`, `JNOS_OFS_FORECAST` | Directory setup, YAML config, framework dispatch |
| **Ex-Script** | `scripts/.../exnos_ofs_{nowcast,forecast}.sh` | Orchestrate 4-step pipeline with error handling |
| **Shared Library** | `ush/nos_ofs_model_run.sh` | Model run logic (framework-agnostic) |

### Hotstart Handoff — The Key Challenge

In combined mode, both phases share `$DATA` — the forecast reads distributed
hotstart files directly from `$DATA/outputs/`. In split mode, each job has its
own `$DATA`, so the hotstart must pass through `$COMOUT`.

```mermaid
flowchart LR
    subgraph NC_JOB["Nowcast Job ($DATA_nowcast)"]
        NC_RUN["SCHISM nowcast<br/>produces distributed<br/>hotstart_NNNNNN_576.nc"]
        NC_COMBINE["combine_hotstart<br/>→ single hotstart_it=576.nc"]
        NC_ARCHIVE["cp → $COMOUT/<br/>hotstart.stofs3d.nc"]
        NC_RUN --> NC_COMBINE --> NC_ARCHIVE
    end

    subgraph COMOUT["$COMOUT"]
        HS[("hotstart.stofs3d.nc<br/>~20 GB")]
    end

    subgraph FC_JOB["Forecast Job ($DATA_forecast)"]
        FC_RETRIEVE["cp $COMOUT/hotstart<br/>→ $DATA/hotstart.nc"]
        FC_PARAM["Copy forecast param.nml<br/>Set ihot=2"]
        FC_RUN["SCHISM forecast<br/>continues from nowcast state"]
        FC_RETRIEVE --> FC_PARAM --> FC_RUN
    end

    NC_ARCHIVE --> HS --> FC_RETRIEVE

    style HS fill:#2d6a4f,color:#fff
```

### Nowcast Job — Detailed Flow

```mermaid
flowchart TD
    subgraph STAGE["stage_model_files('nowcast')"]
        S1[Link 14 static files from FIXstofs3d]
        S2[Copy nowcast param.nml from COMOUTrerun]
        S3[Copy forcing: bctides, river, sflux, OBC, nudging]
    end

    subgraph RESTART["prepare_restart('nowcast')"]
        R1{COMOUTrerun/<br/>restart.nc?}
        R1 -->|Yes| R2[Use prep restart]
        R1 -->|No| R3{Previous cycle<br/>hotstart in COMINstofs?<br/>Search 0-4 days back}
        R3 -->|Yes| R4[Use previous hotstart]
        R3 -->|No| R5[Use coldstart from fix/]
    end

    subgraph EXECUTE["execute_model('nowcast')"]
        E1[Validate: param.nml, bctides.in, hgrid.gr3, vgrid.in]
        E2["mpiexec -n 4320 pschism 6<br/>rnday=1.0, dt=150s, 576 steps"]
        E3[Check mirror.out for success]
    end

    subgraph ARCHIVE["archive_outputs('nowcast')"]
        A1[Copy nowcast.log to COMOUT]
        A2[Find distributed hotstart at step 576]
        A3["combine_hotstart -i 576"]
        A4["Archive → $COMOUT/hotstart.stofs3d.nc"]
    end

    STAGE --> RESTART --> EXECUTE --> ARCHIVE

    style ARCHIVE fill:#1a3a2a,color:#fff
```

### Forecast Job — Detailed Flow

```mermaid
flowchart TD
    subgraph STAGE["stage_model_files('forecast')"]
        S1[Link 14 static files from FIXstofs3d]
        S2[Copy forecast param.nml from COMOUTrerun]
        S3[Copy forcing: bctides, river, sflux, OBC, nudging]
    end

    subgraph RESTART["prepare_restart('forecast')"]
        R1{"$COMOUT/<br/>hotstart.stofs3d.nc?"}
        R1 -->|"Yes (split-job)"| R2["cp to $DATA/hotstart.nc<br/>Create mirror.out, flux.out, staout_*"]
        R1 -->|"No"| R3{"Local distributed<br/>hotstart files?"}
        R3 -->|"Yes (combined-job)"| R4[Run hot_restart_prep.sh]
        R3 -->|"No"| R5[ERROR: no hotstart]
        R2 --> R6["Copy forecast param.nml<br/>Set ihot=2<br/>Clean nowcast schout_*.nc"]
        R4 --> R6
    end

    subgraph EXECUTE["execute_model('forecast')"]
        E1[Validate: param.nml, bctides.in, hgrid.gr3, vgrid.in]
        E2["mpiexec -n 4320 pschism 6<br/>rnday=4.5, dt=150s, 2592 steps"]
        E3[Check mirror.out for success]
    end

    subgraph ARCHIVE["archive_outputs('forecast')"]
        A1[Copy forecast.log to COMOUT]
    end

    STAGE --> RESTART --> EXECUTE --> ARCHIVE

    style RESTART fill:#1a3a2a,color:#fff
```

### Combined vs Split Mode Comparison

| Aspect | Combined (`JNOS_OFS_NOWCST_FCST`) | Split (`NOWCAST` + `FORECAST`) |
|--------|-----------------------------------|-------------------------------|
| `$DATA` | Shared between phases | Separate per job |
| Hotstart handoff | Local combine in forecast prep | Via `$COMOUT` (archived by nowcast) |
| COMF env vars | Set once by `launch.sh` | `launch.sh` re-runs in forecast job |
| Ex-script | `exstofs_3d_atl_now_forecast.sh` | `exnos_ofs_nowcast.sh` + `exnos_ofs_forecast.sh` |
| PBS submission | Single `qsub` | Two `qsub` with dependency |
| ecFlow compatible | No (single task) | Yes (separate tasks) |
| Retry granularity | Must retry both phases | Can retry forecast independently |
| Walltime | 04:00:00 total | Nowcast 01:30:00 + Forecast 04:00:00 |

Both modes use the **same** `nos_ofs_model_run.sh` functions — the functions
detect which mode they're in based on what files are available.

### Submission

**Dev testing (PBS):**
```bash
NCST_JOB=$(qsub jnos_stofs3datl_nowcast_12.pbs)
echo "Nowcast job: $NCST_JOB"
qsub -W depend=afterok:${NCST_JOB} jnos_stofs3datl_forecast_12.pbs
```

**Production (ecFlow):**
```
suite stofs_3d_atl
  family cycle_12
    task prep
    task nowcast
      trigger prep == complete
    task forecast
      trigger nowcast == complete
    task post
      trigger forecast == complete
  endfamily
endsuite
```
