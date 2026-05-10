"""Allow `python -m nos_workflow ...` as a CLI entry point.

J-jobs that don't have ``bin/nos_uw`` on PATH can call
``python -m nos_workflow run prep --ofs $OFS`` and get the same result
as the ``nos_uw`` console script.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
