# backend/tests/unit/_chroma_test_support.py
"""
Shared ChromaDB EphemeralClient test infrastructure, factored out of
test_chroma_client.py / test_documents_router.py / test_documents_service.py
/ test_api_integration_flow.py (Section C audit finding, unit 9:
`pytest backend/tests/unit/` -- the full suite, the command "keep pytest
green" and CI both actually run -- crashed at COLLECTION time, before a
single test executed).

Two compounding root causes, both fixed here:

1. chromadb's EphemeralClient uses SharedSystemClient, a process-wide
   singleton keyed on the identifier "ephemeral". The FIRST
   chromadb.EphemeralClient(settings=...) call in the whole pytest
   process wins that slot; any subsequent call whose Settings object
   compares unequal to the stored one raises:
       ValueError: An instance of Chroma already exists for ephemeral
                   with different settings
   Before this module existed, all four test files above independently
   constructed their own module-level `_TEST_CHROMA_SETTINGS` /
   `_SHARED_RAW_CLIENT` at import time. Running any ONE of those files
   alone worked fine (only one EphemeralClient() call ever happened in
   that process); `pytest backend/tests/unit/` collects several of them
   into the same process and crashed at whichever file's call ran
   second, aborting collection for the ENTIRE suite -- not just those
   four files -- with zero tests run anywhere.

2. Even after consolidating to one shared construction, two files still
   collided, because chromadb.config.Settings is a pydantic Settings
   class whose `environment` field reads the process's `ENVIRONMENT` OS
   environment variable -- the exact same variable name this repo's own
   test files set via `os.environ.setdefault("ENVIRONMENT", "test")`
   (backend.config.Settings's own, unrelated "test vs. production"
   flag). Two `_ChromaSettings(is_persistent=False, allow_reset=True,
   anonymized_telemetry=False)` calls that never explicitly pin
   `environment=` therefore do NOT reliably construct equal objects --
   whichever one runs before some other test file's
   `os.environ.setdefault("ENVIRONMENT", "test")` call gets chromadb's
   own hardcoded default ("development"); whichever runs after gets
   "test". Pytest's file collection order (alphabetical) made this
   order-dependent and, worse, collection-order-dependent -- selecting a
   different subset of test files to run could change whether the two
   constructions happened to agree. Fixed by pinning `environment="test"`
   explicitly below, so this field no longer depends on ambient process
   environment state (or on which other test files have been imported
   yet) at all.

Fix: exactly one EphemeralClient() call, ever, for the whole test
process, with every settings field pinned to an explicit literal, made
here once at import time and imported by every file that needs it.
"""

from typing import Any

import chromadb
from chromadb.config import Settings as _ChromaSettings


class MockEmbeddingFunction:
    """Fake embedding function satisfying ChromaDB's __call__ signature
    check (odict_keys(['self', 'input']), validated at collection-creation
    time), without loading any real sentence-transformer model."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [[0.1] * 384 for _ in input]


TEST_CHROMA_SETTINGS = _ChromaSettings(
    environment="test",
    is_persistent=False,
    allow_reset=True,
    anonymized_telemetry=False,
)

# The one and only chromadb.EphemeralClient() call in the whole test
# process -- see this module's own docstring for why a second call
# anywhere else would crash pytest collection for the entire suite.
SHARED_RAW_CLIENT: Any = chromadb.EphemeralClient(settings=TEST_CHROMA_SETTINGS)
