# Security policy

## Reporting a vulnerability

Please report security problems **privately**: on the repository page open **Security > Report a vulnerability** (GitHub private vulnerability reporting).
Do not open a public issue for a vulnerability. Include what you did, what happened, the mcIRC version (Help > About) and your system.
Never paste private data (admin passwords, API keys, node keys, message text) into a report.

You can expect an answer within about a week. Only the newest release is supported, so please check that the problem still exists after Help > Check for updates.

## Things worth knowing

- **Addons run Python code with full access to your PC.** Install only addons you trust. The catalog lists only addons that were reviewed and tested.
- **The updater** downloads the newest version of mcIRC from this GitHub repository over HTTPS and writes only the files on its allow-list (never settings, logs, node memory or installed addons). Every Python file is syntax-checked first and every replaced file is backed up. It does not verify a signature, so it trusts the repository itself.
- **The troubleshooting log and bug-report screenshots** are built to leave out message text, passwords, your position and whole keys. Check the preview in Help > Report a bug before you send anything.
- Admin passwords typed with `/login` are kept in memory only, never saved or logged.
