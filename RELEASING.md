# MyGarage Release Process

**Purpose**: Step-by-step guide for creating MyGarage releases following semantic versioning and dev-sop.md standards.

**Audience**: Maintainers

**Last Updated**: 2025-12-02

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Release Checklist](#pre-release-checklist)
3. [Version Numbering](#version-numbering)
4. [Release Process](#release-process)
5. [Post-Release](#post-release)
6. [Rollback Procedures](#rollback-procedures)
7. [Troubleshooting](#troubleshooting)

---

## Overview

MyGarage uses **Semantic Versioning** (`MAJOR.MINOR.PATCH`) for all releases.

### Release Automation

Our release process is **semi-automated**:
- ✅ Automated: Testing (CI), Docker build, GHCR publishing, GitHub release creation, changelog extraction
- 🔧 Manual: Version bumping, CHANGELOG.md updates, git tag creation, history documentation

### Release Artifacts

Each release produces:
1. **GitHub Release** with extracted changelog
2. **Docker Images** on GHCR with 4 tags (`latest`, `MAJOR.MINOR.PATCH`, `MAJOR.MINOR`, `MAJOR`)

---

## Pre-Release Checklist

Before starting a release, verify:

### Code Quality
- [ ] All changes committed and pushed to main branch
- [ ] CI workflow passing (tests, linting, type checking)
- [ ] Docker build test passing
- [ ] No open critical bugs or security issues
- [ ] Backend tests: **98%+ pass rate** (135+/137 tests)
- [ ] Frontend tests: **97%+ pass rate** (28+/29 tests)

### Testing
- [ ] Backend pytest runs clean: `pytest backend/tests/unit/ -v`
- [ ] Frontend vitest runs clean: `npm --prefix frontend test -- --run`
- [ ] Type checking passes: `npx tsc --noEmit --project frontend/tsconfig.json`
- [ ] Linting clean: `npm --prefix frontend run lint`
- [ ] Docker build succeeds: `docker build -t mygarage:test .`
- [ ] Test container runs: `docker run --rm mygarage:test`

### Documentation
- [ ] CHANGELOG.md updated with all changes in `[Unreleased]` section
- [ ] README.md is current (features, installation, configuration)
- [ ] API documentation reflects any endpoint changes
- [ ] No TODO/FIXME comments in production code

### Security
- [ ] No secrets or sensitive data in code
- [ ] No debug/console logs in production code
- [ ] Security vulnerabilities addressed (Dependabot, CodeQL)
- [ ] Third-party dependencies reviewed and updated

---

## Version Numbering

MyGarage follows **Semantic Versioning** (`MAJOR.MINOR.PATCH`).

### When to Bump

**MAJOR (x.0.0)** - Breaking changes:
- Incompatible API changes
- Removed endpoints or features
- Database schema changes requiring manual migration
- Changed authentication mechanisms
- Configuration format changes

**Examples:**
- `2.14.0` → `3.0.0`: Remove REST API v1, keep only v2
- `2.14.0` → `3.0.0`: Change from JWT to OAuth2

**MINOR (0.x.0)** - New features (backward-compatible):
- New API endpoints
- New features or functionality
- Significant enhancements
- New optional configuration options
- New record types or tracking capabilities

**Examples:**
- `2.14.0` → `2.15.0`: Add trailer support
- `2.14.0` → `2.15.0`: Add NHTSA recall integration

**PATCH (0.0.x)** - Bug fixes and patches:
- Bug fixes
- Security patches
- Performance improvements (no API changes)
- Documentation updates
- Dependency updates (no breaking changes)

**Examples:**
- `2.14.0` → `2.14.1`: Fix fuel record MPG calculation
- `2.14.0` → `2.14.2`: Security patch for dependency

### Pre-Release Versions

For alpha, beta, or release candidate versions:
- `2.15.0-alpha.1` - Early testing, unstable
- `2.15.0-beta.1` - Feature-complete, testing
- `2.15.0-rc.1` - Release candidate, final testing

The release workflow automatically detects pre-releases and marks them appropriately.

---

## Release Process

### Step 1: Update Version Numbers

**Update backend version:**

Edit `backend/pyproject.toml`:
```toml
[project]
name = "mygarage"
version = "2.15.0"  # Update this line
```

**Update frontend version:**

Edit `frontend/package.json`:
```json
{
  "name": "mygarage-frontend",
  "version": "2.15.0",  # Update this line
  ...
}
```

### Step 2: Update CHANGELOG.md

**Edit CHANGELOG.md:**

1. Change `[Unreleased]` to `[2.15.0] - 2025-12-15` (use actual date)
2. Ensure all changes are categorized (Added, Changed, Fixed, Security, etc.)
3. Add new `[Unreleased]` section at top:

```markdown
# Changelog

## [Unreleased]

## [2.15.0] - 2025-12-15

### Added
- New trailer support with spot rental tracking
- Tow vehicle linking

### Changed
- Updated vehicle wizard to include trailer fields

### Fixed
- Fixed MPG calculation for partial fill-ups
```

### Step 3: Commit Changes

```bash
git add backend/pyproject.toml frontend/package.json CHANGELOG.md
git commit -m "chore: Bump version to 2.15.0"
git push origin main
```

### Step 4: Verify CI Passes

**Wait for CI to complete:**
1. Go to GitHub Actions tab
2. Verify CI workflow passes
3. Check all three jobs: Backend Tests, Frontend Tests, Docker Build Test

**If CI fails:**
- Fix issues and commit
- Wait for CI to pass before continuing

### Step 5: Create Git Tag

**Create and push annotated tag:**
```bash
git tag -a v2.15.0 -m "Release v2.15.0"
git push origin v2.15.0
```

**Tag format:**
- Always prefix with `v` (e.g., `v2.15.0`)
- Use annotated tags (`-a` flag)
- Include version in message

### Step 6: Monitor Automated Release

**Watch automation:**
1. **GitHub Actions** - Two workflows will trigger:
   - `Docker Build & Publish` - Builds and publishes Docker images
   - `Release` - Creates GitHub release

2. **Check Docker Build** workflow:
   - Verify image builds successfully
   - Check GHCR for new images: `ghcr.io/homelabforge/mygarage:2.15.0`
   - Verify all 4 tags created: `2.15.0`, `2.15`, `2`, `latest`

3. **Check Release** workflow:
   - Verify GitHub release created
   - Confirm changelog extracted correctly
   - Check release assets (if any)

**Expected duration:** 5-10 minutes total

### Step 7: Test Published Image

**Pull and test the published image:**
```bash
# Pull the new image
docker pull ghcr.io/homelabforge/mygarage:2.15.0

# Test it runs
docker run --rm -p 8686:8686 ghcr.io/homelabforge/mygarage:2.15.0

# Visit http://localhost:8686 and verify:
# - Application starts
# - Version shows 2.15.0 in footer/about
# - Health check passes: curl http://localhost:8686/health
```

### Step 8: Verify Release

**Verify the release was successful:**
- Check GitHub Releases page for new release
- Verify Docker images available on GHCR
- Test published image works correctly

### Step 9: Update Your Production Deployment (Optional)

**If managing your own production deployment:**
```bash
# Update docker-compose.yml to new version
image: ghcr.io/homelabforge/mygarage:2.15.0

# Or use latest (auto-updates)
image: ghcr.io/homelabforge/mygarage:latest

# Pull and restart
docker compose pull
docker compose up -d
```

---

## Post-Release

### Announcement

1. **GitHub Discussions** - Announce the release with highlights
2. **Update Website** - Update homelabforge.io/builds/mygarage if applicable
3. **Social Media** - Share on relevant platforms (optional)

### Verification

- [ ] GitHub release visible and accurate
- [ ] Docker images available on GHCR (4 tags)
- [ ] README.md still accurate
- [ ] Documentation site updated (if applicable)

### Monitoring

**Watch for issues in first 24-48 hours:**
- GitHub Issues for bug reports
- GitHub Discussions for questions
- Docker pulls and deployment issues

---

## Rollback Procedures

If a critical issue is discovered after release, follow these steps:

### Option 1: Hotfix Release (Recommended)

**For critical bugs or security issues:**

1. Fix the issue on main branch
2. Bump PATCH version (e.g., `2.15.0` → `2.15.1`)
3. Update CHANGELOG.md with `[2.15.1]` section documenting the fix
4. Follow normal release process (Steps 1-9)
5. Hotfix will automatically become `:latest` tag

**Advantages:**
- Maintains release history
- Users on `:latest` auto-update
- Clear audit trail

### Option 2: Delete Release and Tag (Last Resort)

**Only for catastrophic failures (data loss, security breach):**

1. **Delete GitHub Release:**
   - Go to GitHub Releases page
   - Click on problematic release
   - Delete release

2. **Delete Git Tag:**
   ```bash
   # Delete local tag
   git tag -d v2.15.0

   # Delete remote tag
   git push origin :refs/tags/v2.15.0
   ```

3. **Delete Docker Images** (if necessary):
   - Go to GHCR package page
   - Delete specific version tag
   - Note: Cannot delete `:latest` if it's already pulled by users

4. **Revert Version Numbers:**
   - Revert `pyproject.toml` and `package.json` to previous version
   - Revert CHANGELOG.md changes
   - Commit: `git commit -m "chore: Revert to v2.14.0 due to critical issue"`

5. **Communicate:**
   - Post GitHub Issue explaining the rollback
   - Update Discussions
   - Notify users via announcement

**Disadvantages:**
- Breaks versioning sequence
- Confuses users who already pulled the image
- Creates history gaps

---

## Troubleshooting

### CI Workflow Fails

**Symptoms**: CI workflow shows red X on GitHub Actions

**Diagnosis:**
```bash
# Check CI logs on GitHub Actions tab
# Common issues:
# - Test failures
# - Linting errors
# - Type checking failures
# - Docker build failures
```

**Solutions:**
1. Fix the failing tests/lints locally
2. Run tests: `pytest tests/unit/` and `npm test -- --run`
3. Commit fixes
4. Wait for CI to pass
5. Continue release process

**Note**: Tests use `continue-on-error: true` per dev-sop.md, so they won't block the workflow, but you should still fix them.

### Docker Build Workflow Fails

**Symptoms**: Docker Build & Publish workflow fails after tag push

**Common causes:**
1. **Authentication failure** - GITHUB_TOKEN permissions
2. **Dockerfile errors** - Syntax or build issues
3. **GHCR permissions** - Package not configured

**Solutions:**

**For auth issues:**
```bash
# Verify repository settings
# Settings → Actions → General → Workflow permissions
# Ensure "Read and write permissions" is enabled
```

**For Dockerfile issues:**
```bash
# Test build locally
docker build -t mygarage:test .

# Fix Dockerfile errors
# Commit and create new tag (e.g., v2.15.1)
```

**For GHCR permissions:**
```bash
# Go to GitHub → Package settings
# Ensure package is public
# Verify organization permissions
```

### Release Workflow Fails

**Symptoms**: Release workflow fails, no GitHub release created

**Common causes:**
1. **CHANGELOG.md format** - Can't extract version
2. **Permissions** - Can't create release
3. **Duplicate release** - Tag already has release

**Solutions:**

**For changelog extraction:**
- Verify CHANGELOG.md has `## [2.15.0]` section
- Check format matches Keep a Changelog spec
- Workflow will fallback to generic message if extraction fails

**For permissions:**
- Check workflow has `permissions: contents: write`
- Verify repository settings allow workflow to create releases

**For duplicate releases:**
- Delete existing release via GitHub UI
- Re-run workflow or delete and recreate tag

### Wrong Version Tag Published

**Symptoms**: Created tag `v2.15.0` but meant `v2.16.0`

**Solution:**
```bash
# Delete wrong tag
git tag -d v2.15.0
git push origin :refs/tags/v2.15.0

# Delete GitHub release (via GitHub UI)

# Update version numbers correctly
# Edit pyproject.toml, package.json, CHANGELOG.md

# Commit corrections
git add .
git commit -m "chore: Fix version to 2.16.0"
git push

# Create correct tag
git tag -a v2.16.0 -m "Release v2.16.0"
git push origin v2.16.0
```

### Docker Image Won't Pull

**Symptoms**: `docker pull ghcr.io/homelabforge/mygarage:2.15.0` fails

**Diagnosis:**
```bash
# Check if image exists on GHCR
# Visit: https://github.com/orgs/homelabforge/packages/container/mygarage

# Try with full path
docker pull ghcr.io/homelabforge/mygarage:2.15.0

# Check Docker daemon logs
docker system info
```

**Solutions:**
- Verify image published (check GitHub Actions logs)
- Ensure package is public (not private)
- Check GHCR is accessible (not down)
- Try `:latest` tag instead

---

## Release Schedule

### Regular Releases

**Cadence**: As needed, typically:
- **MAJOR**: Annually or when breaking changes necessary
- **MINOR**: Monthly or when significant features ready
- **PATCH**: As needed for bug fixes (1-2 weeks)

### Security Releases

**Critical vulnerabilities**: Immediate patch release
- CVE with CVSS score ≥7.0
- Data exposure risks
- Authentication bypasses

**Process:**
1. Fix vulnerability on private branch
2. Test thoroughly
3. Bump PATCH version
4. Release immediately
5. Announce via GitHub Security Advisories

### Dependency Updates

**Automated via Dependabot:**
- Weekly PRs for backend (pip), frontend (npm), actions, docker
- Review and merge within 7 days
- Trigger PATCH release if security-related
- Batch non-security updates monthly

---

## Release Checklist Template

Copy this checklist for each release:

```markdown
## Release v2.x.x Checklist

### Pre-Release
- [ ] All changes committed to main
- [ ] CI passing (tests, linting, type checking)
- [ ] Docker build test passing
- [ ] Version bumped in pyproject.toml and package.json
- [ ] CHANGELOG.md updated (Unreleased → [2.x.x] - DATE)
- [ ] README.md accurate
- [ ] No secrets in code
- [ ] Security issues addressed

### Release
- [ ] Changes committed: `git commit -m "chore: Bump version to 2.x.x"`
- [ ] Changes pushed: `git push origin main`
- [ ] CI verified passing
- [ ] Tag created: `git tag -a v2.x.x -m "Release v2.x.x"`
- [ ] Tag pushed: `git push origin v2.x.x`

### Post-Release
- [ ] Docker Build workflow completed successfully
- [ ] Release workflow completed successfully
- [ ] GitHub release created with correct changelog
- [ ] Docker images available on GHCR (4 tags)
- [ ] Tested published image: `docker pull ghcr.io/homelabforge/mygarage:2.x.x`
- [ ] Release announced (Discussions, website, etc.)

### Verification (24h)
- [ ] No critical issues reported
- [ ] Docker pulls working
- [ ] Users deploying successfully
```

---

## References

- **Semantic Versioning**: https://semver.org/
- **Keep a Changelog**: https://keepachangelog.com/
- **GitHub Actions Docs**: https://docs.github.com/en/actions
- **GHCR Docs**: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry

---

**Last Updated**: 2025-12-02
**Maintained By**: HomelabForge
