"""Post-product framework: registry-driven post-stage deliverables."""
from .base import PostProduct, ProductContext, ProductResult
from .outputs_manifest import write_outputs_manifest
from .registry import (
    DEFAULT_PRODUCTS,
    available_products,
    get_product,
    register,
    resolve_archive_fields,
    resolve_product_names,
)

__all__ = [
    "DEFAULT_PRODUCTS",
    "PostProduct",
    "ProductContext",
    "ProductResult",
    "available_products",
    "get_product",
    "register",
    "resolve_archive_fields",
    "resolve_product_names",
    "write_outputs_manifest",
]
