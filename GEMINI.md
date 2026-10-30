# Antigravity AI Service Guidelines

## Mandatory Pre-Commit & Git Approval Rule
- **Explicit User Approval Required**: NEVER commit or push code autonomously. Always present the changes and ask the user for explicit approval before running `git commit` or `git push`.
- **Pre-Commit Tests**: When approved, all test cases must pass 100% (`pytest`).

## Mandatory Task Rules
1. **Compulsory Logging**:
   - Add structured logging at key milestones, FastAPI endpoints, prompt generation steps, and upstream LLM calls.
   - Never log raw brief texts or sensitive credentials.
2. **Compulsory Test Cases**:
   - Write comprehensive Pytest test cases in `tests/` for every feature, endpoint, or utility created or modified.
3. **No Standalone Testing Scripts**:
   - Never create ad-hoc test scripts outside `tests/`. All tests belong in `tests/test_*.py`.

