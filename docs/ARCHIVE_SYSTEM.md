# Vehicle Archive System

MyGarage includes a comprehensive vehicle archiving system that allows users to remove vehicles from active use while preserving all historical data, records, and documents.

## Overview

The archive system provides a safe alternative to deletion, allowing you to:
- Remove sold, traded, or retired vehicles from your active fleet
- Preserve complete maintenance history, photos, and documents
- View archived vehicles separately when needed
- Toggle visibility of archived vehicles on the main dashboard
- Un-archive vehicles if needed (e.g., if you buy the vehicle back)
- Permanently delete archived vehicles when you're ready

### Key Differences: Archive vs Delete

| Action | Data Retention | Reversible | Dashboard Visibility | Historical Records |
|--------|---------------|------------|---------------------|-------------------|
| **Archive** | All data kept | Yes (can un-archive) | Optional | Preserved |
| **Delete** | All data removed | No (permanent) | Removed | Lost forever |

## User Interface

### Archiving a Vehicle

1. Navigate to the vehicle's detail page
2. Click the **"Remove Vehicle"** button (red, bottom of page)
3. A modal dialog appears with archive options
4. Fill in the archive details:
   - **Archive Reason**: Why the vehicle is being removed (required)
     - Sold
     - Traded
     - Totaled/Accident
     - Donated
     - End of lease
     - Custom reason
   - **Sale Price**: The amount the vehicle sold for (optional)
   - **Sale Date**: Date the vehicle was sold/removed (optional, defaults to today)
   - **Additional Notes**: Any other relevant information (optional)
   - **Show on Dashboard**: Toggle to control visibility
5. Click **"Archive Vehicle"** to confirm

**Important**: The "Remove Vehicle" button replaces the old "Delete" button. Deletion is now only available through the Archived Vehicles section.

### Dashboard Watermark

When a vehicle is archived with "Show on Dashboard" enabled:
- The vehicle card displays a diagonal red **"ARCHIVED"** watermark
- The watermark overlays the vehicle photo with semi-transparent background
- All vehicle data remains accessible by clicking the card
- Archived vehicles appear in their normal position based on sorting

