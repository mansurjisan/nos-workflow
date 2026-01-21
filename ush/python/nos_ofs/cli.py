#!/usr/bin/env python3
"""
NOS OFS Command Line Interface

This module provides CLI entry points for the nos_ofs workflow package.
It bridges the gap between legacy shell scripts and Python-based processing.

Usage from shell scripts:
    # Run a workflow stage
    python3 -m nos_ofs.cli run stofs_3d_atl prep_nowcast --pdy 20250504 --cyc 12
    python3 -m nos_ofs.cli run stofs_3d_atl now_forecast --pdy 20250504 --cyc 12
    python3 -m nos_ofs.cli run cbofs prep --pdy 20250504 --cyc 06

    # Run full prep stage with YAML config (legacy)
    python3 -m nos_ofs.cli prep --config $OFS_CONFIG --ofs stofs_3d_atl

    # Run specific forcing
    python3 -m nos_ofs.cli forcing gfs --config $OFS_CONFIG

    # Export YAML config to shell environment
    python3 -m nos_ofs.cli export-env --config $OFS_CONFIG --framework stofs

    # List available OFS systems and stages
    python3 -m nos_ofs.cli list
    python3 -m nos_ofs.cli stages
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def get_config_path() -> Optional[Path]:
    """Get configuration file path from environment or arguments."""
    config_path = os.environ.get('OFS_CONFIG')
    if config_path and Path(config_path).exists():
        return Path(config_path)

    ofs = os.environ.get('OFS', '').lower()
    if ofs:
        search_paths = [
            Path(os.environ.get('HOMEstofs', '')) / 'parm' / 'systems' / f'{ofs}.yaml',
            Path(os.environ.get('HOMEnos', '')) / 'parm' / 'systems' / f'{ofs}.yaml',
            Path(__file__).parent.parent.parent.parent.parent / 'parm' / 'systems' / f'{ofs}.yaml',
        ]
        for path in search_paths:
            if path.exists():
                return path
    return None


def cmd_prep(args):
    """Run preprocessing stage."""
    from .models.legacy_runner import LegacyScriptRunner
    from .models.schism_config import StofsConfig

    log.info("=" * 70)
    log.info("NOS OFS PREP STAGE")
    log.info("=" * 70)

    config_path = args.config or get_config_path()
    if not config_path:
        log.error("No configuration file found. Set OFS_CONFIG or use --config")
        return 1

    log.info(f"Loading config: {config_path}")
    config = StofsConfig.from_yaml(str(config_path))

    # Override from environment
    config.PDY = os.environ.get('PDY', config.PDY)
    config.cyc = int(os.environ.get('cyc', config.cyc))
    config.DATA = os.environ.get('DATA', config.DATA)
    config.COMOUT = os.environ.get('COMOUT', config.COMOUT)
    config.COMINgfs = os.environ.get('COMINgfs', config.COMINgfs)
    config.COMINhrrr = os.environ.get('COMINhrrr', config.COMINhrrr)
    config.COMINnwm = os.environ.get('COMINnwm', config.COMINnwm)
    config.COMINrtofs = os.environ.get('COMINrtofs', config.COMINrtofs)

    log.info(f"OFS: {config.RUN}, PDY: {config.PDY}, cyc: {config.cyc:02d}")

    work_dir = Path(config.DATA or os.environ.get('DATA', '/tmp/nos_ofs_work'))
    work_dir.mkdir(parents=True, exist_ok=True)

    runner = LegacyScriptRunner(config)

    if args.step:
        step_methods = {
            'param_nml': runner.create_param_nml,
            'bctides': runner.create_bctides_in,
            'river': runner.create_river_forcing,
            'gfs': runner.create_gfs_forcing,
            'hrrr': runner.create_hrrr_forcing,
            'st_lawrence': runner.create_st_lawrence_forcing,
            'obc': runner.create_obc_forcing,
        }
        if args.step in step_methods:
            success = step_methods[args.step](work_dir)
            return 0 if success else 1
        else:
            log.error(f"Unknown step: {args.step}")
            return 1
    else:
        results = runner.run_full_preprocessing(work_dir)
        failed = sum(1 for s in results.values() if s is False)
        return 1 if failed > 0 else 0


def cmd_forcing(args):
    """Run specific forcing generation."""
    from .models.legacy_runner import LegacyScriptRunner
    from .models.schism_config import StofsConfig

    log.info(f"Generating {args.type.upper()} forcing")

    config_path = args.config or get_config_path()
    if not config_path:
        log.error("No configuration file found")
        return 1

    config = StofsConfig.from_yaml(str(config_path))
    config.PDY = os.environ.get('PDY', config.PDY)
    config.cyc = int(os.environ.get('cyc', config.cyc))

    work_dir = Path(os.environ.get('DATA', '/tmp/nos_ofs_work'))
    work_dir.mkdir(parents=True, exist_ok=True)

    runner = LegacyScriptRunner(config)

    forcing_methods = {
        'gfs': runner.create_gfs_forcing,
        'hrrr': runner.create_hrrr_forcing,
        'river': runner.create_river_forcing,
        'nwm': runner.create_river_forcing,
        'obc': runner.create_obc_forcing,
        'tides': runner.create_tidal_forcing,
        'bctides': runner.create_bctides_in,
        'st_lawrence': runner.create_st_lawrence_forcing,
    }

    if args.type not in forcing_methods:
        log.error(f"Unknown forcing type: {args.type}")
        return 1

    success = forcing_methods[args.type](work_dir)
    return 0 if success else 1


def cmd_export_env(args):
    """Export YAML config as shell environment variables."""
    from .utils.yaml_to_env import export_for_shell

    config_path = args.config or get_config_path()
    if not config_path:
        log.error("No configuration file found")
        return 1

    try:
        output = export_for_shell(str(config_path), framework=args.framework or 'auto')
        print(output)
        return 0
    except Exception as e:
        log.error(f"Failed to export config: {e}")
        return 1


def cmd_list(args):
    """List available OFS systems."""
    from .registry import OFSRegistry

    print("Available OFS Systems:")
    print("-" * 40)
    for ofs, model_type in sorted(OFSRegistry.OFS_MODEL_TYPES.items()):
        print(f"  {ofs:20s} ({model_type.value})")
    return 0


def cmd_stages(args):
    """List available workflow stages."""
    print("Available Workflow Stages:")
    print("-" * 60)
    print()
    print("STOFS Framework (stofs_3d_atl, stofs_3d_pac):")
    print("  prep_nowcast       Prepare all forcing data")
    print("  now_forecast       Run combined nowcast + forecast simulation")
    print("  post_1             Post-processing part 1 (2D fields, stations)")
    print("  post_2             Post-processing part 2 (3D fields, graphics)")
    print("  temp_salt_restart  Update T/S restart from RTOFS")
    print()
    print("COMF Framework (cbofs, dbofs, leofs, etc.):")
    print("  prep               Prepare all forcing data")
    print("  nowcast_forecast   Run combined nowcast + forecast simulation")
    print("  post               Post-processing")
    print()
    print("Note: Stage names are normalized automatically between frameworks.")
    return 0


def cmd_run(args):
    """Run a workflow stage for an OFS system."""
    from .registry import OFSRegistry
    from .models.workflow import SchismModel
    from .models.schism_config import StofsConfig

    log.info("=" * 70)
    log.info(f"NOS OFS RUN: {args.ofs} - {args.stage}")
    log.info("=" * 70)

    # Validate OFS system
    ofs_name = args.ofs.lower()
    if ofs_name not in OFSRegistry.OFS_MODEL_TYPES:
        log.error(f"Unknown OFS system: {args.ofs}")
        log.error(f"Use 'nos-ofs list' to see available systems")
        return 1

    model_type = OFSRegistry.OFS_MODEL_TYPES[ofs_name]

    # Currently only SCHISM is implemented
    if model_type.value != "schism":
        log.error(f"Model type '{model_type.value}' not yet implemented")
        log.error("Currently only SCHISM-based systems are supported:")
        log.error("  stofs_3d_atl, stofs_3d_pac, secofs, creofs")
        return 1

    # Find config file
    config_path = args.config
    if not config_path:
        # Search for config in standard locations
        search_paths = [
            Path(os.environ.get('HOMEstofs', '')) / 'parm' / 'systems' / f'{ofs_name}.yaml',
            Path(os.environ.get('HOMEnos', '')) / 'parm' / 'systems' / f'{ofs_name}.yaml',
            Path(__file__).parent.parent.parent.parent / 'parm' / 'systems' / f'{ofs_name}.yaml',
        ]
        for path in search_paths:
            if path.exists():
                config_path = str(path)
                break

    if not config_path or not Path(config_path).exists():
        log.error(f"Configuration file not found for {ofs_name}")
        log.error("Searched in: HOMEstofs/parm/systems, HOMEnos/parm/systems")
        log.error("Use --config to specify the path explicitly")
        return 1

    log.info(f"Config: {config_path}")

    # Load configuration
    try:
        config = StofsConfig.from_yaml(config_path)
    except Exception as e:
        log.error(f"Failed to load config: {e}")
        return 1

    # Override from command line arguments
    if args.pdy:
        config.PDY = args.pdy
        os.environ['PDY'] = args.pdy
    if args.cyc is not None:
        config.cyc = int(args.cyc)
        os.environ['cyc'] = str(args.cyc).zfill(2)

    # Override from environment (environment takes precedence)
    config.PDY = os.environ.get('PDY', config.PDY)
    config.cyc = int(os.environ.get('cyc', config.cyc))

    # Set up directories
    if args.data:
        config.DATA = args.data
        os.environ['DATA'] = args.data
    else:
        config.DATA = os.environ.get('DATA', config.DATA or f'/tmp/nos_ofs/{ofs_name}')

    if args.comout:
        config.COMOUT = args.comout
        os.environ['COMOUT'] = args.comout
    else:
        config.COMOUT = os.environ.get('COMOUT', config.COMOUT or f'/tmp/nos_ofs/com/{ofs_name}')

    # Ensure directories exist
    Path(config.DATA).mkdir(parents=True, exist_ok=True)
    Path(config.COMOUT).mkdir(parents=True, exist_ok=True)

    log.info(f"OFS: {ofs_name}, PDY: {config.PDY}, cyc: {config.cyc:02d}")
    log.info(f"DATA: {config.DATA}")
    log.info(f"COMOUT: {config.COMOUT}")

    # Set execution mode
    exec_mode = args.mode or os.environ.get('STOFS_EXEC_MODE', 'native')

    # Create workflow and run stage
    try:
        workflow = SchismModel(config, exec_mode=exec_mode)
        workflow.run_stage(args.stage)
        log.info(f"Stage '{args.stage}' completed successfully")
        return 0
    except ValueError as e:
        log.error(f"Invalid stage: {e}")
        log.error("Use 'nos-ofs stages' to see available stages")
        return 1
    except Exception as e:
        log.error(f"Stage execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='NOS OFS Workflow CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nos-ofs run stofs_3d_atl prep_nowcast --pdy 20250504 --cyc 12
  nos-ofs run stofs_3d_atl now_forecast --pdy 20250504 --cyc 12
  nos-ofs run secofs prep --pdy 20250504 --cyc 06
  nos-ofs list
  nos-ofs stages
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # run command - primary way to execute workflow stages
    run_parser = subparsers.add_parser(
        'run',
        help='Run a workflow stage for an OFS system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nos-ofs run stofs_3d_atl prep_nowcast --pdy 20250504 --cyc 12
  nos-ofs run stofs_3d_atl now_forecast
  nos-ofs run stofs_3d_atl post_1
  nos-ofs run secofs prep --config /path/to/secofs.yaml
        """
    )
    run_parser.add_argument('ofs', help='OFS system name (e.g., stofs_3d_atl, cbofs)')
    run_parser.add_argument('stage', help='Workflow stage (e.g., prep_nowcast, now_forecast, post_1)')
    run_parser.add_argument('--config', '-c', help='Path to YAML config file')
    run_parser.add_argument('--pdy', help='Processing date (YYYYMMDD)')
    run_parser.add_argument('--cyc', type=int, help='Cycle hour (0, 6, 12, 18)')
    run_parser.add_argument('--data', help='Working directory (DATA)')
    run_parser.add_argument('--comout', help='Output directory (COMOUT)')
    run_parser.add_argument('--mode', choices=['legacy', 'native', 'python'],
                           help='Execution mode (default: native)')
    run_parser.set_defaults(func=cmd_run)

    # stages command - list available stages
    stages_parser = subparsers.add_parser('stages', help='List available workflow stages')
    stages_parser.set_defaults(func=cmd_stages)

    # prep command (legacy - kept for backward compatibility)
    prep_parser = subparsers.add_parser('prep', help='Run preprocessing stage (legacy)')
    prep_parser.add_argument('--config', '-c', help='Path to YAML config file')
    prep_parser.add_argument('--step', help='Run specific step only')
    prep_parser.set_defaults(func=cmd_prep)

    # forcing command
    forcing_parser = subparsers.add_parser('forcing', help='Generate specific forcing')
    forcing_parser.add_argument('type', help='Forcing type (gfs, hrrr, river, obc, tides)')
    forcing_parser.add_argument('--config', '-c', help='Path to YAML config file')
    forcing_parser.set_defaults(func=cmd_forcing)

    # export-env command
    export_parser = subparsers.add_parser('export-env', help='Export config as shell environment')
    export_parser.add_argument('--config', '-c', help='Path to YAML config file')
    export_parser.add_argument('--framework', '-f', choices=['stofs', 'comf', 'auto'], default='auto')
    export_parser.set_defaults(func=cmd_export_env)

    # list command
    list_parser = subparsers.add_parser('list', help='List available OFS systems')
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
