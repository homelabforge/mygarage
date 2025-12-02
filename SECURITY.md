# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in MyGarage, please report it privately to help us fix it before public disclosure.

### How to Report

**Preferred Method:** Use GitHub Security Advisories
- Go to the [Security tab](https://github.com/homelabforge/mygarage/security/advisories) of this repository
- Click "Report a vulnerability"
- Fill out the advisory form with details

**Alternative Method:** Email Security Team
- Email: [security@homelabforge.io](mailto:security@homelabforge.io)
- Include "MyGarage Security" in the subject line

### What to Include

To help us understand and fix the issue quickly, please include:

- **Type of vulnerability** (e.g., SQL injection, XSS, authentication bypass)
- **Affected component** (e.g., backend API, frontend, Docker image)
- **Affected version(s)** (e.g., v2.14.0, all versions, Docker latest tag)
- **Steps to reproduce** - Detailed instructions to trigger the vulnerability
- **Potential impact** - What could an attacker do with this vulnerability?
- **Suggested fix** (if you have one) - We appreciate any guidance!
- **Your contact information** - So we can follow up with questions

### What to Expect

- **Acknowledgment**: We'll acknowledge receipt within **48 hours**
- **Initial assessment**: We'll provide an initial assessment within **5 business days**
- **Fix timeline**: Critical issues will be patched within **7 days**, high-priority within **14 days**
- **Disclosure**: We'll coordinate with you on responsible disclosure timing
- **Credit**: We'll publicly credit you in the security advisory (unless you prefer anonymity)

## Supported Versions

We actively support the following versions with security updates:

| Version | Supported          | Notes                                    |
|---------|--------------------|------------------------------------------|
| 2.x     | ✅ Yes             | Current major version, actively maintained |
| 1.x     | ❌ No              | End of life - please upgrade to 2.x      |
| < 1.0   | ❌ No              | Pre-release versions, not supported      |

**Docker Tags:**
- `latest` - Always points to the most recent stable release with security patches
- `v2.x.x` - Specific version tags (e.g., `v2.14.0`)
- `main` - Development branch, not recommended for production

## Security Best Practices

When deploying MyGarage, follow these security recommendations:

### 1. Authentication

- **Never use `auth_mode=none` in production** - This disables all authentication!
- Use `auth_mode=local` with strong passwords, or `auth_mode=oidc` with a trusted SSO provider
- If you must use `none` mode (e.g., behind a trusted reverse proxy with authentication), set `MYGARAGE_ALLOW_AUTH_NONE=true` to acknowledge the risk

### 2. Network Security

- **Run behind a reverse proxy** (Traefik, Nginx, Caddy) with HTTPS
- Configure proper CORS origins via `MYGARAGE_CORS_ORIGINS` environment variable
- Limit network access to trusted networks (use Docker networks, firewall rules)
- Enable JWT cookie secure flag in production (auto-enabled when `debug=false`)

### 3. Database Security

- Use strong, unique passwords for PostgreSQL (if using external database)
- Restrict database network access to MyGarage container only
- Enable PostgreSQL SSL/TLS connections for remote databases
- Regularly backup your database and test restore procedures

### 4. Container Security

- Run the official `ghcr.io/homelabforge/mygarage` Docker image
- Keep the image updated - check for security patches regularly
- MyGarage runs as non-root user (UID 1000) by default
- Review and restrict volume mounts to necessary directories only

### 5. Environment Variables

- **Never commit `.env` files to version control**
- Use Docker secrets or environment variable injection for sensitive values
- Rotate JWT secrets periodically (requires user re-authentication)
- Review `.env.example` for security-sensitive configuration options

### 6. File Uploads

- Upload size limits are enforced (10MB photos, 25MB documents by default)
- Only allowed file extensions are accepted (configured in `config.py`)
- Store uploaded files outside the web root (handled automatically)
- Consider scanning uploads with antivirus tools if accepting files from untrusted users

### 7. Updates and Monitoring

- Subscribe to GitHub releases for security announcements
- Monitor application logs for suspicious activity
- Enable health checks in your container orchestration
- Test updates in a staging environment before production deployment

## Security Features

MyGarage includes the following built-in security features:

- **Authentication**: Local JWT or OIDC/SSO integration
- **Password Hashing**: Argon2id with high memory cost (100MB, time cost 3, parallelism 4)
- **Session Management**: HttpOnly JWT cookies with SameSite protection
- **Rate Limiting**:
  - Auth endpoints: 5 requests/minute (brute-force protection)
  - Upload endpoints: 20 requests/minute
  - Export endpoints: 5 requests/minute (resource protection)
  - General API: 200 requests/minute
- **Input Validation**: Pydantic models with strict validation
- **SQL Injection Prevention**: SQLAlchemy ORM with parameterized queries
- **CORS Protection**: Configurable allowed origins
- **Content Security**: File extension and MIME type validation

## Known Security Considerations

### Authentication Mode: `none`

MyGarage defaults to `auth_mode=none` for easy initial setup. This mode:
- **Disables all authentication** - Anyone who can access the URL can access all data
- Displays prominent security warnings in logs
- Is blocked in production unless `MYGARAGE_ALLOW_AUTH_NONE=true` is set
- **Should NEVER be used when exposed to the public internet**

**Recommended for:**
- Local development and testing
- Single-user deployments behind a firewall
- Behind a reverse proxy with external authentication (e.g., Authelia, oauth2-proxy)

**Switch to `local` or `oidc` mode before exposing to untrusted networks.**

### Debug Mode

When `MYGARAGE_DEBUG=true`:
- Detailed error messages are returned to clients (may leak internal paths)
- Stack traces are included in error responses
- More verbose logging (may include sensitive information)
- JWT cookie secure flag is disabled (allows HTTP in development)

**Never enable debug mode in production.**

## Third-Party Dependencies

MyGarage relies on the following external services:

- **NHTSA vPIC API** (vpic.nhtsa.dot.gov) - VIN decoding, publicly accessible
- **Python/Node.js packages** - See `requirements.txt` and `package.json`

We regularly monitor dependencies for known vulnerabilities using:
- Dependabot alerts (GitHub)
- `pip-audit` for Python packages
- `npm audit` for Node.js packages

## Security Changelog

Security-related changes are documented in [CHANGELOG.md](CHANGELOG.md) with `[SECURITY]` tags.

Recent security improvements:
- **v2.10.0**: Added JWT HttpOnly cookies, SameSite protection, secure flag auto-detection
- **v2.8.0**: Implemented Argon2id password hashing, increased memory cost to 100MB
- **v2.6.0**: Added rate limiting to authentication endpoints
- **v2.4.0**: Enhanced CORS configuration, strict MIME type validation

## Contact

For security-related questions or concerns:
- **Security Team**: [security@homelabforge.io](mailto:security@homelabforge.io)
- **General Support**: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)

For community discussions (non-security topics), use [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions).

---

**Thank you for helping keep MyGarage and its users safe!**