**Visual Design:**
- Red text: `#DC2626` (red-600)
- Semi-transparent background: 20% opacity
- Diagonal orientation: 45° rotation
- Positioned top-right of vehicle photo
- Non-interactive (doesn't block clicking the card)

### Viewing Archived Vehicles

Navigate to **Settings → Archived Vehicles** to see all archived vehicles.

The Archived Vehicles list shows:
- Vehicle year, make, and model
- VIN
- Archive date
- Archive reason
- Sale price (if provided)
- Dashboard visibility status
- Action buttons (View, Un-archive, Delete)

### Un-archiving a Vehicle

To restore an archived vehicle to active status:

1. Go to **Settings → Archived Vehicles**
2. Find the vehicle in the list
3. Click the **"Un-archive"** button
4. Confirm the action
5. The vehicle immediately returns to your active fleet on the dashboard

**Effects of Un-archiving:**
- `archived_at` timestamp is cleared
- `archived_visible` is reset to `true`
- All archive metadata (reason, price, notes) is cleared
- Vehicle appears on dashboard as active
- All records, photos, and documents remain intact

### Permanently Deleting an Archived Vehicle

To permanently delete a vehicle and all its data:

1. First, archive the vehicle using the "Remove Vehicle" button
2. Go to **Settings → Archived Vehicles**
3. Find the vehicle in the archived list
4. Click the red **"Delete"** button
5. Confirm the permanent deletion

**Warning**: This action is **irreversible** and will delete:
- The vehicle record
- All service records
- All fuel records
- All odometer readings
- All service reminders
- All documents
- All notes
- All photos (from filesystem)
- All associated data

Use this feature carefully and only when you're certain you no longer need the vehicle's historical data.

## Archive Metadata

When archiving a vehicle, the system stores the following metadata:

### Database Fields

Located in the `vehicles` table:

| Field | Type | Description |
|-------|------|-------------|
| `archived_at` | TIMESTAMP | When the vehicle was archived (NULL if active) |
| `archive_reason` | TEXT | Reason for archiving (sold, traded, etc.) |
| `archive_sale_price` | DECIMAL | Sale price if applicable |
| `archive_sale_date` | DATE | Date of sale/removal |
| `archive_notes` | TEXT | Additional context or notes |
| `archived_visible` | BOOLEAN | Whether to show on dashboard (default: TRUE) |

### Archive Reasons

Predefined options in the UI:

- **Sold**: Vehicle was sold to another party
- **Traded**: Vehicle was traded in for another vehicle
- **Totaled/Accident**: Vehicle was totaled in an accident
- **Donated**: Vehicle was donated to charity
- **End of Lease**: Lease ended and vehicle returned
- **Other**: Custom reason (requires explanation in notes)

## Technical Implementation

### Database Schema

The archive system uses soft-delete pattern with metadata:

```sql
ALTER TABLE vehicles ADD COLUMN archived_at TIMESTAMP;
ALTER TABLE vehicles ADD COLUMN archive_reason TEXT;
ALTER TABLE vehicles ADD COLUMN archive_sale_price DECIMAL(10, 2);
ALTER TABLE vehicles ADD COLUMN archive_sale_date DATE;
ALTER TABLE vehicles ADD COLUMN archive_notes TEXT;
ALTER TABLE vehicles ADD COLUMN archived_visible BOOLEAN DEFAULT 1;
```

**Active vehicle**: `archived_at IS NULL`
**Archived vehicle**: `archived_at IS NOT NULL`

### Backend API Endpoints

#### Archive a Vehicle
```http
POST /api/vehicles/{vin}/archive
Content-Type: application/json

{
  "reason": "sold",
  "sale_price": 15000.00,
  "sale_date": "2025-12-11",
  "notes": "Sold to private buyer",
  "archived_visible": true
}
```

**Response**: Updated vehicle object with archive fields populated

#### Un-archive a Vehicle
```http
POST /api/vehicles/{vin}/unarchive
```

**Response**: Updated vehicle object with archive fields cleared

#### List Archived Vehicles
```http
GET /api/vehicles/archived
```

**Response**: Array of archived vehicle objects

#### Delete Archived Vehicle
```http
DELETE /api/vehicles/{vin}
```

**Requirements**: Vehicle must be archived first (`archived_at IS NOT NULL`)
**Response**: 204 No Content on success

### Dashboard Filtering Logic

The dashboard endpoint filters vehicles to show:
- All active vehicles (`archived_at IS NULL`)
- Archived vehicles with visibility enabled (`archived_at IS NOT NULL AND archived_visible = TRUE`)

```sql
SELECT * FROM vehicles
WHERE archived_at IS NULL
   OR (archived_at IS NOT NULL AND archived_visible = 1)
ORDER BY year DESC, make, model;
```

### Frontend Components

#### VehicleRemoveModal
Located: `frontend/src/components/VehicleRemoveModal.tsx`

Modal dialog for archiving vehicles with form fields for all archive metadata.

**Features:**
- Form validation with Zod schema
- Date picker for sale date (defaults to today)
- Currency input for sale price
- Textarea for notes
- Toggle for dashboard visibility

#### ArchivedVehiclesList
Located: `frontend/src/components/ArchivedVehiclesList.tsx`

Table displaying all archived vehicles with management actions.

**Features:**
- Sortable columns
- Quick actions (View, Un-archive, Delete)
- Confirmation dialogs for destructive actions
- Display of archive metadata

#### VehicleStatisticsCard
Located: `frontend/src/components/VehicleStatisticsCard.tsx`

Dashboard vehicle card with conditional watermark rendering.

**Watermark Implementation:**
```typescript
{stats.archived_at && (
  <div className="absolute inset-0 pointer-events-none overflow-hidden">
    <div className="absolute top-0 right-0 transform rotate-45
                    translate-x-1/4 -translate-y-1/4
                    bg-red-600/20 text-red-600 font-bold text-2xl
                    px-16 py-2 border-y-2 border-red-600 shadow-lg">
      ARCHIVED
    </div>
  </div>
)}
```

### Vehicle Schema Types

TypeScript interfaces for archived vehicles:

```typescript
interface VehicleResponse {
  vin: string
  // ... other vehicle fields
  archived_at?: string
  archive_reason?: string
  archive_sale_price?: number
  archive_sale_date?: string
  archive_notes?: string
  archived_visible: boolean
}

interface VehicleArchiveRequest {
  reason: string
  sale_price?: number
  sale_date?: string
  notes?: string
  archived_visible?: boolean
}
```

## Data Preservation

When a vehicle is archived, **all data is preserved**:

### Records Preserved
- Service records (with attachments)
- Fuel records
- Odometer readings
- Service reminders (active and completed)
- Documents (with OCR data)
- Notes
- Photos (all images)
- Window sticker data
- VIN decoded information

### Queries Still Work
Archived vehicles can still be queried through the API:
```http
GET /api/vehicles/{vin}
GET /api/vehicles/{vin}/service-records
GET /api/vehicles/{vin}/fuel-records
GET /api/vehicles/{vin}/photos
```

All endpoints continue to function normally for archived vehicles.

### Analytics Impact

When viewing analytics:
- **Vehicle-specific analytics**: Include all data regardless of archive status
- **Fleet-wide analytics**: Only include active vehicles by default
- **Future enhancement**: Filter to include/exclude archived vehicle data

## Use Cases

### 1. Selling a Vehicle
```
1. User lists vehicle for sale
2. Vehicle sells for $15,000 on Dec 11, 2025
3. User clicks "Remove Vehicle" on vehicle page
4. Fills in archive form:
   - Reason: Sold
   - Sale Price: $15,000
   - Sale Date: 12/11/2025
   - Notes: "Sold to John Doe via Craigslist"
   - Show on Dashboard: OFF
5. Vehicle archived and removed from dashboard
6. Historical records preserved for tax/reference purposes
```

### 2. End of Lease
```
1. Lease ends, vehicle returned to dealer
2. User archives with reason "End of Lease"
3. Keeps visible on dashboard to track which vehicles they've had
4. All maintenance records preserved for review
5. Can show future mechanic what service was done if they lease another
```

### 3. Accident/Totaled
```
1. Vehicle is totaled in accident
2. Archive with reason "Totaled/Accident"
3. Notes: "Insurance claim #12345, paid out $20,000"
4. Keep on dashboard to remember the incident
5. All records preserved for insurance/legal purposes
```

### 4. Temporary Storage
```
1. Vehicle stored for winter/deployment
2. Archive to declutter dashboard during storage period
3. Un-archive when bringing vehicle back into service
4. All data remains intact
```

## Best Practices

### When to Archive
- ✅ Vehicle sold or traded
- ✅ Vehicle totaled or destroyed
- ✅ End of lease
- ✅ Vehicle temporarily out of service (long-term storage)
- ✅ Fleet vehicle retired from service

### When to Delete
- ⚠️ Only after archiving and confirming no data needed
- ⚠️ When legal retention periods have passed
- ⚠️ When storage space is critical
- ⚠️ Never for active vehicles

### Dashboard Visibility
- ✅ **Hide** (`archived_visible = false`): Normal use case, declutter dashboard
- ✅ **Show** (`archived_visible = true`): Want to remember past vehicles, sentimental value

### Notes Field
Use the notes field to record:
- Buyer information (if appropriate)
- Insurance claim numbers
- Odometer reading at time of sale/removal
- Condition notes
- Reason for trade/donation
- Any other context that might be useful later

## Migration from Old Delete System

If you're upgrading from a version without the archive system:

1. **Old "Delete" button is replaced** with "Remove Vehicle" (archive)
2. **No data migration needed**: New fields default to NULL for existing vehicles
3. **Existing active vehicles**: Automatically have `archived_at = NULL`, `archived_visible = TRUE`
4. **New workflow**: Must archive before delete is available

## Troubleshooting

### Issue: Can't find archived vehicle on dashboard

**Solution**: Check the "Show on Dashboard" setting in Settings → Archived Vehicles. Toggle it ON to make the vehicle visible.

### Issue: Archived watermark not showing

**Solution**:
1. Verify `archived_at` is set (check in database or API response)
2. Hard refresh the page (Ctrl+Shift+R)
3. Check browser console for errors

### Issue: Want to restore vehicle but already deleted

**Solution**: Unfortunately, permanent deletion is irreversible. You'll need to manually re-enter the vehicle and its data. This is why we recommend always archiving first.

### Issue: Can't delete vehicle, button is disabled

**Solution**: The delete button only appears for archived vehicles. First archive the vehicle, then delete from the Archived Vehicles list.

### Issue: Dashboard shows wrong vehicle count

**Solution**: The dashboard count includes archived vehicles with `archived_visible = true`. To exclude them, toggle "Show on Dashboard" off in Settings → Archived Vehicles.

## Future Enhancements

Potential improvements for future versions:

- [ ] Bulk archive operations (archive multiple vehicles at once)
- [ ] Archive templates (pre-filled reasons for fleet managers)
- [ ] Export archived vehicle data to PDF/JSON before deletion
- [ ] Archive history log (track who archived when)
- [ ] Scheduled archiving (auto-archive vehicles after X days of inactivity)
- [ ] Archive analytics (view trends in fleet turnover)
- [ ] Restore with selective data (un-archive but don't restore certain records)

## API Reference

### Complete Archive Workflow

```bash
# 1. List all active vehicles
curl -X GET "http://localhost:8686/api/vehicles"

# 2. Archive a vehicle
curl -X POST "http://localhost:8686/api/vehicles/1HGCM82633A123456/archive" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "sold",
    "sale_price": 15000.00,
    "sale_date": "2025-12-11",
    "notes": "Sold to private buyer",
    "archived_visible": false
  }'

# 3. List archived vehicles
curl -X GET "http://localhost:8686/api/vehicles/archived"

# 4. Un-archive if needed
curl -X POST "http://localhost:8686/api/vehicles/1HGCM82633A123456/unarchive"

# 5. Permanently delete (only after archiving)
curl -X DELETE "http://localhost:8686/api/vehicles/1HGCM82633A123456"
```

### Response Examples

**Archived Vehicle Response:**
```json
{
  "vin": "1HGCM82633A123456",
  "nickname": "Honda Accord",
  "year": 2019,
  "make": "Honda",
  "model": "Accord",
  "archived_at": "2025-12-11T15:30:00Z",
  "archive_reason": "sold",
  "archive_sale_price": 15000.00,
  "archive_sale_date": "2025-12-11",
  "archive_notes": "Sold to private buyer",
  "archived_visible": false
}
```

## Contributing

To enhance the archive system:

1. Add new archive reasons to the enum in `VehicleRemoveModal.tsx`
2. Update database migrations if adding new archive metadata fields
3. Ensure all archive fields are properly indexed for performance
4. Add tests for archive/un-archive workflows
5. Update this documentation with new features

## Related Documentation

- [API Documentation](http://localhost:8686/docs) - OpenAPI/Swagger docs
- [Development Guide](../DEVELOPMENT.md) - Setup and contribution guidelines
- [Database Schema](../backend/app/models/) - SQLAlchemy models
