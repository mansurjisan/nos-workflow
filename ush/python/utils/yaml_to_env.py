#!/usr/bin/env python3
"""Legacy YAML-to-shell resolver — thin re-export of the canonical module.

The single source of truth is ``nos_workflow/utils/yaml_to_env.py``. This file
exists only because ``ush/nos_config.sh`` locates the resolver by THIS path
(``ush/python/utils/yaml_to_env.py``) for shell env exports in the operational
J-jobs. Keeping it a thin re-export — rather than a maintained second copy —
permanently removes the dual-resolver keep-in-sync hazard: any feature added to
the canonical resolver is reflected here automatically, byte-for-byte.

When ``nos_config.sh`` runs this file directly, Python puts THIS file's
directory (``ush/python/utils``) on ``sys.path[0]`` — not its parent
``ush/python`` — so ``nos_workflow`` is not importable by default. We prepend
``ush/python`` to make the import resolve, then delegate everything.
"""
from __future__ import annotations

import sys
from pathlib import Path

_USH_PYTHON = str(Path(__file__).resolve().parents[1])
if _USH_PYTHON not in sys.path:
    sys.path.insert(0, _USH_PYTHON)

from nos_workflow.utils.yaml_to_env import (  # noqa: E402,F401
    __all__,
    __version__,
    compute_derived_values,
    deep_merge,
    export_env,
    export_for_shell,
    export_shell_mappings,
    filter_by_section,
    format_ctl_file,
    format_json,
    format_shell_exports,
    get_nested_value,
    get_runtime_from_env,
    get_standard_exports,
    load_yaml_with_inheritance,
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
