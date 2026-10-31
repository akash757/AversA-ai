---
description: Mandatory development rules for testing, logging, pre-commit verification, documentation, and frontend tracking
trigger: always_on
---

# Development Rules

## 1. Explicit Approval & Pre-Commit Test Verification
- **User Approval Required**: NEVER commit or push code autonomously. Always present the changes and ask the user for explicit approval before running `git commit` or `git push`.
- All test cases MUST pass before any code is committed.
- Never commit code that breaks any test suite or reduces test coverage.
- The pre-commit hook automatically verifies all tests; never bypass `--no-verify`.

## 2. Compulsory Logging
- For every task, feature, service, middleware, endpoint, or background job in `backend` and in `ai`, structured and contextual logging is **MANDATORY**:
  - **Backend**: Use `logger.info`, `logger.warn`, `logger.debug`, `logger.critical` from `src/utils/logger.ts`.
  - **AI Service**: Use the application logger with appropriate levels (`INFO`, `WARNING`, `ERROR`, `DEBUG`).
  - Always log key lifecycle events, entry/exit points, database transaction boundaries, external API calls, and failure scenarios.
  - **Privacy Rule**: Never log raw dialog text, client brief contents, passwords, or personal credentials. Log IDs, counts, format codes, and status codes.

## 3. Compulsory Test Cases
- Whenever any task or feature is built or modified in `backend` or in `ai`, formal test cases MUST be written immediately without fail:
  - **Backend**: Add unit and integration tests inside the dedicated `tests/` directory (`tests/**/*.test.ts`) using Jest.
  - **AI Service**: Add unit and integration tests inside `tests/` using Pytest.
  - Maintain high test coverage (>90%) across branches, statements, and functions.
  - Include positive cases, validation rejections, error handling, and edge cases.

## 4. Zero Standalone Scripts for Testing
- NEVER create a `scripts/` folder or standalone script files (e.g., `test*.ts`, `check*.js`, `validate*.py`) for testing or validation.
- All verification must be written as formal test cases in the `tests/` folder and executed through the test runner (`npm test` or `pytest`).

## 5. Compulsory Swagger / OpenAPI Documentation Updates
- Whenever any new API route or endpoint is created, modified, or removed in `backend`:
  - **Immediate Swagger Update**: Always update `backend/src/config/swagger.ts` in the same task before completing work.
  - **Complete Specification**:
    - Mount the path and HTTP method under `swaggerDocument.paths`.
    - Document appropriate `tags`, `summary`, `description`, and `security: [{ BearerAuth: [] }]` (if protected).
    - Document all `parameters` (path, query) and `requestBody` schemas.
    - Document expected response codes (`200`, `201`, `400`, `401`, `403`, `404`, `409`).
    - Add all new request body or entity schemas to `components.schemas`.
  - **Verification**: Verify that `tsc --noEmit` and `npm test tests/app.test.ts` pass so `/docs.json` and Swagger UI at `/docs` reflect the new API without errors.

## 6. Continuous Architecture Documentation Synchronization
- **Mandatory Documentation Update**: Whenever any feature, service, pipeline, model, route, security rule, or configuration is added, modified, or refactored:
  - Immediately update the comprehensive architecture document `AversA_Full_Architecture_and_DataFlow_Documentation.md` in:
    1. The central artifact directory (`<appDataDir>/brain/<conversation-id>/AversA_Full_Architecture_and_DataFlow_Documentation.md`).
    2. The dedicated backend documentation folder (`backend/docs/AversA_Full_Architecture_and_DataFlow_Documentation.md`).
  - Keep data flow diagrams (Mermaid), system boundaries, quality gate tables, and endpoint specifications fully synchronized with actual codebase state.

## 7. Frontend Pending Implementation Tracking
- **Frontend Tracking Files (`implementation_pending.md`)**: Whenever an implementation in `backend` or `ai-backend` introduces or updates an API, data contract, WebSocket event, or workflow that requires corresponding frontend UI / client implementation:
  - Immediately update (or create) `implementation_pending.md` in:
    1. The workspace root (`c:\Users\Reyna\Desktop\Akash\implementation_pending.md`).
    2. The dedicated frontend docs folder (`frontend/docs/implementation_pending.md`).
  - Document all concrete steps, components, API client hooks, data shapes, state requirements, and UX flows that need to be implemented in `frontend`.
  - Check off items as they are implemented in the frontend.

