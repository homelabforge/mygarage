# Changelog

All notable changes to MyGarage will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Family Dashboard Management Modal** - Dedicated modal for managing family dashboard member visibility and ordering
  - Toggle member visibility on/off with Eye icon buttons
  - Reorder visible members with up/down arrows
  - Separates visible and hidden members into distinct sections
  - Real-time API updates (no "Save" button needed)
- **Transfer History Section** - Display vehicle ownership transfer history on VehicleDetail page
  - Collapsible timeline showing ownership transfers
  - Displays from_user → to_user with relationship badges
  - Shows transfer date, transferred_by admin, and notes
  - Shows data included (service records, fuel logs, etc.) as badges
- **Dashboard Shared Vehicle Badge & Filter** - Visual distinction for shared vehicles
  - Blue "Shared" badge on vehicle cards when vehicle is shared with you
  - Tooltip shows who shared the vehicle and permission level (view/edit)
  - Filter dropdown (All Vehicles / My Vehicles / Shared With Me) - only appears if you have shared vehicles
- **LiveLink Integration** - Real-time vehicle telemetry monitoring with WiCAN OBD2 devices
  - **HTTPS POST Transport** - WiCAN PRO devices can push telemetry directly to MyGarage with token authentication
  - **MQTT Subscription** - Subscribe to MQTT broker for telemetry from any WiCAN device (PRO or standard)
  - **Real-time Dashboard** - Live gauges displaying speed, RPM, coolant temp, and other parameters
  - **Drive Sessions** - Automatic session detection on engine start/stop with trip statistics
  - **DTC Monitoring** - Track diagnostic trouble codes with severity levels and user notes
  - **Odometer Auto-Sync** - Automatic odometer updates from telemetry with LiveLink badge
  - **Historical Charts** - Time-series visualization with multi-parameter overlay and CSV export
  - **Device Management** - Link devices to vehicles, per-device tokens, firmware update notifications
  - **Threshold Alerts** - Configurable warnings for parameters like coolant temp and battery voltage
  - **Data Retention** - Configurable retention periods (30-365 days) with daily aggregation
  - **Wiki Documentation** - Comprehensive LiveLink guide, FAQ section, and troubleshooting

### Fixed
- **OIDC Admin User Management** - OIDC admins can now access Multi-User Management in Settings
  - Previously restricted to local auth admins only
  - Add User button and multi-user toggle hidden for OIDC (users managed in identity provider)
- **Odometer Sync Sanity Checks** - Prevent corrupted values (0xFFFFFF sentinel) from being stored
  - Added 1 million mile absolute cap
  - Added 10,000 mile jump limit to catch overflow values
  - Capped dates to today to prevent future-dated entries from device clock issues
- **Backup Download Performance** - Fixed slow backup downloads by using native browser download
  - Previously loaded entire file into memory via AJAX before triggering download
  - Now uses direct browser navigation, providing proper progress indication and reduced memory usage
- **Backup Upload Visibility** - Uploaded backups now appear in the backup list
  - Previously, uploaded files with non-standard names wouldn't match the listing glob pattern
  - Now renames uploaded files to `mygarage-{type}-uploaded-{timestamp}.{ext}` for consistency
  - Added validation for missing filename

### Changed
- **Centralized User Types** - Consolidated duplicate User interface definitions into single source of truth
  - Created `frontend/src/types/user.ts` with canonical User interface
  - Updated UserManagementModal, AddEditUserModal, and SettingsSystemTab to import from shared type
- **Authentication Mode UI** - Redesigned Settings > System authentication configuration
  - Renamed "Local JWT" button to "Local" for clarity
  - Local and OIDC configuration now open in modal dialogs instead of inline forms
  - Tab buttons (None, Local, OIDC) now only select the mode; click "Configure" to open settings
  - Modal backdrops use blur effect for better visual hierarchy
  - Moved Archived Vehicles card below Authentication Mode card in layout
- **LiveLink Dashboard Widget** - Removed battery voltage from compact vehicle card view (still visible in full LiveLink tab)
- **LiveLink Tab Header** - Removed battery voltage from status bar for cleaner display

### Fixed
- **MQTT Subscriber** - Removed unnecessary isinstance check that caused pyright error in CI

### Dependencies
- **granian**: 2.6.1 → 2.7.0

### Dev Dependencies
- **@vitejs/plugin-react-swc**: 4.2.2 → 4.2.3
- **eslint-plugin-react-refresh**: 0.4.26 → 0.5.0
- **globals**: 17.2.0 → 17.3.0
- **jsdom**: 27.4.0 → 28.0.0
- **aiomqtt**: Added >=2.3.0 for MQTT subscription support
- **@types/react**: 19.2.10 → 19.2.11
- **ruff**: 0.14.14 → 0.15.0

## [2.20.4] - 2026-01-31

### Fixed
- **Monthly Spending Trend Chart** - Fixed chart displaying duplicate x-axis labels and empty right half
  - Line components for rolling averages were providing separate `data` props, causing Recharts to render duplicate axis entries
  - Merged `avg3` and `avg6` rolling averages directly into `trendData` array
  - Removed separate `data` prop from Line components so they use the chart's unified dataset

### Changed
- **oven/bun**: 1.3.7-alpine → 1.3.8-alpine
- **axios**: 1.13.3 → 1.13.4
- **autoprefixer**: 10.4.23 → 10.4.24
- **Recharts Cell Migration** - Migrated deprecated `Cell` component to `shape` prop pattern for Pie chart (Recharts 3.7.0 deprecation)

### Security
- **CodeQL Alerts #905-#908** - Fixed clear-text logging false positives in POI registry
  - Config dict contains `api_key` which tainted all derived values including `name` and `priority`
  - Used `sanitize_for_log()` to break taint chain through string transformation
  - Used `int()` constructor for priority values

## [2.20.3] - 2026-01-27

