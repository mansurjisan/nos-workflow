"""Post-product framework: context, result, and product base class.

A *product* is one deliverable of the post stage (station NetCDF, field
NetCDF, SHEF text, ...). Products are registered in
``nos_workflow.post.registry`` and selected per system via the YAML
``post.products`` list (or the ``NOS_POST_PRODUCTS`` env override); the
post stage driver executes them in order with per-product isolation, so
one failing product warns and the rest still run.

This module has no imports from ``nos_workflow.stages`` -- concrete
products may live there (P1) or in nos-utils (later phases) and import
freely from here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, List, Mapping, Optional

if TYPE_CHECKING:
    from ..registry import OFSDescriptor  # noqa: F401


@dataclass(frozen=True)
class ProductContext:
    """Resolved, validated inputs shared by every product of one post run.

    Built once by the stage driver after the fatal checks (required env,
    combine script, station.in) pass; products must not re-read
    ``os.environ`` for anything captured here.
    """

    descriptor: "OFSDescriptor"
    shell_env: Mapping[str, str]
    homenos: Path
    fixofs: Path
    comout: Path
    data: Path
    pdy: str
    cyc: str
    cycle: str
    run_name: str
    prefix_nos: str
    nc_hour: str
    sta_in: Path
    combine_script: Path
    pgmout: str


@dataclass
class ProductResult:
    """Outcome of one product, recorded in the outputs manifest."""

    name: str
    status: str  # "ok" | "skipped" | "failed"
    outputs: List[str] = field(default_factory=list)
    detail: Optional[str] = None
    duration_s: float = 0.0


class PostProduct(ABC):
    """One post-stage deliverable.

    Subclasses set ``name`` (the registry key / YAML token) and implement
    :meth:`produce`. ``produce`` should return a :class:`ProductResult`
    and keep its own failures non-fatal where the legacy shell did
    (warn-and-continue); raising ``StageFailedError`` remains the escape
    hatch for genuinely fatal conditions.
    """

    name: ClassVar[str] = ""

    @abstractmethod
    def produce(self, ctx: ProductContext) -> ProductResult:
        """Generate the product's outputs for this cycle."""


__all__ = ["PostProduct", "ProductContext", "ProductResult"]
