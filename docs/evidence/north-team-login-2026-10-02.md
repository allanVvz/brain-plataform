# North staff login — 2026-10-02

Production control-plane ae511333 rejected non-admin users without personas
before evaluating their explicit operations grants. AKIA contains portal grant
projection that had not been shipped to that production service. Its staff
fallback also needed to include account_type=agency, the actual type of Cintia,
Alisson and Luiza. All three accounts are active and have explicit North grants;
Cintia’s linked North profile has role=admin. No data grant or migration is needed.

The production-based control-plane code now resolves explicit portal grants for
internal/agency staff without personas. Unknown grants remain denied and a failed
authorization lookup fails closed. Clients keep their existing persona routing.

Verification: 15 focused auth tests passed. The active control-plane database
client resolved exactly [north] for all three audited staff IDs, read-only.
The candidate hook is opt-in through verification.control_plane_auth_user_ids
in ops/microservices/releases/north-staff-login-20261002.json. It requires every
listed account to be active staff with exactly the North grant and an operations
session targeting /north/admin, before public cutover. It creates no sessions.

Image source a1dc611da8dc02b8f77b34837884f0647577069f; immutable digest
sha256:b70b0b79881d46b742ec6cda5b0adc1bb617de27c503cd20fbd2122b6f0deb3e.
Manifest preserves schema162 and every other service entry from production.
Independent review approved auth isolation, candidate hook and manifest scope.

Release 37071328808 completed successfully. The candidate verified all three
staff IDs before cutover. Public /portal-api/north/auth/me, admin shell and
clients returned HTTP 200 for all three accounts. Cintia’s five-minute privileged
audit session loaded https://north-portal.pages.dev/admin/home, showed Cintia in
the user menu and recorded zero failed API GETs or persona errors. Her password
was not tested or changed. No business-data writes were performed.

The canonical source manifest now records the deployed control-plane entry, so
subsequent incremental releases can preserve this fix. The release branch was
frozen at a6935a5 during deployment; workflow checkout resolved that commit.