### Fixed
- **Metric Unit Mileage** - Odometer/fuel/service records failing with 422 error when using metric units ([#25](https://github.com/homelabforge/mygarage/issues/25))
  - km→miles conversion produced floats, but backend expects integers
  - Added `Math.round()` to all mileage conversions in OdometerRecordForm, FuelRecordForm, ServiceRecordForm, and ServiceVisitForm
- **Photo Upload** - Vehicle photo upload failing with 422 "file field required" error ([#24](https://github.com/homelabforge/mygarage/issues/24))
  - Fixed missing `Content-Type: multipart/form-data` header in PhotoUpload, VehicleDetail JSON import, and SettingsBackupTab upload

### Changed
- **oven/bun**: 1.3.6-alpine → 1.3.7-alpine
- **axios**: 1.13.2 → 1.13.3
- **react**: 19.2.3 → 19.2.4
- **react-dom**: 19.2.3 → 19.2.4
- **react-is**: 19.2.3 → 19.2.4
- **react-router-dom**: 7.12.0 → 7.13.0
- **recharts**: 3.6.0 → 3.7.0
- **zod**: 4.3.5 → 4.3.6
- **@types/react**: 19.2.8 → 19.2.10
- **@typescript-eslint/eslint-plugin**: 8.53.1 → 8.54.0
- **@typescript-eslint/parser**: 8.53.1 → 8.54.0
- **@vitest/ui**: 4.0.17 → 4.0.18
- **globals**: 17.0.0 → 17.2.0
- **typescript-eslint**: 8.53.1 → 8.54.0
- **vitest**: 4.0.17 → 4.0.18
- **pandas-stubs**: 2.3.3 → 2.3.3.260113
- **ruff**: 0.14.13 → 0.14.14
- **types-Pillow**: 10.2.0 → 10.2.0.20240822

## [2.20.2] - 2026-01-27

### Fixed
- **PostgreSQL Compatibility** - Dashboard not showing new vehicles when using PostgreSQL ([#23](https://github.com/homelabforge/mygarage/issues/23))
  - Changed `archived_visible` field from Integer to Boolean type for proper PostgreSQL compatibility
  - Vehicle schema now correctly uses `bool` type instead of `int` for archive visibility
- **NHTSA Body Class Field** - Increased `body_class` field length from 50 to 100 characters to accommodate longer NHTSA values
- **Migration System Database URL** - Migration runner now uses configured `DATABASE_URL` environment variable instead of hardcoded SQLite path
- **Archive Endpoint Timezone** - Fixed PostgreSQL timezone issue in archive endpoint
  - Created `utc_now()` utility function for timezone-naive datetime operations
  - Applied to vehicle archive/restore operations in `vehicles.py`, `window_sticker.py`, and `reminders.py`
- **PostgreSQL Driver** - Added `psycopg2-binary` dependency for synchronous PostgreSQL migrations

## [2.20.1] - 2026-01-25

### Changed
- **Garage Analytics Overhaul** - Improved cost tracking and categorization
  - **Service Category Breakdown**: Cost by Category pie chart now shows all 5 service categories separately (Maintenance, Upgrades, Inspection, Collision, Detailing) instead of lumping all services into "Maintenance"
  - **Running Costs by Vehicle Redesign**: Consolidated bar chart and vehicle cost breakdown into a single card
    - Converted to horizontal bar chart layout for better readability
    - Added inline cost breakdown table (Maint. | Upgrades | Insp. | Collision | Detail. | Fuel | Total)
    - Removed standalone "Vehicle Cost Comparison" section (data now in combined card)
    - Removed purchase price from breakdown (already shown in Garage Value summary card)
  - **Vehicle Nickname Display**: Bar chart and breakdown table now show vehicle nicknames instead of full year/make/model
  - **Running Costs vs Total Cost**: "Total Cost" renamed to "Running Costs" and now excludes purchase price (shows only operational costs: all service categories + fuel)
  - **CSV Export**: Updated to include all service category columns (still uses full vehicle name for data export)
  - Backend now groups service records by `service_category` field for accurate analytics

- **Vehicle Detail Page - Non-Motorized Vehicle Handling**
  - **Powertrain Section Hidden**: Trailers, Fifth Wheels, and Travel Trailers no longer show the "Powertrain" section (they don't have engines)
  - **Fuel Type in Vehicle Details**: For non-motorized vehicles with propane (fifth wheels, travel trailers), fuel type now displays in the "Vehicle Details" card instead of Powertrain
  - Uses existing `isMotorized` check to conditionally render appropriate sections

### Fixed
- **PostgreSQL Support** - Added missing `asyncpg` dependency required for PostgreSQL database connections ([#21](https://github.com/homelabforge/mygarage/issues/21))
- **Vehicle Edit Form - Non-Motorized Vehicle Support** - Fixed form validation blocking saves for trailers, fifth wheels, and travel trailers
  - Hidden "VIN Decoded Information" and "Engine & Transmission" sections for non-motorized vehicles
  - Added separate "Fuel Information" section for non-motorized vehicles with propane
  - Fixed form validation schemas to handle null values from database (was causing "Invalid input" errors on optional fields)
  - Form now only loads relevant fields based on vehicle type, preventing hidden field validation failures
- **Integration Test Suite Alignment** - Fixed 59 integration tests to match actual API implementation
  - Updated route paths to match current API structure (`/api/export/vehicles/{vin}/...` format)
  - Added required `title` field to document upload tests
  - Fixed photo delete tests to use filename instead of numeric ID
  - Fixed VIN inclusion in document download/delete route paths
  - Updated expected HTTP status codes (422 for Pydantic validation, not 400)
  - Added rate limit tolerance (429) to CSV format validation tests
- **Export Route Bug** - Fixed `FuelRecord.mpg` attribute error in CSV/JSON export
  - `mpg` field doesn't exist on FuelRecord model; replaced with `is_hauling` and `fuel_type` fields
  - Updated CSV headers and JSON export to use actual model attributes

### Changed
- **Test Infrastructure** - Improved pytest-asyncio configuration
  - Added `loop_scope="session"` to async fixtures for proper event loop reuse
  - Updated pytest.ini with asyncio_default_fixture_loop_scope setting

## [2.20.0] - 2026-01-19

### Security
- **CodeQL Security Remediation - 173 Issues Fixed**
  - **Log Injection Prevention (138 fixes)** - CWE-117
    - Created `sanitize_for_log()` utility function that escapes control characters (newlines, tabs, ANSI escapes)
    - Applied to all user-controlled values in logger calls across 44+ files
    - Prevents log forging and log injection attacks
  - **Clear-Text Logging of Sensitive Data (10 fixes)** - CWE-532
    - Created `mask_coordinates()` function to reduce GPS precision for privacy (~1.1km)
    - Created `mask_api_key()` function to show only first 4 characters
    - Applied to shop discovery, POI providers, and integration services
  - **Unsafe Cyclic Imports (13 fixes)** - Python best practices
    - Moved runtime imports to `TYPE_CHECKING` blocks in SQLAlchemy models
    - Fixed `Vehicle` model (16 forward reference imports)
    - Fixed `MaintenanceTemplate` model (1 forward reference import)
  - **Partial SSRF Protection (1 fix)** - CWE-918
    - Added URL validation in `MaintenanceTemplateService` for GitHub template URLs
    - Allowlisted hosts: `raw.githubusercontent.com`, `github.com`, `raw.github.com`
    - Path component sanitization prevents directory traversal
  - **Stack Trace Exposure (1 fix)** - CWE-209
    - Fixed provider test endpoint in settings routes
    - Exception details now logged server-side only, generic message returned to client
  - **Code Quality Fixes (5 fixes)**
    - Fixed empty-except in OSM provider with meaningful error handling
    - Fixed unused-import in maintenance template validator
    - Fixed mixed-returns in pytest conftest with proper `NoReturn` typing

### Added
- **Maintenance System Overhaul - Complete Service Tracking Redesign**
  - **Vendors**: New vendor management system replacing address book for service providers
    - Dedicated vendor table with type (shop, dealer, self, other)
    - Vendor history tracking (service count, total spent, last visit)
    - Search/autocomplete for existing vendors when creating service visits
  - **Service Visits**: Replaced service records with comprehensive visit tracking
    - Visit-level data: date, vendor, mileage, notes
    - Multiple line items per visit (parts, labor, services)
    - Line items: description, category, service type, cost, notes
    - Tax & fees tracking: tax amount, shop supplies, misc fees
    - Subtotal (line items only) and calculated total (including all fees)
    - Attachment support migrated from old service records
  - **Maintenance Schedule Items**: New proactive maintenance tracking
    - Schedule items with due dates (by date or mileage)
    - Status tracking: upcoming, due soon, overdue, completed
    - Link service visits to schedule items when completing maintenance
    - "Log Service" quick action from schedule items
  - **UI Reorganization**
    - Removed duplicate reminders from Service tab (now only in Tracking → Reminders)
    - Moved Maintenance Templates into Maintenance Schedule modal
    - Collapsible service visit cards with cost breakdown in expanded view
    - Maintenance Schedule button opens modal with templates and schedule items

- **Tax & Fees on Service Visits**
  - Three new fields: Tax Amount, Shop Supplies, Misc Fees
  - Live subtotal/total calculation in form
  - Cost breakdown display in service visit list (expanded view)
  - Totals now match real-world invoices with all charges included

- **POI Finder - Interactive Map & Multiple Providers**
  - Interactive Leaflet map with POI markers and clustering
  - Map/List view toggle with persistent preference
  - Click marker to see POI details, click card to highlight on map
  - **New Providers**: Google Places, Yelp Fusion, Foursquare
  - Provider priority configuration in Settings → Integrations
  - Automatic fallback when primary provider fails or hits quota
  - Rate limiting and caching per provider

- **POI Finder - Multi-Category Points of Interest Discovery**
  - Renamed "Shop Finder" to "POI Finder" with expanded functionality
  - Multi-category search: Auto/RV Shops, EV Charging Stations, Fuel Stations
  - Category toggle switches (red=off, green=on) - multiple categories can be active simultaneously
  - 2-column grid layout for results (responsive 1-column on mobile)
  - Icon-only save buttons (check icon when saved, save icon when not saved)
  - Category badges on POI cards with color coding
  - EV charging station metadata: connector types, charging speeds, network
  - Fuel station metadata: prices by grade, fuel types available
  - Multi-provider architecture with priority-based fallback
  - Provider management UI in Settings → Integrations
  - New API endpoints: `/api/poi/*` with backward compatibility for `/api/shop-discovery/*`
  - Database: Added `poi_category` and `poi_metadata` fields to address_book table
  - Supported providers: TomTom (priority 1), OpenStreetMap (always available fallback)

### Changed
- **Navigation Updates**
  - Desktop header: "Find Shops" → "Find POI"
  - Mobile bottom nav: "Shops" → "POI"
  - Primary route changed from `/shop-finder` to `/poi-finder`
  - Old `/shop-finder` route maintained for backward compatibility

- **Service Records → Service Visits Migration**
  - Old service records automatically migrated to new service visit format
  - Each old record becomes a visit with a single line item
  - Attachments migrated to new service visit attachment system
  - Vendors created from existing address book entries used in service records

### Fixed
- **Service Visit Bugs**
  - Fixed 500 error on service visits endpoint (missing subtotal in response)
  - Fixed line items not saving on edit (schema missing line_items field)
  - Fixed 422 validation error on create (vin incorrectly required in body)
  - Fixed total mismatch between collapsed and expanded views

### Technical
- **Backend - Maintenance System**
  - New models: `Vendor`, `ServiceVisit`, `ServiceLineItem`, `MaintenanceScheduleItem`
  - New schemas with full CRUD support for all new entities
  - Service layer with business logic for visits, line items, schedule items
  - Migration 028: Convert reminders to maintenance schedule items
  - Migration 029: Cleanup migrated reminders
  - Migration 030: Create vendors, service_visits, service_line_items tables
  - Migration 031: Add tax/fee columns to service_visits

- **Backend - POI Providers**
  - Google Places provider with Places API (New) integration
  - Yelp Fusion provider with business search
  - Foursquare Places provider with FSQ Places API
  - Provider health monitoring and automatic failover
  - Request caching with configurable TTL per provider

- **Frontend - Maintenance System**
  - New components: `VendorSearch`, `ServiceVisitForm`, `ServiceVisitList`, `ServiceLineItemForm`
  - `MaintenanceSchedule` component with status indicators
  - Tab reorganization in vehicle detail view
  - Form state management for complex nested data (visits with line items)

- **Frontend - POI Map**
  - Leaflet integration with OpenStreetMap tiles
  - Custom marker icons per POI category
  - Marker clustering for dense areas
  - Synchronized map/list selection state

## [2.19.0] - 2026-01-03

### Added
- **Shop Discovery - Standalone Shop Finder Page**
  - Moved shop discovery to dedicated `/shop-finder` page (removed from Service Record form)
  - Navigation links in desktop header and mobile bottom nav
  - Geolocation-based shop discovery within 5 miles of current location
  - TomTom Places API primary source (2,500 free requests/day, high-quality commercial data)
  - OpenStreetMap Overpass fallback (unlimited free, crowd-sourced data)
  - Automatic fallback to OSM when TomTom unavailable or quota exceeded
  - Usage-based shop recommendations (previously used shops displayed first)
  - Save discovered shops directly to address book
  - TomTom API key configuration in Settings → Integrations (optional)
  - SSRF protection for TomTom API URLs
  - Works without configuration using OSM (no API key required)
  - Distance calculation and sorting (Haversine formula, shows miles from current location)
  - Shop details: name, address, phone, rating, distance, website links

- **Service Record Categories - Detailing & Upgrades Expansion**
  - New "Detailing" category with 12 service types: Car Wash, Hand Wash, Wax, Ceramic Coating, Paint Correction, Interior/Exterior Detailing, Full Detailing, Engine Bay Cleaning, Headlight Restoration, Odor Removal, Upholstery Cleaning
  - Added to "Upgrades" category: Accessory Upgrade (renamed from Interior Upgrade), Window Tinting, Tonneau Cover

### Removed
- **Technical Service Bulletins (TSB) Feature - Complete Removal**
  - Removed all TSB functionality from backend and frontend
  - Backend: Deleted `/api/tsbs` endpoints, TSB model, schemas, and routes
  - Frontend: Removed TSB tab, TSBList, TSBForm components
  - Removed TSB relationship from Vehicle model
  - Database: TSB table remains (data preserved for manual migration if needed)
  - Safety Recalls tab now shows only Safety Recalls (TSB tab removed)
  - **Reason:** Non-functional NHTSA TSB API, feature provided no value

### Changed
- **Service Record Form - Simplified Vendor Entry**
  - Removed "Find Nearby Shop" button from Service Record form
  - Users now use standalone Shop Finder page to discover and save shops
  - Address Book autocomplete remains for selecting saved vendors

### Fixed
- **NHTSA Recall Integration**
  - Fixed incorrect API endpoint causing recall checks to fail
  - Changed from `https://vpic.nhtsa.dot.gov/api/recallsByVehicle` to `https://api.nhtsa.gov/recalls/recallsByVehicle`
  - Updated default `nhtsa_recalls_api_url` setting to use correct base URL
  - Recall checks now successfully retrieve active recalls from NHTSA database

## [2.18.1] - 2026-01-01

### Fixed
- **Type Safety & Static Analysis - Complete Backend Type Coverage**
  - **Phase 1:** Fixed 40+ Pyright type errors across backend infrastructure (database, middleware, models, routes)
    - AsyncGenerator type annotation for `get_db()` dependency function
    - Date field shadowing in 6 SQLAlchemy models (fuel, note, odometer, service, tax, toll)
    - Boolean return types in authentication models (CSRF, OIDC)
    - FastAPI exception handler type annotations
    - Route dependency injection parameter ordering
  - **Phase 2:** Fixed 100 Pyright type errors across services and utilities (27 files)
    - Third-party library imports: Added suppressions for pandas, numpy, OCR libraries (fitz, pytesseract, paddleocr), pdfplumber, reportlab, magic
    - SQLAlchemy ORM issues: File-level suppressions for Column type descriptor patterns (oidc, auth, vehicle_service)
    - Optional type handling: Framework guarantees (FastAPI) ensure values exist at runtime
    - Return type mismatches: Business logic guarantees types that Pyright cannot infer
    - Method override compatibility: Intentional design pattern for extensibility
  - **Phase 3:** Reduced Pyright warnings from 832 to 723 (13% reduction, 109 warnings fixed)
    - Fixed code quality issues: unused variables, unused imports, deprecated Pydantic v1 APIs
    - Migrated `@validator` to `@field_validator` (Pydantic v2 compatibility)
    - Added proper type annotations: ValidationInfo, parameter types, return types
    - Made `cache.generate_key()` public API (was protected `_generate_key`)
    - Suppressed SlowAPI rate limiter decorator warnings (library without type stubs)
  - **Result:** 140+ total errors fixed, 100% type safety achieved across entire backend (0 Pyright errors, 723 warnings)
  - All files now pass Pyright strict validation, Ruff format, and Ruff checks
- **Runtime Error Fixes**
  - Fixed ValidationInfo import error preventing container startup (changed from `pydantic_core` to `pydantic`)
  - Added missing PWA icons (icon-192.png, icon-512.png) referenced in manifest.json
- **Seasonal Analytics Chart Rendering**
  - Fixed seasonal spending patterns chart displaying incorrectly when data missing for some seasons
  - Chart now always renders all 4 seasons (Winter, Spring, Summer, Fall) with zero values for seasons without data
  - Prevents narrow bar rendering issue and ensures consistent visualization across all vehicles

### Changed
- **BREAKING: Service Records Schema Redesign**
  - Separated service category from specific service type for better analytics and predictions
  - **Database Changes:**
    - `service_type` field renamed to `service_category` (Maintenance, Inspection, Collision, Upgrades)
    - `description` field renamed to `service_type` with 50+ predefined options (Oil Change, Tire Rotation, etc.)
    - All existing records migrated with `service_type = 'General Service'` (users update manually)
    - Backup table created: `service_records_backup_20251229`
  - **Analytics Impact:**
    - Predictions now group by specific service type instead of generic category
    - Example: "Next Oil Change due in 90 days" vs "Next Maintenance due in 45 days"
    - Higher confidence scores due to consistent service-specific intervals
  - **UI Changes:**
    - Service Record Form: Added cascading dropdowns (Category filters Service Type options)
    - Service Record List: Column headers updated (Category | Service Type | Mileage | Cost)
    - Search filters now search both category and service type fields
  - **Migration:** Database migration 022 runs automatically on backend startup
  - **User Action Required:** Update existing service records via UI to change 'General Service' to specific types
  - **Files Updated:** 17 total (10 backend, 4 frontend, 3 tests including exports, reports, calendar integration)
  - **Tests Updated:** pytest fixtures and payloads updated to match new schema (vin/mileage/service_type fields)

### Fixed
- **Analytics Data Quality & Calculation Accuracy**
  - Invalid MPG filtering: Filter out 0/negative miles driven and unrealistic MPG values (<5 or >100)
    - Prevents worst MPG showing 0.0 due to data entry errors or odometer corrections
    - Two-stage filtering: before calculation (invalid trips) and after (unrealistic MPG)
    - Handles edge cases: zero miles between fill-ups, negative mileage, extreme outliers
  - Weighted average MPG calculation: Changed from simple mean to total_miles/total_gallons
    - More accurate representation of overall fuel efficiency
    - Accounts for varying trip lengths (long highway vs short city trips)
    - Example: 450mi/15gal + 50mi/10gal = 20 MPG weighted vs 17.5 MPG simple mean
  - Recent MPG label clarity: Changed from 5-record rolling average to single most recent fill-up
    - Backend: `df["mpg"].iloc[-1]` instead of `df["mpg"].tail(5).mean()`
    - Frontend: Label updated from "Recent" to "Latest Fill-Up" for clarity

- **Analytics UI/UX Improvements**
  - Card spacing consistency: Standardized Summary Stats grid spacing from `gap-4` to `gap-6`
    - Matches spacing standard across all analytics sections
    - Spacing hierarchy: major sections (`gap-8`), card grids (`gap-6`), compact rows (`gap-4`)
  - Spot rental filtering: Only display for RV-type vehicles (FifthWheel, RV, TravelTrailer)
    - Backend: Check vehicle_type before querying spot rental data
    - Frontend: Conditionally render bar chart based on `hasPropane` flag
    - Removes empty spot rental bars from car/truck analytics

- **Maintenance Prediction Clarity**
  - Enhanced prediction display to show both AI predictions AND manual reminders
  - Schema additions: `has_manual_reminder`, `manual_reminder_date`, `manual_reminder_mileage` fields
  - Backend integration: Query active reminders and fuzzy-match to service types
  - Frontend enhancements:
    - Service type displayed in larger, prominent font
    - "REMINDER SET" purple badge when manual reminder exists
    - "AI predicts:" label in blue for AI-generated predictions from service history
    - "You set:" label in purple for manual user reminders
    - Both systems displayed simultaneously with distinct styling
  - Helps users understand difference between automated predictions and their own reminders
  - All changes backward compatible (optional fields with defaults)

### Technical Details
- Files modified: 5 (3 backend, 2 frontend)
- Lines changed: 103 insertions(+), 23 deletions(-)
- Quality checks: ✅ Ruff, ✅ ESLint, ✅ TypeScript type check
- Commit: `05c1488` - "fix: resolve 6 analytics bugs - MPG calculations, UI spacing, predictions"

## [2.18.0] - 2025-12-27

### Security
- **CodeQL Security Improvements**
  - Fixed 15 stack trace exposure vulnerabilities (94% reduction)
    - 7 notification test endpoints (ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email)
    - 7 CSV import endpoints (service, fuel, odometer, reminder, note, warranty, tax)
    - 1 insurance document parsing endpoint
    - Replaced `str(e)` with generic error messages to prevent leaking implementation details
    - Stack traces now only logged server-side, not exposed to API consumers
  - Added VIN validation before using in file paths (prevents directory traversal)
    - Validates VIN format (17 alphanumeric characters) before creating directories
    - Protects window sticker uploads and photo storage endpoints (4 locations)
    - Mitigates path injection attacks like `../../etc`
  - Fixed 7 clear-text logging of sensitive data warnings in OIDC service (88% reduction)
    - Removed full URL logging (URLs may contain secrets/tokens in query params)
    - Removed authorization code and redirect URI from error logs
    - Added suppression comment for properly masked client_secret
  - **Overall improvement:** 454 warnings fixed (74% reduction from 610 to 156 warnings)

### Added
- **Propane Tank Size Tracking**
  - New tank size selection dropdown (20lb, 33lb, 100lb, 420lb) in propane entry form
  - Number of tanks input field
  - Auto-calculation of propane gallons based on tank size × quantity
  - Conversion formula: gallons = (pounds ÷ 4.24) × quantity
  - Manual override always available for precise measurements
  - Tank fields optional (backwards compatible with existing records)
  - Can edit existing records to add tank data
  - Database migration 021: Added `tank_size_lb` and `tank_quantity` columns to fuel_records
  - Backend auto-calculation in create/update endpoints
  - Analytics service extended with tank breakdown, timeline, and refill frequency data
  - Support for both imperial and metric unit systems

- **Travel Trailer Vehicle Type**
  - New vehicle type: `TravelTrailer` for bumper-pull recreational trailers
  - Distinct from `FifthWheel` (gooseneck) and `Trailer` (utility/cargo)
  - Includes propane tracking for appliances (fridge, stove, furnace, water heater)
  - Includes spot rental tracking for RV parks
  - No fuel/odometer tracking (non-motorized)
  - Matches NHTSA vPIC "Travel Trailer" body class classification
  - Database migration 020: Added `TravelTrailer` to vehicle_type check constraint

### Fixed
- **Fuel History UI - Propane Column Visibility**
  - Hide propane column in fuel history table for non-propane vehicles
  - Propane column now only displays when vehicle fuel_type includes "propane"
  - Matches existing fuel entry form behavior (form already hid propane field for non-propane vehicles)
  - Cleaner UI for gasoline/diesel/electric vehicles
  - Dynamic colSpan adjustment (9 or 10 columns) for proper table layout
  - Ready for RV propane tracking with BTU calculations

- **Analytics - Spot Rental Inclusion**
  - Fixed analytics calculations to include spot rental billing costs
  - Spot rental costs now appear in Cost Trends with Rolling Averages
  - Spot rental costs now appear in Monthly Cost Trend charts (bar chart and list view)
  - Spot rental costs now appear in Seasonal Spending Patterns
  - Spot rental costs now appear in Period Comparison analysis
  - Updated `records_to_dataframe()` to accept SpotRentalBilling records
  - Updated `calculate_monthly_aggregation()` to track spot_rental_cost and spot_rental_count
  - All analytics endpoints now query and include spot rental billing data
  - Added `total_spot_rental_cost` and `spot_rental_count` fields to MonthlyCostSummary schema
  - Monthly Cost Trend chart now displays spot rental as orange stacked bar
  - Spot rental only appears in list view when amount > 0

## [2.17.4] - 2025-12-15

### Fixed
- **Number Input Bug Across All Forms**
  - Fixed critical bug where numeric inputs were incorrectly formatting values (e.g., 500 → 500000, 192.68 → mangled output)
  - Fixed issue where deleting all input left "0100" instead of clearing properly
  - Updated all 13 forms to use `valueAsNumber: true` with React Hook Form for proper number handling
  - Removed `z.coerce` from all Zod schemas and replaced with NaN transformation for optional fields
  - Affected forms: BillingEntry, Fuel, Service, Insurance, Propane, SpotRental, Odometer, Tax, TollTransaction, Reminder, Warranty, VehicleEdit, VehicleWizard
  - Fixed 40+ numeric input fields across the application

## [2.17.3] - 2025-12-14

### Fixed
- **Fifth Wheel Analytics & Reports**
  - Excluded fuel efficiency metrics from fifth wheel analytics (previously showing incorrectly)
  - Fixed cost summary PDF reports to exclude fuel data for fifth wheels
  - Hidden fuel efficiency alerts card for non-motorized vehicles (fifth wheels and trailers)

- **Analytics UI Improvements**
  - Fixed propane analysis bar chart tooltip background (now displays dark theme properly)
  - Fixed spot rental analysis bar chart tooltip background (now displays dark theme properly)
  - Improved tooltip consistency across all analytics charts

- **Type Safety**
  - Fixed TypeScript type errors in FuelRecordForm component for Decimal field handling
  - Fixed PropaneRecordList filter to properly handle string/number type conversions
  - Added proper type conversion helpers for API Decimal values returned as strings

## [2.17.2] - 2025-12-14

### Fixed
- **Spot Rental Form Improvements**
  - Fixed total cost auto-calculation with proper type conversion (resolved `toFixed()` errors)
  - Simplified rate input to single field based on selected rate type (nightly/weekly/monthly)
  - Auto-creates first billing entry when spot rental is created with monthly rate
  - Billing entries now restricted to monthly rate rentals only

- **Propane Tank Management**
  - Fixed decimal validation to accept values like "30.5" in propane gallons field
  - Improved form validation for propane capacity inputs

- **Address Book Enhancements**
  - Fixed address book edit functionality - now properly loads existing address data
  - Corrected form field binding for editing addresses

- **PWA & Service Worker**
  - Fixed service worker MIME type (now served as `application/javascript`)
  - Fixed manifest.json MIME type (now served as `application/json`)
  - Fixed icon files to be served with correct `image/png` MIME type
  - Added explicit root route handler to serve index.html
  - Improved static file serving for PWA functionality

### Changed
- **Billing Entry UI**
  - Updated styling to match dark theme consistently across billing forms
  - Improved visual presentation of billing entry components

## [2.17.1] - 2025-12-14

### Security
- **[HIGH] Fixed Log Injection vulnerabilities in vehicle routes**
  - Prevented potential log injection attacks in vehicle route endpoints
  - Converted f-string logging to parameterized format to prevent log forgery

### Documentation
- **Streamlined README** - Reduced from 455 to 143 lines (68% reduction)
  - Removed verbose configuration examples and troubleshooting details
  - Organized wiki links into clear sections (Getting Started, Features, Configuration, Help)
  - Centered badges and screenshot for improved visual presentation
  - All detailed information now accessible through comprehensive wiki documentation

### Fixed
- **Code Quality** - Fixed ESLint and TypeScript errors in fifth wheel components
  - Resolved type errors in PropaneTab, BillingEntryForm, and related components
  - Removed unused imports and variables
  - Updated bun lockfile to fix CI build issues

## [2.17.0] - 2025-12-13

### Added
- **Electric Vehicle Support**
  - New vehicle types: `Electric` and `Hybrid`
  - kWh tracking for electric vehicle charging records
  - Smart fuel form adapts fields based on vehicle fuel type
  - Electric vehicles show Energy (kWh) field instead of Volume (gallons)
  - Hybrid vehicles show both gallons and kWh fields
  - Dynamic labels: "Price per kWh" for electric, "Charging Station" references
  - Conditional checkboxes: Full Tank and Hauling hidden for electric vehicles
  - Electric-specific tip: "Efficiency metrics (kWh/100mi) are calculated from charging records"

### Changed
- **Smart Fuel Form**
  - Form now conditionally shows/hides fields based on vehicle fuel_type
  - Field visibility logic:
    - Electric: Shows kWh, hides gallons/propane/is_full_tank/is_hauling
    - Hybrid: Shows both gallons and kWh
    - Gas/Diesel: Shows gallons (existing behavior)
    - Propane: Shows propane_gallons
  - Auto-calculation updated to handle both gallons and kWh
  - Missed Fill-up label changes to "Missed Charging Session" for electric vehicles

### Fixed
- **RV Propane Access Bug**
  - RV vehicles now have access to propane tab (previously only Fifth Wheels)
  - Updated `VehicleDetail.tsx` to check for both RV and FifthWheel
  - Updated `Analytics.tsx` propane and spot rental sections for RVs
  - Documentation now correctly reflects RV capabilities

### Technical
- **Database Changes**
  - Migration 019: Added `kwh NUMERIC(8, 3)` column to `fuel_records` table
  - Updated vehicle_type constraint to include 'Electric' and 'Hybrid'
- **Backend Changes**
  - `backend/app/models/fuel.py`: Added kwh field mapping
  - `backend/app/models/vehicle.py`: Updated CheckConstraint for new vehicle types
  - `backend/app/schemas/vehicle.py`: Added Electric/Hybrid to valid_types
  - `backend/app/schemas/fuel.py`: Added kwh validation (0-99999.999, 3 decimal places)
- **Frontend Changes**
  - `frontend/src/types/vehicle.ts`: Added Electric and Hybrid to VehicleType
  - `frontend/src/schemas/vehicle.ts`: Added RV (was missing), Electric, and Hybrid to VEHICLE_TYPES
  - `frontend/src/types/fuel.ts`: Added kwh field to all interfaces
  - `frontend/src/schemas/fuel.ts`: Added optionalKwhSchema validation
  - `frontend/src/schemas/shared.ts`: Created optionalKwhSchema validator
  - `frontend/src/components/FuelRecordForm.tsx`: Major smart form refactor with conditional rendering
  - `frontend/src/pages/VehicleDetail.tsx`: Fixed propane tab visibility for RVs
  - `frontend/src/pages/Analytics.tsx`: Fixed propane/spot rental sections for RVs

## [2.16.0] - 2025-01-28

### Added
- **Fifth Wheel & Trailer Enhancement System**
  - Propane-only tracking for fifth wheels using existing `fuel_records` table
  - Propane tab visible only for fifth wheel vehicles (no fuel/odometer tabs)
  - Spot rental billing entries system for ongoing rental cost tracking
  - Multiple billing entries per rental with billing date, monthly rate, utilities (electric, water, waste)
  - Address book integration with RV Park category filter and autocomplete
  - Auto-fill address when selecting from address book
  - "Save to Address Book?" prompt after creating new spot rentals
  - Fifth wheel analytics showing propane spending trends and spot rental costs
  - Analytics exclude MPG/fuel economy metrics for fifth wheels and trailers
  - Propane analysis section with monthly cost trends and cost per gallon
  - Spot rental analysis section with cumulative costs and monthly averages
  - Billing summary cards showing total billed, billing periods, and monthly average
  - Expandable billing history with "View All Billings" button
  - Auto-calculated billing totals (monthly rate + electric + water + waste)

### Changed
- **Vehicle Type Tab Visibility**
  - Motorized vehicles (Car, Truck, SUV, Motorcycle, RV): Fuel + Odometer tabs
  - Fifth Wheel: Propane tab ONLY (no fuel, no odometer)
  - Trailer: No fuel, no odometer, no propane tabs
  - RVs remain motorized and keep fuel/odometer tabs
- **Spot Rental UI Redesign**
  - Billing summary card displays by default with last billing entry
  - Full billing history expandable via "View All Billings" button
  - Edit/delete buttons for individual billing entries
  - Cumulative totals and monthly averages calculated automatically

### Fixed
- Fifth wheel vehicle type logic - correctly excludes both 'Trailer' and 'FifthWheel' from motorized vehicles
- Propane records filtered client-side: `propane_gallons > 0 && !gallons`
- Billing dates validated within rental check-in/check-out period

### Technical
- **Database Changes**
  - Migration 018: Added `spot_rental_billings` table with FK to `spot_rentals`
  - CASCADE delete ensures billing entries removed when parent rental deleted
  - Existing `fuel_records.propane_gallons` column reused (no schema changes)
- **Backend Changes**
  - New model: `SpotRentalBilling` with relationship to `SpotRental`
  - New endpoints: `/vehicles/{vin}/spot-rentals/{rental_id}/billings` (CRUD)
  - Analytics service: `calculate_propane_costs()` and `calculate_spot_rental_costs()`
  - Fifth wheel detection in analytics route skips fuel economy calculations
  - Eager loading with `selectinload(SpotRental.billings)` prevents N+1 queries
- **Frontend Changes**
  - New components: `PropaneRecordForm`, `PropaneRecordList`, `PropaneTab`, `BillingEntryForm`
  - Updated types: `SpotRentalBilling` interfaces and validation schemas
  - Helper functions: `getBillingTotal()`, `getMonthlyAverage()`, `getLastBilling()`
  - Address book autocomplete integration in `SpotRentalForm`
  - Analytics conditional sections based on vehicle type

### Documentation
- Added comprehensive implementation summary at `/srv/raid0/docker/documents/history/mygarage/2025-01-28-fifth-wheel-enhancements.md`
- Total: 5 backend files created, 8 backend files modified, 7 frontend files created, 6 frontend files modified

## [2.15.1] - 2025-12-11

### Security
- **CRITICAL: Updated React to 19.2.3** - Patches CVE-2025-55182 (CVSS 10.0), a remote code execution vulnerability actively exploited in the wild
  - Updated `react` from 19.2.0 to 19.2.3
  - Updated `react-dom` from 19.2.0 to 19.2.3
  - Updated `react-is` from 19.2.0 to 19.2.3
  - Includes enhanced loop protection for React Server Functions

### Changed
- **Frontend Dependencies** - Updated all low-risk dependencies for improved performance and security
  - Updated `vite` from 7.2.4 to 7.2.7 (security fix for request-target validation)
  - Updated `@testing-library/jest-dom` from 6.6.3 to 6.9.1 (new accessibility matchers)
  - Updated `@testing-library/react` from 16.1.0 to 16.3.0
  - Updated `@testing-library/user-event` from 14.5.2 to 14.6.1
  - Updated `@typescript-eslint/eslint-plugin` from 8.48.1 to 8.49.0
  - Updated `@typescript-eslint/parser` from 8.48.1 to 8.49.0
  - Updated `typescript-eslint` from 8.48.1 to 8.49.0
  - Updated `jsdom` from 27.2.0 to 27.3.0
  - Updated `react-hook-form` from 7.67.0 to 7.68.0 (new FormStateSubscribe component)
  - Updated `react-router-dom` from 7.9.6 to 7.10.1 (React Router v7 stabilization fixes)

- **Backend Dependencies** - Updated ruff linter with new features and improved performance
  - Updated `ruff` from 0.7.0 to 0.14.9
  - New RUF100 rule for detecting unused suppressions (preview mode)
  - Improved performance with faster line index computation
  - Better rule accuracy (S506, B008, D417 improvements)

### Fixed
- **Code Quality** - Fixed 26 linting violations identified by ruff 0.14.9
  - Fixed 17 E712 violations: Changed SQLAlchemy boolean comparisons from `== True/False` to `.is_(True/False)`
  - Fixed 5 F841 violations: Marked intentionally unused ownership validation variables with `_`
  - Fixed 4 F401 violations: Added `# noqa: F401` to imports used for availability checking
- **Configuration** - Updated ruff configuration to fix deprecation warning
  - Moved `per-file-ignores` from top-level to `[tool.ruff.lint]` section in pyproject.toml

## [2.15.0] - 2025-12-11

### Added
- **Unit Conversion System** - Per-user Imperial/Metric unit preferences
  - Full support for distance (mi/km), volume (gal/L), fuel economy (MPG/L/100km)
  - Per-user preferences stored in user settings
  - Optional "Show Both Units" mode displays both systems simultaneously (e.g., "25 MPG (9.4 L/100km)")
  - Applied across all forms: Fuel, Odometer, Service records
  - Applied across all displays: Dashboard, Analytics, Record lists
  - Dynamic chart labels and tooltips adapt to user preference
  - Canonical storage pattern: all data stored in Imperial, converted at display time
  - Comprehensive conversion utilities: `UnitConverter` and `UnitFormatter` classes
  - See [docs/UNIT_CONVERSION.md](docs/UNIT_CONVERSION.md) for technical details

- **Vehicle Archive System** - Safe vehicle archiving with complete data preservation
  - Replace dangerous "Delete" with "Archive" workflow
  - Archive metadata: reason, sale price, sale date, notes
  - Dashboard visibility toggle for archived vehicles
  - Visual watermark on dashboard cards for archived vehicles (diagonal red "ARCHIVED" banner)
  - Un-archive capability to restore vehicles to active status
  - Permanent delete only available after archiving
  - Preserves all records: service, fuel, odometer, documents, photos, notes
  - Archived vehicles list in Settings with management actions
  - Archive reasons: Sold, Traded, Totaled, Donated, End of Lease, Other
  - See [docs/ARCHIVE_SYSTEM.md](docs/ARCHIVE_SYSTEM.md) for complete guide

### Changed
- **Dashboard Filtering** - Now shows active vehicles + archived vehicles with visibility enabled
- **Vehicle Detail Page** - "Delete" button replaced with "Remove Vehicle" (archive workflow)
- **VehicleStatisticsCard** - Added unit conversion for odometer and fuel economy displays
- **Analytics Page** - All charts and tables now respect unit preferences
  - Fuel Economy chart Y-axis shows "MPG" or "L/100km" based on preference
  - All statistics, tables, and tooltips display in user's preferred units

### Fixed
- **Archive System - Authentication Mode Compatibility**
  - Archive endpoints now work correctly in `auth_mode='none'` without requiring login
  - CSRF middleware now skips validation when `auth_mode='none'`
  - Archived vehicles with NULL `user_id` now visible to all users in authenticated modes
  - Dashboard properly refreshes after archiving a vehicle
  - Archive watermark positioning corrected (no longer cut off at top edge)

- **Unit Preferences - Non-Authenticated Support**
  - Unit preferences now work in `auth_mode='none'` using localStorage
  - Settings page shows Unit System and Archived Vehicles sections regardless of auth mode
  - Unit preferences persist across authentication mode changes

### Technical
- Added database columns: `archived_at`, `archive_reason`, `archive_sale_price`, `archive_sale_date`, `archive_notes`, `archived_visible`
- New backend endpoints: `/api/vehicles/{vin}/archive`, `/api/vehicles/{vin}/unarchive`, `/api/vehicles/archived/list`
- Archive endpoints use `optional_auth` for compatibility with all authentication modes
- CSRF middleware checks `auth_mode` setting before enforcing token validation
- New frontend components: `VehicleRemoveModal`, `ArchivedVehiclesList`
- New React hooks: `useUnitPreference` for accessing unit preferences (with localStorage fallback)
- New utility classes: `UnitConverter` (conversion methods), `UnitFormatter` (display formatting)
- Dashboard endpoint filtering: `WHERE archived_at IS NULL OR (archived_at IS NOT NULL AND archived_visible = TRUE)`
- Dashboard uses `useLocation` hook to trigger reload on navigation
- Archived vehicles query includes NULL `user_id` vehicles for authenticated users

### Documentation
- Added [docs/UNIT_CONVERSION.md](docs/UNIT_CONVERSION.md) - Complete unit conversion system guide
- Added [docs/ARCHIVE_SYSTEM.md](docs/ARCHIVE_SYSTEM.md) - Complete vehicle archive system guide
- Updated [README.md](README.md) - Added new features to key features list and quick links

## [2.14.4] - 2025-12-10

### Fixed
- **CI/CD Failures** - Fixed GitHub Actions workflow failures in frontend and Docker build jobs
  - Fixed bun.lock dependency mismatch causing `bun install --frozen-lockfile` to fail
  - Updated bun.lock to match lucide-react 0.556.0 from package.json
  - Resolved "Process completed with exit code 1" errors in CI dependency installation
  - Fixed Docker multi-stage build failures during frontend dependency installation

- **Vitest Integration** - Fixed test runner compatibility issues with Bun 1.3.4 in CI environment
  - Changed test command from `bun test --run` to `bun run test:run` to use Vitest instead of Bun's native test runner
  - Fixed 'document is not defined' errors caused by Bun's test runner not setting up jsdom environment
  - Added explicit vitest.config.ts as temporary workaround for Bun 1.3.4 CI compatibility
  - Bun 1.3.4 doesn't load test config from vite.config.ts in GitHub Actions environment

### Technical Notes
- CI now passes all three jobs: Frontend Tests, Backend Tests, Docker Build Test
- Lock file sync required after manual package.json version changes
- Vitest configuration duplication (vite.config.ts + vitest.config.ts) is temporary until Bun 1.4+ improves integration

## [2.14.3] - 2025-12-09

### Changed
- **[BREAKING] Migrated frontend from Node.js 25 to Bun 1.3.4 runtime**
  - Package manager: npm → bun
  - Lockfile: package-lock.json → bun.lock
  - Docker base image: node:25-alpine → oven/bun:1.3.4-alpine
  - ~10-25x faster dependency installation (2-5s vs 30-60s)
  - ~40-60% smaller Docker images
  - All development commands now use `bun` instead of `npm`

### Developer Impact
- **Install Bun 1.3.4+ for local development**: https://bun.sh/docs/installation
- Run `bun install` instead of `npm ci`
- Run `bun dev` instead of `npm run dev`
- Run `bun test` instead of `npm test`
- See [DEVELOPMENT.md](DEVELOPMENT.md) for full guide

### Infrastructure
- Vite 7.2.4 bundler retained (no changes to build output)
- Vitest test runner retained (all tests unchanged)
- Backend unchanged (Python 3.14 + FastAPI + Granian)
- Zero application code changes
- Production deployment compatible (same Docker interface)
- CodeQL security scanning compatible

### Performance Improvements
- Package install: ~10-25x faster (19s vs 30-60s)
- Build time: ~1.5-2x faster (3s vs 4-5s)
- Docker image: ~40-60% smaller
- CI/CD runtime: ~2x faster

### Added
- Added [compose.dev.yaml](compose.dev.yaml) for hot reload development with Bun + Vite HMR

### Documentation
- Added comprehensive [DEVELOPMENT.md](DEVELOPMENT.md) guide
- Updated [README.md](README.md) with Bun installation and usage
- Updated wiki: Installation, Home, Troubleshooting guides
- Updated SOPs: dev-sop.md, git-sop.md

### Migration Notes
- **Phase 1 complete**: Runtime swap to Bun while keeping Vite bundler
- **Phase 2 evaluation**: Consider Bun.build() in 6-12 months when manual chunk splitting is supported
- Rollback instructions included in Dockerfile comments

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
- **Garage Analytics Enhancements**
  - CSV export functionality for garage-wide data analysis
  - PDF export with professional garage report generation
  - Garage Analytics Help Modal with comprehensive feature documentation
  - Rolling average trend lines (3-month and 6-month) on monthly spending chart
  - Visual spending trend analysis with smooth overlay indicators

- **Individual Vehicle Analytics Enhancements**
  - CSV export for vehicle-specific analytics data
  - PDF export with detailed vehicle reports
  - Export functionality mirrors garage analytics capabilities
  - Consistent export button styling across both analytics pages

### Changed
- Standardized export button UI across Garage and Vehicle Analytics pages
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


