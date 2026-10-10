# Security Policy

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through **GitHub Security Advisories**: go to the repository's
[Security tab](https://github.com/homelabforge/mygarage/security/advisories),
click **Report a vulnerability**, and fill out the form.

Please include:

- the type of vulnerability and the affected component/version
- steps to reproduce
- the potential impact
- a suggested fix, if you have one

We'll acknowledge your report as soon as we can, keep you updated, coordinate
disclosure timing, and credit you in the advisory unless you'd rather stay
anonymous.

## Supported Versions

Security fixes land in the latest release — the Docker `:latest` tag and the
newest `vX.Y.Z` tag. Older major versions are not maintained; please upgrade.
The `main` branch is development and not recommended for production.

## Deployment Hardening

- **Don't expose MyGarage with authentication disabled.** The default no-auth
  mode is for local/trusted use only — switch to `local` or OIDC authentication
  before putting it on an untrusted network.
- **Run behind an HTTPS reverse proxy** (Traefik, Nginx, Caddy).
- **Pin the SSO callback URL.** Left blank, `oidc_redirect_uri` is built from
  each request's Host or X-Forwarded-Host header, so set it to your public
  callback URL (Settings > System > Configure OIDC > Callback URL) and register
  exactly that URL at your identity provider, never a wildcard. Behind a
  reverse proxy, also set `MYGARAGE_TRUSTED_PROXIES`.
- **Never enable debug mode in production** — it can leak internal details in
  error responses.
- The official image (`ghcr.io/homelabforge/mygarage`) runs as a **non-root**
  user (UID 1000); keep it updated for security patches.
- **Never commit secrets.** Keep `.env` out of version control — see
  [`.env.example`](.env.example) for the available settings.

Dependencies are monitored via GitHub Dependabot.

## Security Changelog

Security-relevant changes are recorded in [CHANGELOG.md](CHANGELOG.md).
