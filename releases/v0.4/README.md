# v0.4 — camera build (NOT cleared for flashing)

= v0.4-candidate/edits_full.json minus the SD loader (its hook is on a dead path — REVIEW_v04 H1-new, confirmed).
Contains: profile bundles, per-profile WB, colour grain (per slot), bloom (per slot), MONO slots in colour,
log video, XPan/21:9 (heights ×16), recording limit. All verifiers passed on the superset.

Blocker (REVIEW_v04 B1): no proven install/recovery path yet. Test order when cleared:
rec_limit → video_log → bundles → WB → grain → bloom → MONO-colour → aspect (one feature per flash).
