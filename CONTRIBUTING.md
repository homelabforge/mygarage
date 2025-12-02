# Contributing to MyGarage

Thanks for your interest in contributing to MyGarage!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/mygarage.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test locally
6. Commit: `git commit -m "Add your feature"`
7. Push: `git push origin feature/your-feature-name`
8. Open a Pull Request

## Development Setup

See the [Development section](README.md#development) in the README for setup instructions.

## Code Style

### Backend (Python)
- Follow PEP 8 guidelines
- Use `black` for code formatting
- Use type hints where appropriate
- Keep functions focused and under 50 lines when possible
- Use async/await for database operations

**Example:**
```python
async def get_vehicle_or_403(
    vehicle_id: int,
    user: User,
    db: AsyncSession
) -> Vehicle:
    """Get vehicle or raise 403 if user doesn't have access."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    if vehicle.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    return vehicle
```

### Frontend (React/TypeScript)
- Use TypeScript for all new components
- Use Prettier with default settings
- Follow React hooks best practices
- Use functional components (no class components)
- Keep components under 300 lines (split if larger)

**Component naming:**
```typescript
// PascalCase for components
export default function VehicleCard() { ... }

// camelCase for functions and variables
const handleSubmit = () => { ... }
```

### Styling (Tailwind CSS 4.x)

MyGarage uses **Tailwind CSS 4.x with `@theme`** for automatic light/dark mode theming based on system preference.

**Important conventions:**

#### 1. Use Semantic Theme Variables (Not Raw Colors)

```jsx
/* ✅ Correct - uses theme variables */
<div className="bg-garage-surface text-garage-text border-garage-border">

/* ❌ Wrong - hardcoded colors break dark mode */
<div className="bg-gray-800 text-white border-gray-700">
```

#### 2. Theme Variable Reference

**Background Colors:**
- `bg-garage-bg` - Main background
- `bg-garage-surface` - Card/panel background
- `bg-garage-surface-light` - Elevated surface
- `bg-garage-muted` - Muted/disabled background

**Text Colors:**
- `text-garage-text` - Primary text
- `text-garage-text-muted` - Secondary/muted text

**Border Colors:**
- `border-garage-border` - Standard borders

**Accent Colors:**
- `bg-primary-*` / `text-primary-*` - Primary actions (blue scale, 50-900)
- `bg-success-*` / `text-success-*` - Success states (green, 500-700)
- `bg-warning-*` / `text-warning-*` - Warning states (amber, 500-700)
- `bg-danger-*` / `text-danger-*` - Error/danger states (red, 500-700)

**Pre-built Component Classes:**
- `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`
- `.input`, `.card`
- `.badge`, `.badge-success`, `.badge-warning`, `.badge-danger`, `.badge-neutral`

#### 3. Dark Mode is Automatic

Theme variables automatically adapt based on system preference. **Never use `dark:` modifier** unless you need behavior different from the theme.

System preference detection happens automatically - no manual toggle needed.

#### 4. Adding New Theme Variables

If you need to add new colors:

1. Add to `@theme` block in `src/index.css`
2. Add light mode override in `html.light` block
3. Use semantic naming (describe purpose, not color)

#### 5. Responsive Design

- Mobile-first approach (base styles for mobile, scale up)
- Use Tailwind breakpoints: `sm:` (640px), `md:` (768px), `lg:` (1024px), `xl:` (1280px)
- Custom breakpoint: `xs:` (475px)
- Test on mobile, tablet, and desktop viewports

### Commits

Use conventional commit format:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, no logic change)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

**Examples:**
```bash
git commit -m "feat: add vehicle export to CSV"
git commit -m "fix: correct MPG calculation for partial fill-ups"
git commit -m "docs: update API authentication examples"
git commit -m "style: apply theme variables to settings page"
```

## Testing

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Bug Reports

Use [GitHub Issues](https://github.com/homelabforge/mygarage/issues) with:
- Clear description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Docker version, browser, light/dark mode)
- Screenshots (if UI-related)

## Feature Requests

Open a [GitHub Discussion](https://github.com/homelabforge/mygarage/discussions) to propose new features before implementing them.

## Questions?

Ask in [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions).
