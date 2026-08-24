"""Built-in block handlers. Importing this package registers them all.

Each module registers its block types into the default ``REGISTRY`` at import,
so ``import src.spells`` (which imports this package) makes the catalogue ready.
"""

from . import rolls  # noqa: F401
from . import damage  # noqa: F401
from . import healing  # noqa: F401
from . import state  # noqa: F401
