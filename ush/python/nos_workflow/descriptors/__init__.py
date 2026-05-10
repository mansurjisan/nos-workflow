"""OFS descriptor modules.

Each module in this package defines a single ``OFSDescriptor`` and calls
``register(...)`` at import time. The registration side-effect is
triggered by :func:`nos_workflow.registry.load_all_descriptors`, not by
this ``__init__`` — that keeps ``nos_uw list`` from paying for imports
on packages it doesn't need, and keeps tests free to load only what
they exercise.
"""
