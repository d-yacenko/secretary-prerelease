# Google OAuth operations

Secretary already refreshes Google access tokens automatically.

- The authorization URL requests `access_type=offline` and `prompt=consent`.
- Gmail and Google Calendar share one stored Google account credential.
- When an access token expires, sync uses the stored refresh token. No weekly re-consent job exists.

Google Cloud projects left in Publishing status **Testing** expire non-basic OAuth authorizations, including refresh tokens for Gmail, Calendar, and Drive scopes, after 7 days. Application code cannot renew a refresh token after Google returns a permanent failure such as `invalid_grant`.

Continuous real use requires the OAuth client’s Publishing status to be **In Production**, or an appropriate **Internal** mode for a Workspace organization. Changing that status is an operator action in Google Cloud Console. It is outside Secretary runtime, and this repository does not automate the consent screen, store a Google password, or rotate refresh tokens around the Testing limit.

Public distribution that uses sensitive or restricted scopes may also require Google’s verification and security review. That review is not performed by Secretary.
