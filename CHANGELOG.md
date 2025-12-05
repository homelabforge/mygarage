# Changelog

All notable changes to MyGarage will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.14.2] - 2025-12-04

### Security
- **[CRITICAL] Fixed Server-Side Request Forgery (SSRF) vulnerabilities (CWE-918)**
  - Created comprehensive URL validation utility (`backend/app/utils/url_validation.py`)
  - Fixed SSRF in OIDC service (`backend/app/services/oidc.py:100`) - prevents access to internal services
  - Fixed SSRF in NHTSA service (`backend/app/services/nhtsa.py:48`) - validates API URLs
  - Protection includes: blocks private IPs (RFC 1918, RFC 4193), loopback, link-local, AWS metadata endpoint
  - DNS rebinding protection and domain allowlisting support
  - All HTTP requests to external services now validated

- **[HIGH] Fixed Log Injection vulnerabilities (CWE-117) - 200+ instances across 44 files**
  - Converted all f-string logging to parameterized logging format
  - Prevents log forgery attacks via newline injection
  - Created automated remediation tool (`fix_log_injection.py`)
  - Affected files: all routes/, services/, utils/, migrations/, and core modules

- **[HIGH] Fixed Secret Exposure in Logs**
  - Created `mask_secret()` function to safely log sensitive values
  - Fixed 4 instances of OIDC client secret exposure in logs
  - Secrets now show only first/last 4 chars (e.g., `oidc_****...****_abcd`)

- **[HIGH] Fixed Path Injection vulnerabilities (CWE-22)**
  - Added defense-in-depth path validation in photo deletion (`backend/app/routes/photos.py:250,259`)
  - Validates resolved paths are within PHOTO_DIR to prevent traversal attacks
  - Enhanced with `validate_path_within_base()` security checks

- **[MEDIUM] Fixed postMessage Origin Validation (CWE-20291)**
  - Added strict same-origin validation in service worker (`frontend/public/sw.js:147`)
  - Prevents XSS and message spoofing from unauthorized origins
  - Rejects messages with console warning for security monitoring

### Changed
- **Exception Handling** - Verified stack trace exposure properly handled
  - Production mode (default): Generic error messages only, no internal details
  - Debug mode: Detailed traces for development only
  - Error handlers in `backend/app/utils/error_handlers.py` provide secure responses

### Added
- **New Security Utilities**
  - `backend/app/utils/url_validation.py` - Comprehensive SSRF protection (447 lines)
  - `backend/app/exceptions.py` - Added `SSRFProtectionError` exception class
  - `fix_log_injection.py` - Automated log injection remediation script

### Fixed
- **Code Quality Improvements** - Resolved 101 CodeQL NOTE-level alerts
  - Removed 59 unused imports from 39 Python files (automated)
  - Added explanatory comments to 8 empty except blocks (optional dependency checks)
  - Renamed 9 unused local variables to `_` for intentionally unused values
  - Fixed useless comparison in frontend user count display
  - Documented 3 Pydantic validator false positives (require `cls` parameter)
  - Documented 3 pytest.skip false positives (raises exception, never returns None)

### Documentation
- **SECURITY.md** - Added comprehensive CodeQL Security Analysis section
  - Documented all 140 fixed vulnerabilities (2 CRITICAL, 119 HIGH, 1 MEDIUM)
  - Documented 17 false positives with justification
  - Listed 136 deferred code quality items (NOTE level)
  - Updated security changelog for v2.14.2
- **Cyclic Imports** - Documented 47 cyclic import alerts for future architectural refactoring
  - Saved to `/srv/raid0/docker/documents/history/mygarage/2025-12-04-cyclic-imports-deferred.txt`
  - Includes recommended fixes (TYPE_CHECKING, dependency injection, lazy imports)

### Technical Notes
- All security and code quality fixes are backward compatible
- No API changes or breaking changes
- Total files modified: 86 (47 security + 39 code quality)
- CodeQL analysis: 241/272 alerts resolved (140 security + 101 code quality)
- Remaining 47 alerts are cyclic imports (architectural issue, deferred to refactoring sprint)

## [2.14.1] - 2025-12-03

### Added
- **Single-Source-of-Truth Version Management**
  - Backend now reads version from `pyproject.toml` automatically at runtime
  - Added `get_version()` function using Python's built-in `tomllib` parser
  - Version bumps now only require updating 2 files instead of 3
  - Eliminates version drift between config.py and pyproject.toml
  - Updated Dockerfile to copy `pyproject.toml` into production image

### Changed
- **Zod v4 API Migration** - Updated all validation schemas to use Zod v4 API patterns
  - Removed deprecated `required_error` and `invalid_type_error` parameters from schemas
  - Simplified error messages using single `message` parameter
  - Updated z.enum `errorMap` syntax to new `message` format
  - Removed unnecessary `z.preprocess()` wrappers that were causing type inference issues
  - React Hook Form's zodResolver automatically handles empty string → undefined conversion

- **Form Type Safety Improvements**
  - Fixed defaultValues type mismatches across 15+ form components
  - Changed numeric field defaults from `.toString() || ''` to `?? undefined` pattern
  - Fixed boolean field defaults using `??` instead of `||` to preserve explicit false values
  - Improved type inference for all form schemas (now return proper types instead of `unknown`)

