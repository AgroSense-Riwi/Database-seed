"""Global PRNG seeding (seed_data_reproducibility_strategy.md §2.1)."""

from __future__ import annotations

import logging
import os
import random

from faker import Faker

try:  # numpy is optional: not a direct dependency of the seed.
    import numpy as _np
except ImportError:  # pragma: no cover - depends on the environment
    _np = None

logger = logging.getLogger("agrosense.seed")


def set_reproducible_state(seed: int) -> None:
    """Seed every global PRNG used by the generators (CT-06 / E-03).

    Seeds ``random``, ``numpy.random`` (only when numpy is installed) and Faker.
    """
    logger.debug("Fijando estado reproducible con semilla=%d", seed)
    random.seed(seed)
    if _np is not None:
        _np.random.seed(seed)
    Faker.seed(seed)
    # Prescribed by the reproducibility strategy doc. NOTE: hash randomisation is
    # fixed at interpreter start-up, so this only affects *subprocesses* spawned
    # after this call; the current process keeps its own PYTHONHASHSEED. The
    # generators do not depend on hash() ordering (UUIDv5 + seeded Random).
    os.environ["PYTHONHASHSEED"] = str(seed)
