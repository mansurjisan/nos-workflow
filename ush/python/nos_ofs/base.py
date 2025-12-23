"""
Base classes for forcing data processors.

This module provides the abstract base class and result dataclass
for all forcing data processors (GFS, HRRR, NAM, NWM, RTOFS, Tidal, etc.)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class ForcingResult:
    """Result from forcing data processing."""

    success: bool
    source: str
    output_files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


class ForcingProcessor(ABC):
    """
    Abstract base class for forcing data processors.

    All forcing processors (GFS, HRRR, NAM, NWM, RTOFS, etc.) inherit
    from this class and implement the process() method.
    """

    def __init__(
        self,
        config: Any,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
    ):
        """
        Initialize forcing processor.

        Args:
            config: Configuration instance (OFSConfig or legacy StofsConfig)
            input_path: Path to input data (COMIN)
            output_path: Path for output files (DATA)
            variables: List of variables to process
        """
        self.config = config
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.variables = variables or []

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the name of this forcing source."""
        pass

    @abstractmethod
    def process(self) -> ForcingResult:
        """
        Process forcing data.

        Returns:
            ForcingResult with status and output files
        """
        pass

    def validate_input(self) -> bool:
        """Validate that input data exists."""
        if not self.input_path.exists():
            log.warning(f"{self.source_name} input path not found: {self.input_path}")
            return False
        return True

    def create_output_dir(self) -> None:
        """Create output directory if it doesn't exist."""
        self.output_path.mkdir(parents=True, exist_ok=True)