- **Test Infrastructure Updates**
  - Changed `global` to `globalThis` for Node.js/browser compatibility in test setup
  - Removed unused imports and variables across test files

### Fixed
- **TypeScript Compilation Errors** - Resolved 100+ TypeScript errors caused by Zod v4 API changes
  - Fixed all schema validation patterns to match Zod v4 requirements
  - Fixed form component type mismatches for numeric and boolean fields
  - Fixed null safety issues in title length checks and property access
  - Removed unused imports and watch variables flagged by TypeScript strict mode

### Dependencies
- **Frontend**: Updated jsdom from 25.0.1 to 27.2.0 (Dependabot security update)

### Technical Notes
- All changes are backward compatible - no validation rules or API contracts changed
- Build passes successfully with Vite
- All 28 unit tests passing
- 49 non-blocking TypeScript warnings remain (type inference cascades from resolver types)

## [2.14.0] - 2025-12-01

### Added
- **Multi-User Management System**
  - Database setting `multi_user_enabled` to control user creation (default: false)
  - Backend enforcement: blocks user creation when multi-user mode is disabled
  - Admin password reset endpoint (`PUT /auth/users/{id}/password`) for local auth users only
  - Multi-User Management card in Settings > System (admin-only, local auth only)
  - Toggle switch to enable/disable multi-user mode
  - User preview showing first 3 users with avatars
  - "Add User" button to create new accounts
  - "Manage All Users" button to access full user management interface
  - User Management modal with:
    - Searchable user table (by username, email, or full name)
    - Role badges (Admin/User)
    - Status badges (Active/Inactive)
    - Auth method badges (OIDC/Local)
    - Edit user details
    - Reset password (local users only)
    - Enable/disable user accounts
    - Delete users (cannot delete yourself)
  - Add/Edit User modal with:
    - Username field (disabled in edit mode)
    - Email field (required)
    - Full name field (optional)
    - Password fields with strength indicator
    - Password visibility toggles
    - Role selector (Admin/User)
    - Active status checkbox
    - OIDC user badge (when applicable)
  - Delete User modal with:
    - User information display
    - Data impact warnings (vehicles, service records, fuel records)
    - Type "DELETE" confirmation requirement
    - Admin badge warning for admin users
  - Security safeguards:
    - Last admin protection: cannot disable the only active admin
    - Last admin protection: cannot change role of the only active admin
    - Self-deletion prevention: users cannot delete their own account
    - Warning tooltips for disabled actions
    - Confirmation dialogs for destructive operations

### Changed
- Settings > System page now uses two-column CSS Grid layout:
  - Left column: System Configuration + Multi-User Management
  - Right column: Authentication Mode + Change Password

### Fixed
- Button styling consistency across multi-user management components:
  - Change Password button now uses correct theme (`bg-gray-700 border border-gray-600`)
  - Create/Update button in Add/Edit User modal now uses correct theme
  - All buttons now match the application's standard gray button style

## [2.13.0] - 2025-12-01

### Added
- **OIDC Username-Based Account Linking with Password Verification**
  - Prevents duplicate account creation (username1, username2, etc.) during OIDC login
  - When username matches but email differs, users are prompted to verify their password
  - New database table `oidc_pending_links` for temporary link tokens (migration 015)
  - New frontend page `/auth/link-account` for password verification
  - Security features:
    - Token expiration: 5 minutes (configurable via `oidc_link_token_expire_minutes`)
    - Max password attempts: 3 (configurable via `oidc_link_max_password_attempts`)
    - Rate limiting: 5 requests/minute on link endpoint
    - One-time use tokens (deleted after successful link)
    - Comprehensive audit logging (success and failure)
  - Edge case handling:
    - Token expiration with user-friendly error messages
    - Maximum attempt lockout
    - OIDC-only user detection (no password)
    - Conflict prevention (already linked to different provider)
    - Inactive user checks
  - Backward compatible with existing OIDC flows (email-based linking still works)
  - Files added:
    - `backend/app/exceptions.py` - PendingLinkRequiredException
    - `backend/app/models/oidc_pending_link.py` - Pending link model
    - `backend/app/migrations/015_add_oidc_pending_links.py` - Database migration
    - `frontend/src/pages/LinkAccount.tsx` - Password verification UI
  - Files modified:
    - `backend/app/services/settings_init.py` - Added 2 new settings
    - `backend/app/services/oidc.py` - Added 3 helper functions, modified user creation logic
    - `backend/app/routes/oidc.py` - Modified callback handler, added `/link-account` endpoint
    - `frontend/src/App.tsx` - Added route for link account page

## [2.13.0] - 2025-11-30

### Added
- **Code Quality Refactoring (Phase 2)**
  - Complete service layer architecture for business logic separation
    - `VehicleService` (226 lines) - Vehicle CRUD operations with integrated authorization
    - `ServiceRecordService` (366 lines) - Service record management with N+1 query optimization
    - `FuelRecordService` (486 lines) - Fuel tracking with MPG calculations and caching
    - `PhotoService` (179 lines) - Photo management and thumbnail generation
  - Photo management extracted to dedicated router (`/app/routes/photos.py`, 448 lines, 7 endpoints)
  - Average MPG calculation now cached (5-minute TTL) for performance
  - Legacy photo hydration moved to one-time migration script (removed from request hot path)
  - Database migration 014: `014_hydrate_legacy_photos.py` for one-time photo metadata population
