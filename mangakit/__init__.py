"""mangakit: shared production tools for code-first manga (page source -> SVG -> PNG)."""
__version__ = "0.1.0"

from .geometry import Affine, Path, line_y, similarity, similarity2  # noqa: E402
from .project import MangakitError, Project  # noqa: E402

__all__ = ["Affine", "Path", "line_y", "similarity", "similarity2", "Project", "MangakitError", "__version__"]
