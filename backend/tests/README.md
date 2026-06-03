# tests/

pytest test suite. Mirrors the source folder structure.
Target coverage: ≥ 85% (enforced by CI).

## Structure
```
tests/
├── unit/         # Fast tests — all external calls mocked
└── integration/  # Real API calls — run with: pytest -m integration
```

## Running tests
```bash
pytest                        # unit tests only (default)
pytest -m integration         # integration tests (needs .env)
pytest --cov --cov-report=html  # with HTML coverage report
```