- **Authentication Mode 'None' Implementation**
  - Support for running application without authentication in development environments
  - Frontend centralized auth_mode state in AuthContext (single API call to `/settings/public`)
  - Smart authentication dependencies check `auth_mode` setting before enforcing
  - `auth_mode='none'` allows guest access (user = None) with full permissions
  - Settings UI allows changing Authentication Mode to "None" with security warnings
  - Frontend ProtectedRoute respects `auth_mode` from context (no duplicate API calls)

### Changed
- **Massive Code Reduction and Organization (Phase 2)**
  - `vehicles.py`: 1,002 → 316 lines (69% reduction)
  - `service.py`: 404 → 185 lines (54% reduction)
  - `fuel.py`: 487 → 165 lines (66% reduction)
  - Total: 1,227 lines removed from route files (average 63% reduction)
  - Route handlers now focused purely on HTTP concerns, business logic in service layer
  - Removed redundant `_sanitize_filename` function (using centralized utils version with better validation)
  - Consolidated duplicate VIN decode endpoints with shared `_decode_vin_helper()` function
  - All photo endpoints maintain backward compatibility with authorization checks in place
- **Authentication Architecture Updates**
  - `require_auth()` now checks `auth_mode` setting: returns None when disabled, enforces when enabled
  - `get_current_admin_user()` checks `auth_mode` first: returns None when disabled (allows all access)
  - All helper functions accept `Optional[User]` for type safety with null checks
  - `get_vehicle_or_403()` and `check_vehicle_ownership()` handle None users (grant full access)
  - Vehicle/Service/Fuel service layers accept `Optional[User]`, show all data when user is None
  - Settings endpoints split: `/api/settings/public` (no auth) vs `/api/settings` (admin only)
  - All 100+ endpoints now work seamlessly with `auth_mode='none'`

