# Coding Standards

## Branch naming
`feat/<area>-<description>` · `fix/<area>-<description>` · `chore/<description>`
`docs/<description>` · `test/<area>-<description>` · `ci/<description>`

## Commit format
`type(scope): short description` — max 72 characters, imperative mood

Types: `feat` · `fix` · `docs` · `test` · `chore` · `perf` · `refactor` · `ci`

## File naming
| Type | Convention | Example |
|------|-----------|---------|
| Python source | snake_case | `fundamental_analyst.py` |
| Python tests | `test_<module>.py` | `test_fundamental_analyst.py` |
| React components | PascalCase | `AgentProgressCard.tsx` |
| React hooks/utils | camelCase | `useWebSocket.ts` |
| Folders | kebab-case | `agent-progress/` |
| Constants | SCREAMING_SNAKE_CASE | `MAX_DEBATE_ROUNDS = 2` |

## Python tooling
- **Formatter:** black (line length 88)
- **Imports:** isort with black profile
- **Linter:** flake8 + flake8-bugbear
- **Types:** mypy strict mode
- **Tests:** pytest, target ≥ 85% coverage
