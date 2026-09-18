# FINAL FIX PLAN (ordered; engine-free fixes first)

## 1. Critical missing requirements
- F1 (#65): add `docs/architecture.mmd` (mermaid: edge/internal zones,
  all services, trust arrows) + README reference. No PNG (no renderer
  without daemon/node) — source + ASCII is the honest artifact.
- F2 (#68): write AI-assistance disclosure (what AI generated, what the
  candidate verified, per PDF §31).

## 2. Security gaps
- F3: live image scans + read-only first boot (ENGINE).
- F4: first push → Actions run incl. Checkov (needs GitHub remote).

## 3. Reliability gaps
- F5: run F1–F7 drills live, paste evidence into INCIDENT-1/2 (ENGINE).
- F6: backlog drill → fill SCALING worker numbers (ENGINE).

## 4. Deployment gaps
- F7: v1→v2→v3→rollback live transcript (ENGINE).
- F8: push → release/rollback/audit jobs go green (needs remote).

## 5. Observability gaps
- F9: Prometheus targets UP + Grafana render + 5 alert drills (ENGINE).

## 6. Documentation gaps
- F10: re-grep stale refs after fixes (e.g., "M1 runbook content" pointers,
  old module paths) — do in this pass.
- F11: traceability counts → 68+ new tests.

## 7. Demo gaps
- F12: full runbook pass top-to-bottom (ENGINE); record outputs into
  incident/dry-run notes.
