# Credential handling

The local browser retains Lectio's remembered login in its dedicated profile.
Interactive and background runs share that profile and browser identity. Setup
checks Lectio's current-device remembered-session entry before reporting success.
The scheduled wrapper offers a visible login recovery at most once per day while
unresolved; a successful refresh rearms recovery for the next failure.

## Cookies sent to GitHub

Only `ASP.NET_SessionId`, `isloggedin3`, `BaseSchoolUrl`, and
`LastAuthenticatedPageLoad2` are permitted in the exported header. A nonempty
`ASP.NET_SessionId` is required. Remembered-login cookies such as
`autologinkeyV2`, legacy tickets, SSO cookies, and unknown cookie names are
excluded. The same restriction is enforced immediately before `gh secret set`,
including optional exports after calendar fetching. Values are passed on stdin,
not the command line. Invalid/duplicate headers are rejected without printing
their contents or overwriting the existing secret.

These are ordinary Lectio session credentials, not a calendar-only API token.
An attacker who obtains a usable session may act with the account's privileges,
including reading private data and performing permitted writes. Removing the
remembered key reduces exposure but does not turn a session into read-only access
or establish a guaranteed maximum lifetime; server-side renewal rules still apply.

## Local session persistence

On Windows, session-only cookies needed across browser restarts are stored in
`%LOCALAPPDATA%\lectio-sync\playwright-profile\session-cookies.dpapi`.
Windows DPAPI protects them for the current user with no UI prompt and no
application-managed key file. Integrity verification and an atomic write precede
removal of the legacy plaintext JSON file. Migration is automatic. A corrupt
encrypted file is not bypassed by loading an older plaintext copy. Persistent
cookies remain in Chromium's own profile storage.

SSO session cookies are retained in protected storage to preserve the existing
login experience. This protection limits the value of a copied file; it cannot
protect against malware executing as the logged-in Windows user or an attacker
who controls that user's session. On non-Windows platforms the existing file
permissions model (mode 0600) is retained; DPAPI is Windows-specific.

Cookie files are excluded from Git. Public code and public calendar files are
different from Actions secrets. The ICS feeds intentionally remain public for
the existing calendar subscriptions; anyone can read the published event data
without authentication. Those files do not provide an authenticated session.

## Workflow dependencies

Checkout and Python setup are pinned to the verified upstream commit IDs instead
of movable version tags. Update those pins deliberately when adopting newer
versions. Repository write access and the ability to run altered workflows remain
sensitive privileges because workflows can access configured secrets.