### Fixed
- **Code Quality Improvements (Phase 3 - 71% reduction in linting issues)**
  - Fixed F821 (undefined name): Added missing `Document` import in [vehicle.py:187](backend/app/models/vehicle.py#L187)
  - Fixed E722 (bare except): Replaced with specific `ValueError` in [insurance.py:129](backend/app/services/document_parsers/insurance.py#L129)
  - Auto-fixed 128 actionable issues via ruff (unused imports, empty f-strings, boolean comparisons, unused variables)
  - Reduced total ruff issues from 181 → 53 (71% reduction)
  - Remaining 53 issues are intentional design patterns (documented in `pyproject.toml`)
    - E402 (46 issues): Imports after code for FastAPI initialization order and circular dependency resolution
    - F401 (7 issues): Unused imports in try/except blocks for optional dependency checks
  - Added comprehensive ruff configuration with per-file ignores
- **Authentication Flow Improvements**
  - Fixed CSRF token endpoint to work without authentication when `auth_mode='none'`
  - Fixed ProtectedRoute and Layout to use `/settings/public` instead of admin-only endpoint
  - Eliminated ERROR logs ("No credentials provided") on page load before authentication
  - CSRF endpoint now uses `optional_auth` dependency, returns `{"csrf_token": None}` when disabled
  - Frontend no longer makes duplicate API calls to check auth_mode (centralized in AuthContext)
  - Resolved infinite loop issue (3 components independently calling `/settings/public` → 200+ requests)
- **Frontend Validation Error Serialization**
  - Fixed `TypeError: Object of type ValueError is not JSON serializable` in error handlers
  - Validation errors now properly converted to JSON-serializable format before response
- **Auth Mode 'None' Backend Validation**
  - Removed overly restrictive validation blocking `auth_mode='none'` changes (kept warning logs only)
  - Fixed AttributeError crashes from None user references in authorization helpers
  - Fixed 500 errors when accessing endpoints with `auth_mode='none'` enabled
  - Settings page now accessible without authentication when auth is disabled

### Security
- **CRITICAL: Authentication & Authorization Hardening (Phase 1)**
  - All vehicle data endpoints now require authentication via `require_auth` dependency
  - Implemented per-vehicle authorization - users can only access their own vehicles
  - Added `user_id` column to vehicles table with foreign key to users (database migration 013)
  - Admin users retain access to all vehicles for support purposes
  - Production safeguard: `auth_mode='none'` blocked in production without explicit `MYGARAGE_ALLOW_AUTH_NONE=true` flag
  - Startup warning displayed when `auth_mode='none'` is active
  - Authentication dependencies: `require_auth()` (smart enforcement) vs `optional_auth()` (never enforces)
  - Authorization helpers: `get_vehicle_or_403()`, `check_vehicle_ownership()` with None user support
  - 24+ endpoints hardened: vehicles, service records, fuel records, photos, settings
  - Public settings endpoint (`/api/settings/public`) works without authentication for frontend initialization
  - Prevents unauthenticated data access and cross-user data leakage in production
  - Allows development without authentication when explicitly configured
- **Dependency Security Validation (Phase 3)**
  - Zero vulnerabilities found in 79 scanned packages (Safety v3.7.0)
  - All dependencies up-to-date with no known CVEs
  - Key packages verified: fastapi 0.123.0, sqlalchemy 2.0.29, pillow 12.0.0, argon2-cffi 25.1.0
- **Code Security Validation (Phase 3)**
  - Bandit scan: Only 2 findings, both acceptable design choices
    - 0.0.0.0 binding (required for Docker container networking)
    - MD5 for cache keys (non-cryptographic use case with `usedforsecurity=False`)
  - No actual security vulnerabilities detected in 41,554 lines of code
  - Strong security posture validated by automated scanning

### Performance
- **Service Layer Optimizations**
  - MPG calculation now cached with 5-minute TTL (automatic invalidation on data changes)
  - Photo hydration removed from request hot path (one-time migration instead)
  - N+1 query optimizations in ServiceRecordService (pre-fetches attachment counts via JOIN)
  - Reduced code size improves application load time and memory footprint
- **Authentication Flow Optimization**
  - Single API call to check `auth_mode` instead of 3 duplicate calls
  - Resolved rate limit issues (200+ requests to `/settings/public` → 1 request)
  - Centralized state management prevents redundant network requests

### Technical Notes
- **Service Layer Architecture**: Implements dependency injection, integrated authorization, complete business logic separation from HTTP layer
- **Type Safety**: All functions use `Optional[User]` to force explicit null handling throughout codebase
- **Smart Authentication**: Functions check `auth_mode` setting dynamically - no hardcoded auth bypass logic
- **Graceful Degradation**: None users represent guest access with full permissions when auth is disabled
- **Code Quality**: 71% reduction in linting issues, 69% reduction in main route file, production-ready code
- **Backward Compatibility**: All API contracts maintained, photo endpoints work identically after extraction
- Database migrations: 013 (user_id for multi-user support), 014 (legacy photo hydration)

## [2.12.0] - 2025-11-28

### Added
- **Multi-Service Notification System** - Expanded from ntfy-only to 7 notification providers
  - **ntfy** - Self-hosted push notifications with optional token authentication
  - **Gotify** - Self-hosted push notification server
  - **Pushover** - iOS/Android push notifications
  - **Slack** - Team channel notifications via webhooks
  - **Discord** - Discord channel notifications via webhooks
  - **Telegram** - Bot-based notifications
  - **Email** - SMTP-based email notifications (with STARTTLS support)
  - Unified NotificationDispatcher with priority-based retry logic
  - Per-service test endpoints (`/api/notifications/test/{service}`)
  - Configurable retry attempts and delays with service-specific multipliers
  - Event-type toggles: recalls, service due/overdue, insurance/warranty expiring, milestones

- **Frontend Notification Configuration UI**
  - Sub-tab navigation for switching between notification providers
  - Individual configuration forms for each service with enable toggle, credentials, and test button
  - Green dot indicators showing which services are enabled
  - Unified Event Notifications card with expandable sections
  - Advance warning day configuration for insurance, warranty, and service reminders
  - Two-column responsive layout (service config + event settings)

### Changed
- Backend notification architecture refactored to abstract base class pattern
- Settings system expanded with 24 new notification-related keys
- Notification services use async HTTP (httpx) and async SMTP (aiosmtplib)

## [2.11.0] - 2025-11-26

### Added
- **Frontend HTTP Error Handler** - New utility for consistent error message handling
  - `httpErrorHandler.ts` maps HTTP status codes to user-friendly messages
  - `parseApiError()` - Full error parsing with status, message, retry hints
  - `getErrorMessage()` - Simple error message extraction
  - `getActionErrorMessage()` - Context-aware messages ("Failed to save...")
  - Re-exported from `api.ts` for convenient access throughout frontend

### Changed
- **Error Handling Standardization** - Refactored generic exception handlers to use specific exception types
  - Reduced generic `except Exception as e:` handlers from ~120 to ~71 (40% reduction)
  - API routes now use specific exceptions: `IntegrityError`, `OperationalError`, `httpx.*`, `FileNotFoundError`, etc.
  - Improved HTTP status codes: 409 for conflicts, 503 for database unavailable, 504 for timeouts
  - Better error messages that don't expose internal details
  - Remaining generic handlers are intentional fallbacks (CSV import rows, OCR, migrations)

### Fixed
- **Backup Creation Logout Bug** - Fixed issue where creating backups would log users out
  - Exempted `/api/backup/*` routes from CSRF protection (already protected by JWT authentication)
  - Backup endpoints are idempotent with no user input, making CSRF protection redundant
  - Added CSRF token storage validation to catch sessionStorage failures early
  - Added console warnings when CSRF tokens are missing on state-changing requests
  - Removed duplicate CSRF token cleanup from middleware (performance optimization)

## [2.10.0] - 2025-11-23

### Security
- **CRITICAL: CSRF Protection** - Implemented synchronizer token pattern for cross-site request forgery protection
  - Added `csrf_tokens` database table with 24-hour token expiration
  - CSRF tokens automatically generated on login (both local and OIDC)
  - Middleware validates CSRF tokens on all state-changing operations (POST/PUT/PATCH/DELETE)
  - Tokens returned in login response for frontend integration
  - Automatic cleanup of expired tokens on logout and login

- **CRITICAL: Settings Endpoint Security** - Fixed privilege escalation vulnerability
  - **BREAKING**: Split settings endpoints - `/api/settings/public` (no auth) for initialization, `/api/settings` (admin-only) for management
  - All settings CRUD operations now require admin privileges (`get_current_admin_user`)
  - Public endpoint returns only whitelisted settings: `auth_mode`, `app_name`, `theme`
  - Prevents unauthorized users from reading/modifying sensitive configuration (OIDC secrets, SMTP credentials, etc.)

- **HIGH: JWT Cookie Security** - Auto-detect secure cookie flag based on environment
  - `jwt_cookie_secure` now auto-detects: `Secure=true` in production (`debug=false`), `Secure=false` in development
  - Prevents session token exposure over unencrypted HTTP in production
  - Explicit override available via `JWT_COOKIE_SECURE` environment variable
  - Default changed from `false` to environment-aware

- **MEDIUM: OIDC State Persistence** - Database-backed state storage for multi-worker reliability
  - Added `oidc_states` database table with 10-minute expiration
  - Replaces in-memory dictionary storage
  - Supports multi-worker deployments and container restarts during authentication flows
  - State validation and one-time-use enforcement via database

- **LOW: SQLite Pool Configuration** - Conditional pool settings for database compatibility
  - Pool configuration now only applied to PostgreSQL/MySQL
  - SQLite uses appropriate NullPool automatically
  - Prevents future SQLAlchemy compatibility issues

### Changed
- **Database Migration 012**: Added `csrf_tokens` and `oidc_states` tables with indexes
- CORS middleware now allows `X-CSRF-Token` header
- Login and logout endpoints updated to manage CSRF tokens
- OIDC callback endpoint updated to generate CSRF tokens
- Settings routes refactored for public/admin separation

### Technical Notes
- Frontend integration required: Store CSRF token from login response, send in `X-CSRF-Token` header for mutations
- Addresses Codex security audit findings: HIGH and MEDIUM risk items resolved
- Version bump: 2.8.0 → 2.10.0 (skipped 2.9.0 to align with frontend)

## [2.8.0] - 2025-11-23

### Added
- **Fleet Analytics Enhancements**
  - CSV export functionality for fleet-wide data analysis
  - PDF export with professional fleet report generation
  - Fleet Analytics Help Modal with comprehensive feature documentation
  - Rolling average trend lines (3-month and 6-month) on monthly spending chart
  - Visual spending trend analysis with smooth overlay indicators

- **Individual Vehicle Analytics Enhancements**
  - CSV export for vehicle-specific analytics data
  - PDF export with detailed vehicle reports
  - Export functionality mirrors fleet analytics capabilities
  - Consistent export button styling across both analytics pages

### Changed
- Standardized export button UI across Fleet and Vehicle Analytics pages
- Updated button styling to use garage theme colors for consistency
- Removed "Export" prefix from button labels (now just "CSV" and "PDF")

### Technical Notes
- Added `garage-primary`, `garage-primary-dark`, `success`, and `danger` color classes to Tailwind theme
- Frontend analytics pages now fully support data export workflows
- Export buttons use consistent `bg-garage-surface` styling with theme-aware hover states

## [2.7.0] - 2025-11-23

### Added
- **OpenID Connect (OIDC) / SSO Authentication**
  - Complete OIDC authentication integration with support for external identity providers (Authentik, Keycloak, etc.)
  - "Sign in with SSO" button on login page with dynamic provider name display
  - OIDC callback success page with automatic token handling and redirect
  - Email-based account linking - automatically links OIDC accounts to existing local accounts via verified email
  - Dual authentication support - users can login with either password OR OIDC after linking
  - Admin UI for OIDC configuration in Settings → System → OIDC tab
    - Provider configuration: Issuer URL, Client ID/Secret, Scopes
    - Auto-generated redirect URI display
    - Test connection functionality with detailed result feedback
    - Claim mapping configuration (username, email, full name)
    - Group-based admin role mapping
    - Authentik setup guide with step-by-step instructions
  - Database schema additions: `oidc_subject`, `oidc_provider`, `auth_method` fields on User model
  - 12 new OIDC settings with defaults and validation
  - `/api/auth/oidc/config` - Public OIDC configuration endpoint
  - `/api/auth/oidc/login` - OIDC flow initiation endpoint
  - `/api/auth/oidc/callback` - Provider callback handler
  - `/api/auth/oidc/test` - Admin-only connection testing endpoint

### Security
- **OIDC Security Features**
  - CSRF protection via state parameter validation (10-minute expiration)
  - Replay attack protection via nonce validation in ID tokens
  - JWT signature verification using provider's JWKS public keys
  - Issuer claim validation (prevents token reuse from other providers)
  - Audience claim validation (ensures tokens issued for MyGarage)
  - Expiration validation on all tokens
  - NULL password protection - OIDC-only users cannot authenticate via password login
  - Made `hashed_password` column nullable to support OIDC-only users (migration 011)

### Changed
- Authentication system now supports multiple auth methods (local password + OIDC)
- User model `hashed_password` field is now nullable (OIDC-only users have NULL password)
- Login page conditionally displays SSO button based on OIDC configuration

### Dependencies
- **Backend**: Added `authlib>=1.6.5` for OIDC/OAuth2 authentication

### Technical Notes
- Backend implementation: 532-line OIDC service with complete OAuth2 flow
- Frontend implementation: OIDC success page, login page SSO integration, settings UI
- Database migration 011 applied to support OIDC fields
## [2.6.0] - 2025-11-22

### Added
- **Light/Dark Theme System**
  - User-selectable theme toggle in Settings → System tab
  - Comprehensive light theme for all pages and components
  - React Big Calendar fully themed for both light and dark modes
  - Theme preference persisted in both localStorage (instant) and database (cross-device sync)
  - ThemeContext provider for global theme state management
  - Sun/Moon icon toggle UI with visual active state indication
  - Default theme remains dark mode for existing users
  - Tailwind v4 CSS variable architecture for clean theme switching
  - Refactored 48+ components to use semantic theme-aware classes
  - Light mode color palette: white cards (#ffffff) on light gray background (#f3f4f6)
  - Dark mode color palette: slate cards (#1a1f28) on dark background (#0a0e14)

### Fixed
- **Light Mode Styling Issues**
  - Removed 200+ hardcoded dark gray button styles (`bg-gray-700`) across all components
  - Replaced with semantic `.btn-primary` class that adapts to both themes
  - Fixed modal overlays being too harsh in light mode (50% → 30% opacity)
  - Fixed badge colors not adapting to light mode background
  - Fixed text contrast issues with hardcoded gray colors
  - Corrected CSS architecture to properly use Tailwind v4 `@theme` directive
  - Eliminated redundant CSS variable overrides
  - Removed all `!important` hacks - proper specificity through CSS layers

### Security
- **Password Hashing Migration: Bcrypt → Argon2**
  - Migrated from bcrypt 5.0.0 to Argon2id (argon2-cffi 25.1.0)
  - Argon2id is the current OWASP recommended password hashing algorithm
  - Hybrid verification system supports both legacy bcrypt and new Argon2 hashes
  - Auto-rehashing: User passwords transparently upgraded to Argon2 on next login
  - No password resets required - zero downtime migration
  - Removed 72-byte password length limitation (bcrypt restriction)
  - Argon2 parameters: time_cost=2, memory_cost=102400 (100MB), parallelism=8
  - Migration tracking via automated database migration system (migration 010)
  - bcrypt temporarily retained for gradual migration support

### Changed
- Tailwind CSS dark mode enabled via class-based switching
- Theme preference stored in global settings table with category 'general'
- CSS architecture updated to support dynamic theme switching via CSS variables

## [2.5.2] - 2025-11-22

### Changed
- **Automated Database Migration System**
  - Migrations now run automatically on container startup
  - Added `schema_migrations` tracking table
  - Renamed migration files with numeric prefixes for ordering
  - Extracted inline migrations from database.py to standalone files
  - Prevents schema drift between development and production
  - No manual migration execution required after deployments

### Fixed
- Database migration system now prevents schema mismatch issues
- Migration tracking persists across container restarts

## [2.5.1] - 2025-11-22

### Security
- **CRITICAL: Fixed default authentication mode**
  - Changed default `auth_mode` from `none` to `local` to require authentication by default
  - Previously, all endpoints were publicly accessible out-of-the-box until manually configured
  - New instances now require authentication immediately after first admin setup

- **CRITICAL: Fixed rate limiting enforcement**
  - Wired up SlowAPI middleware to actually enforce rate limits
  - Previously, rate limit decorators were no-ops due to missing middleware
  - Auth endpoints now properly rate-limited at 5 requests/minute to prevent brute-force attacks
  - Upload endpoints now properly rate-limited at 20 requests/minute to prevent DoS
  - Default global rate limit of 200 requests/minute now enforced

- **CRITICAL: Fixed open user registration**
  - Registration endpoint now restricted to first user only
  - After first admin is created, public registration is disabled
  - Added new admin-only `/api/auth/users` POST endpoint for admins to create accounts
  - New users created by admins default to inactive and non-admin status
  - Prevents unauthorized account creation on public instances

### Changed
- User registration flow: Only first user can self-register (becomes admin)
- Subsequent users must be created by administrators through user management UI
- New users require admin activation before they can log in

## [2.5.0] - 2025-11-22

### Added
- **Zod + React-Hook-Form Integration**
  - Implemented declarative form validation using Zod v4 schemas
  - Created reusable schema infrastructure in `/frontend/src/schemas/`
    - `shared.ts`: Common validators (mileage, currency, dates, etc.)
    - `auth.ts`: Authentication forms with password strength validation
    - `fuel.ts`: Fuel record validation
    - `service.ts`: Service record validation with type enum
    - `reminder.ts`: Conditional validation (date OR mileage required)
  - Added `FormError` component for field-level error display
  - Migrated Register and Login forms to use react-hook-form with zodResolver
  - Real-time validation with field-specific error messages
  - Password strength indicator in registration form

### Changed
- **Dependency Updates**
  - Updated zod: 3.24.0 → 4.1.12
  - Updated @hookform/resolvers: 3.9.0 → 5.2.2
  - Updated react-hook-form: 7.54.0 → 7.61.1
  - Updated axios: 1.7.0 → 1.13.2
  - Updated lucide-react: 0.553.0 → 0.554.0
  - Updated @types/react: 19.0.6 → 19.2.6
  - Updated @types/react-big-calendar: 1.8.12 → 1.16.3
  - Updated @types/react-dom: 19.0.2 → 19.2.3
  - Updated @typescript-eslint packages: 8.46.4 → 8.47.0
  - Updated vite: 7.2.2 → 7.2.4

### Fixed
- **Critical: Password Validation Mismatch**
  - Fixed frontend password validation to match backend requirements
  - Frontend now validates: uppercase, lowercase, digit, special character (!@#$...)
  - Previously only checked length ≥ 8, causing confusing backend rejection errors
  - Users now get immediate, clear feedback about password requirements

## [2.4.0] - 2025-11-21

### Added
- **Unified Document Scanner with Multi-Provider Insurance Support**
  - Consolidated PDF/image scanning architecture for all document types
  - Insurance documents now use same OCR engine as window stickers (PaddleOCR + Tesseract)
  - Auto-detection of insurance providers from document content
  - Provider-specific parsers: Progressive, State Farm, GEICO, Allstate
  - Generic fallback parser for unknown providers
  - Image upload support for insurance documents (jpg, png) in addition to PDF
  - New `/api/insurance/parsers` endpoint to list available parsers and OCR status
  - New `/api/vehicles/{vin}/insurance/test-parse` endpoint for debugging extraction
  - Confidence scoring (0-100%) for insurance extraction
  - Per-field confidence levels (high/medium/low)
  - Optional `provider` query parameter to hint parser selection

- **Window Sticker OCR Display Enhancement**
  - Added display of all OCR-extracted fields that were previously stored but not shown
  - New Standard Equipment card (collapsible) showing categorized standard features
  - New Optional Equipment card (collapsible) with pricing from `window_sticker_options_detail`
  - New Packages card showing package groupings with prices
  - OCR metadata display (parser used, confidence score, VIN verification)
  - Drivetrain field now displayed in Powertrain card

### Removed
- **pdfplumber dependency**
  - Removed unused pdfplumber library (PyMuPDF handles all PDF operations)
  - Reduces container size and maintenance burden

### Fixed
- **Window Sticker Data Display Gap**
  - Fixed 8 OCR-extracted fields not being rendered in frontend despite being stored in database
  - Fields now displayed: `standard_equipment`, `optional_equipment`, `window_sticker_options_detail`, `window_sticker_packages`, `sticker_drivetrain`, `window_sticker_parser_used`, `window_sticker_confidence_score`, `window_sticker_extracted_vin`
- **Stellantis OCR Parser Fixes**
  - Fixed environmental ratings extraction (GHG/Smog) - now correctly identifies actual ratings vs scale markers
  - Fixed equipment categorization - optional package items no longer appear under standard equipment
  - Fixed confidence score display (was showing 9500% instead of 95%)

## [2.3.1] - 2025-11-19

### Changed
- **Frontend JWT Authentication Migration**
  - Migrated 35 components from direct `fetch()` calls to centralized axios API client
  - All API requests now automatically include `Authorization: Bearer <token>` header
  - Consistent error handling with automatic logout/redirect on 401 errors
  - Improved type safety and code maintainability

### Fixed
- **Authentication consistency**
  - Eliminated "No credentials provided" errors from components bypassing auth
  - Fixed JWT token not being sent with dashboard, settings, form, and page requests
  - Corrected authentication flow in backup/restore operations
  - Fixed file upload/download endpoints to properly use axios with FormData and blob responses
  - Fixed vehicle import/export JSON functionality

### Technical Details
- Updated components (35 total):
  - Pages: Dashboard, Register, VehicleDetail, VehicleEdit
  - Settings tabs: System, Files, Integrations, Notifications, Backup, AddressBook
  - Forms: ServiceRecord, TollTag, TollTransaction, TaxRecord, SpotRental
  - Uploads: PhotoUpload, WindowStickerUpload
  - Lists: TollTagList, TollTransactionList, TaxRecordList, SpotRentalList
  - Tabs: TollsTab
  - Utilities: AddressBookSelect, AddressBookAutocomplete, ReportsPanel, ProtectedRoute
  - Hooks: useAppVersion
- All file downloads now use `responseType: 'blob'` with axios
- FormData uploads work seamlessly without additional configuration
- Updated fallback version in useAppVersion to 2.3.1

## [2.3.0] - 2025-11-15

### Added
- **Propane tracking for fifth wheel vehicles**
  - Added `propane_gallons` field to fuel records (Numeric 8,3 precision)
  - New propane input field in fuel record form
  - Propane column in fuel record list view
  - Automatic database migration on startup
  - Input validation (0-999.999 gallons, 3 decimal places)
- **Security improvements** (10 major fixes)
  - Path traversal protection for document uploads
  - VIN pattern validation (17-character alphanumeric)
  - SQL injection prevention via parameterized queries
  - MIME type validation for file uploads (PDF, images)
  - File size limits (10MB for images, 50MB for PDFs)
  - Password length limits (72 bytes for bcrypt compatibility)
  - Email format validation (max 254 characters)
  - User input sanitization across all endpoints
  - Rate limiting headers exposed in CORS configuration
  - Comprehensive error handling with proper HTTP status codes

### Fixed
- **Critical:** Fixed fifth wheel fuel tab access
  - Corrected boolean operator precedence in vehicle type check
  - Fifth wheels can now properly access fuel tracking features
- **Security:** Prevented path traversal in document downloads
  - Added strict filename validation
  - Restricted access to user-owned documents only
- **Security:** Added MIME type validation for uploads
  - Prevents execution of malicious files
  - Validates against allowed types (PDF, JPG, PNG, HEIC, etc.)
- **Security:** Implemented file size limits
  - Images: 10MB maximum
  - PDFs: 50MB maximum
  - Prevents DoS attacks via large file uploads
- Input validation edge cases across multiple endpoints
  - Maintenance records: validated mileage, date ranges
  - Fuel records: validated amounts, prices, odometer readings
  - Documents: validated descriptions, file metadata
  - Settings: validated configuration values

### Changed
- Updated version to 2.3.0 (MINOR bump for propane feature)
- Enhanced fuel record form layout (3-column grid)
- Improved About page organization and statistics

---

## [2.2.1] - 2025-11-15

### Fixed
- **Critical:** Removed non-functional token refresh logic
  - Eliminated dead code calling non-existent `/api/auth/refresh` endpoint
  - Simplified authentication flow
  - Reduced unnecessary API calls
- **Critical:** Fixed React hooks compliance violations
  - Added proper `useCallback` wrappers in AuthContext
  - Fixed PhotoGallery dependencies
  - Corrected Calendar.tsx hook dependencies
  - Removed all `eslint-disable` comments for hooks
- Removed 11 production console.log statements
  - Kept only PWA-related debug logs
  - Cleaner console output

### Performance
- **Added React.memo to 17 expensive components**
  - VehicleCard, PhotoGallery, ReminderCard, MaintenanceRecordItem
  - DocumentCard, FuelCard, FuelRecordList, MaintenanceRecordList
  - DocumentList, ReminderList, VehicleList, TabContent components
  - Analytics charts and reports components
  - Reduces unnecessary re-renders
  - Improved list/grid rendering performance
- Optimized component re-rendering patterns

### Improved
- **Code quality** - Better React patterns and hooks compliance
- **Developer experience** - No more lint warnings
- **Production logs** - Reduced noise, better signal

---

## [2.2.0] - 2025-11-15

### Changed
- **MAJOR:** Migrated from Uvicorn to Granian ASGI server
  - **+11% requests/sec** (45,000 → 50,000)
  - **-25% memory usage** (20MB → 15MB per worker)
  - More consistent latency (2.8x max/avg vs 6.8x)
  - Single worker mode for APScheduler compatibility
- **MAJOR:** Removed deprecated libraries
  - Removed moment.js (~232KB), replaced with date-fns (~78KB) - **-154KB**
  - Removed unused chart.js and react-chartjs-2 - **-200KB**
  - Total bundle savings: **~350KB**
- **MAJOR:** Implemented frontend code splitting
  - Route-based lazy loading for all pages
  - Manual chunk configuration (react-vendor, charts, calendar, ui, forms, utils)
  - **-78% initial bundle size** (~900KB → ~200KB)
  - **-60% time to interactive** (~2.5s → <1s)
- **MAJOR:** Migrated to @vitejs/plugin-react-swc
  - Faster builds using SWC instead of Babel
  - Better development experience
- Fixed Tailwind v4 PostCSS configuration
  - Created `postcss.config.js` with @tailwindcss/postcss plugin
  - Added autoprefixer support
  - Simplified tailwind.config.js (theme moved to CSS)

### Added
- Created `pyproject.toml` for modern Python packaging
  - Version management in single source of truth
  - Dev dependencies separated (pytest, ruff)
  - Better tooling support
- **Health check logging filter**
  - Suppresses Docker health check logs from access logger
  - Reduces log noise while preserving API request visibility
  - Applied to Granian access logger

### Security
- **bcrypt v5.0 password validation**
  - Added password length checks (max 72 bytes)
  - Prevents silent truncation vulnerability
  - Returns clear error for invalid passwords

### Updated
- **Backend dependencies:**
  - FastAPI: 0.121.0 → 0.121.1
  - APScheduler: 3.10.4 → 3.11.1
  - Pydantic: 2.12.0 → 2.12.3
  - Pillow: 11.0.0 → 12.0.0 (Python 3.14 support)
  - Added Granian: 2.5.7
- **Frontend dependencies:**
  - lucide-react: 0.468.0 → 0.553.0
  - react-router-dom: 7.1.1 → 7.9.6
  - recharts: 3.3.0 → 3.4.1
  - TypeScript: 5.6.2 → 5.9.3
  - @types/react: 19.0.0 → 19.0.6
  - @types/react-dom: 19.0.0 → 19.0.2
  - Added date-fns: 4.1.0
  - Added @tailwindcss/postcss: 4.1.17
  - Added autoprefixer: 10.4.20

---

## Earlier Versions

- **v2.1.0:** Authentication UI redesign, dependency updates (Tailwind v4, Vite 7), security improvements, zero-config
- **v2.0.0:** Backup system, service consolidation, enhanced features
- **v1.x:** Initial development phases (7 major phases + 12 feature phases)

---


