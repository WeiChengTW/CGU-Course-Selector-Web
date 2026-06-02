# MOOCS Session Login Design

## Goal

Add MOOCS/校務系統帳密登入 so different students can use the web app with their own course data. The system must not save passwords. After login, it synchronizes the student's MOOCS course list into a session-specific temporary data directory, and all course/status pages read from that session instead of the shared CSV.

## Non-goals

- No long-term account system for this app.
- No password persistence.
- No database migration for this demo version.
- No background job queue unless the synchronous login flow proves too slow for demo use.

## User flow

1. Unauthenticated users visiting course-dependent pages are redirected to `/login`.
2. The login page asks for MOOCS account and password.
3. On submit, the backend runs the existing MOOCS scraper with the submitted credentials.
4. The scraper returns the student's course list.
5. The backend writes session-local files:
   - `data/sessions/<session_id>/moocs_courses.txt`
   - `data/sessions/<session_id>/taken_courses.csv`
6. The password is discarded after the request finishes.
7. The browser receives an HttpOnly session cookie and is redirected to `/courses`.
8. Logout clears the cookie and deletes the session directory.

## Architecture

### Routes

Add `app/routes/auth.py`:

- `GET /login`: render login page.
- `POST /login`: validate form fields, run MOOCS sync, create session cookie, redirect on success.
- `POST /logout`: clear cookie and remove session temporary data.

Update `app/main.py` to include the auth router.

### Services

Add `app/services/session_service.py`:

- Generate cryptographically random session ids.
- Resolve the current session directory under `data/sessions/<session_id>`.
- Create and delete session directories.
- Read session id from request cookie.
- Provide a small helper that requires a valid session for protected routes.

Add `app/services/moocs_sync_service.py`:

- Import `scrape_moocs_courses` from `Graduation-Credit-Calculator/lib/scraper.py`.
- Import `write_details` from `Graduation-Credit-Calculator/lib/catalog.py`.
- Run the scraper with the submitted username/password.
- Save raw MOOCS list and generated course CSV inside the session directory.
- Return a summary such as course count and output path.

### Templates

Add `app/templates/login.html`:

- MOOCS account input.
- MOOCS password input.
- Submit button.
- Loading message: `正在登入 MOOCS 並同步課程，第一次需要等待`.
- Error message area for failed login/sync.

Update `app/templates/base.html`:

- Show login/logout state.
- Add logout form/button when a session exists.

## Data flow changes

Current code reads a shared file at `data/taken_courses.csv`. That must change for course-dependent APIs.

Update route handlers so each request resolves the current session data directory and constructs services from that directory:

- `/courses/data` reads `data/sessions/<session_id>/taken_courses.csv`.
- `/catalog/search` still queries the public catalog API, but course status marking uses the current session's `CourseService`.
- `/catalog/taken-courses` reads the current session's course summary.
- `/graduation/data` should use session-local graduation report if available. If not available, it can return the existing fallback message.

The global `course_service = CourseService(DATA_DIR)` in route modules should be removed for session-dependent data because it would leak one shared data source across users.

## Security and privacy

- Passwords are never written to disk.
- Passwords are never logged.
- Session cookie is HttpOnly.
- Session id is generated with Python `secrets`.
- Session data is scoped to a random id and deleted on logout.
- Error messages shown to users must not include passwords or raw exception details that might contain sensitive values.

## Error handling

Login can fail because:

- Account/password is incorrect.
- MOOCS page structure changed.
- MOOCS requires captcha or manual verification.
- Playwright/browser dependency is missing.
- Catalog API lookup fails for some courses.

The login page should show a short friendly message. Detailed diagnostics can be printed only if they do not contain credentials.

## Testing and verification

Manual verification for demo:

1. Visit `/courses` while logged out; confirm redirect or login prompt.
2. Login with valid MOOCS credentials; confirm courses appear.
3. Open another browser/incognito session and login as another student; confirm data differs.
4. Confirm `/catalog` marks already-taken courses according to the logged-in student's data.
5. Logout; confirm session cookie is cleared and session data is deleted.
6. Confirm no password appears in generated files or logs.

## Tradeoffs

This design favors safety and demo reliability over convenience. Users must log in again for a new session, and first login may take a while because it runs Playwright and catalog lookups synchronously. That is acceptable for the current demo scope and avoids storing school credentials.