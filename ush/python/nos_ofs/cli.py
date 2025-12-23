#!/usr/bin/env python3
"""
NOS OFS Command Line Interface

This module provides CLI entry points for the nos_ofs workflow package.
It bridges the gap between legacy shell scripts and Python-based processing.

Usage from shell scripts:
    # Run full prep stage with YAML config
    python3 -m nos_ofs.cli prep --config $OFS_CONFIG --ofs stofs_3d_atl

    # Run specific forcing
    python3 -m nos_ofs.cli forcing gfs --config $OFS_CONFIG

    # Export YAML config to shell environment
    python3 -m nos_ofs.cli export-env --config $OFS_CONFIG --framework stofs
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


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='NOS OFS Workflow CLI')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # prep command
    prep_parser = subparsers.add_parser('prep', help='Run preprocessing stage')
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
