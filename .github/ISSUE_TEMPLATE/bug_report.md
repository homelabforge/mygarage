---
name: Bug Report
about: Report a bug or unexpected behavior
title: '[BUG] '
labels: bug
assignees: ''
---

## Bug Description

**Describe the bug**
A clear and concise description of what the bug is.

**Expected Behavior**
What you expected to happen.

**Actual Behavior**
What actually happened.

## Steps to Reproduce

1. Go to '...'
2. Click on '...'
3. Scroll down to '...'
4. See error

## Environment

**MyGarage Version:**
- Docker tag (e.g., `latest`, `v2.14.0`):
- Or commit hash if building from source:

**Deployment Method:**
- [ ] Docker Compose
- [ ] Docker Run
- [ ] Kubernetes
- [ ] Other (please specify):

**Operating System:**
- Host OS (e.g., Ubuntu 22.04, Debian 12, Windows 11 + WSL2):
- Docker version (run `docker --version`):

**Database:**
- [ ] SQLite (default)
- [ ] PostgreSQL (version:          )

**Browser (for UI issues):**
- Browser and version (e.g., Chrome 120, Firefox 121, Safari 17):
- [ ] Light mode
- [ ] Dark mode

**Authentication Mode:**
- [ ] none (no authentication)
- [ ] local (username/password)
- [ ] oidc (SSO/OIDC provider:          )

## Logs and Screenshots

**Error Messages**
```
Paste any error messages here
```

**Container Logs**
```bash
# Get logs with: docker logs mygarage --tail 100
Paste relevant logs here
```

**Screenshots**
If applicable, add screenshots to help explain your problem.
Drag and drop images here or use Markdown:
```markdown
![Screenshot description](URL)
```

## Additional Context

**Configuration:**
- Are you using a reverse proxy? (Traefik, Nginx, Caddy, etc.)
- Are you using a custom domain or localhost?
- Any custom environment variables set?

**Recent Changes:**
- Did this work before? If yes, what changed?
- Recent Docker image update?
- Recent configuration changes?

**Other relevant information:**
Add any other context about the problem here.

---

**Before submitting:**
- [ ] I've searched existing issues to ensure this isn't a duplicate
- [ ] I've included my MyGarage version and deployment method
- [ ] I've included relevant logs or error messages
- [ ] I've described the steps to reproduce the issue
