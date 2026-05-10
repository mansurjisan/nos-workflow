"""Per-stage entry points for the workflow driver.

Each module in this package exposes a single ``run(descriptor, env)``
function returning an integer exit code (0 = success). The CLI
dispatches via :func:`nos_workflow.registry.lookup` and then calls the
matching ``stages.<stage>.run`` function — no class hierarchy, no
plumbing class needed.
"""
