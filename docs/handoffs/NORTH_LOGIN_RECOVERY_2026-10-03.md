# North login recovery — 2026-10-03

Production control-plane 91b7aad did not include the earlier a1dc611 North portal-grant fix. A North-authorized account without Brain personas received 403 at login. The exact fix was cherry-picked onto productive lineage 39722c0 as 09d1c5630d656d2fa35b7bc5dfed0d13fadf895b; 15 auth tests passed.

Only control-plane changed. Build 37150076575 produced sha256:699c6e4aa8a6787b74171b2e777337ee76e7bff691ec002b51e9de249dc17098. Manifest `ops/microservices/releases/north-login-recovery-20261003.json` passed dry-run 37150301531 and release 37152123271. An earlier dispatch 37150367034 failed checkout with an abbreviated SHA before mutation; the successful run used full manifest SHA 33d137e0c5a6c00fffc01d57671c4b3bc6a8f82b.

Read-only post-release status: control-plane blue, other service slots/digests preserved, claims not paused. Previous control-plane digest ce9bf23c20141fb6766eb7f9243c07346668f97c8f9258065050601de9d45982 remains the rollback reference. Brain backup `/var/backups/brain-ai/20261003T200350Z` completed and SHA256SUMS verified; no restore was performed.

Verification against https://north-portal.pages.dev and public API:
- Authorized fixture password login and auth/me: 200; own task capabilities: 200; foreign-agency task: 403; logout: 200; revoked session: 403.
- Browser sessions for Allan, Cintia, Alisson and Luiza reached `/admin/home`; auth/me, North shell and clients returned 200. These used short-lived server-issued sessions for the actual identities, not their passwords.
- Private local evidence: `agent-work/lead-delivery-20261003/north-password-evidence.json`, `north-staff-evidence.json`, and corresponding screenshots. No credentials or session tokens are included.

This proves access recovery, not completion of North writes, Graph editor or FAQ/RAG. Keep this auth fix when integrating the Graph candidate. Gateway CORS preview release remains under investigation: canary failed before cutover despite public login passing; no bypass authorized or applied.
