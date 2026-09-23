# Google OAuth operations

Secretary already refreshes Google access tokens automatically.

- The authorization URL requests `access_type=offline` and `prompt=consent`.
- Gmail and Google Calendar share one stored Google account credential.
- When an access token expires, sync uses the stored refresh token. No weekly re-consent job exists.

Google Cloud projects left in Publishing status **Testing** expire non-basic OAuth authorizations, including refresh tokens for Gmail, Calendar, and Drive scopes, after 7 days. Application code cannot renew a refresh token after Google returns a permanent failure such as `invalid_grant`.

Continuous real use requires the OAuth client’s Publishing status to be **In Production**, or an appropriate **Internal** mode for a Workspace organization. Changing that status is an operator action in Google Cloud Console. It is outside Secretary runtime, and this repository does not automate the consent screen, store a Google password, or rotate refresh tokens around the Testing limit.

Public distribution that uses sensitive or restricted scopes may also require Google’s verification and security review. That review is not performed by Secretary.

The branding pages stay in `infra/public/`. The retired Caddy `public_web` service is not the publisher. A later authorized rollout copies those pages into the existing nginx static root as `index.html`, `privacy/index.html`, and `terms/index.html`. It does not edit or reload nginx and does not change `/secretary/`.

After that rollout has succeeded, set these Google OAuth consent-screen values:

- Application home page: `https://web-itx.duckdns.org/`
- Application privacy policy: `https://web-itx.duckdns.org/privacy`
- Application terms of service: `https://web-itx.duckdns.org/terms`

Google Cloud Publishing status remains an operator action. Google may also require domain ownership verification in Google Search Console. After the operator moves the client from Testing to In Production, the currently expired Google refresh token still requires one fresh Secretary OAuth authorization.
