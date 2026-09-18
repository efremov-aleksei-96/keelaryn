# Keelaryn Roadmap

**Status:** durable direction, not a release commitment.  
**Architecture baseline:** Zero-Based Architecture r2.

This roadmap records deliberately deferred work so that it survives chat boundaries without being mistaken for MVP requirements.

## Current implementation path

The active implementation sequence is:

1. freeze the zero-based architecture and roadmap in repository documentation — COMPLETE;
2. define strict machine-readable schemas and a deterministic state machine — COMPLETE;
3. implement Keelaryn Core against a disposable local filesystem — COMPLETE;
4. build fault-injection and restart/recovery coverage before remote storage integration — COMPLETE;
5. add a Google Drive backend — COMPLETE;
6. deploy the Core poller on Linux VPS — COMPLETE;
7. prove a disposable Project → RESULT → Reconciliation → Core end-to-end cycle — COMPLETE;
8. pilot only on a copy of a limited real-Hub subset — COMPLETE; sanitized evidence: `tests/results/zero-based-private-real-hub-subset-pilot-20260917.json`;
9. design production-Hub migration after the pilot — NEXT.

Step 8 proved a read-only structural subset from the real production Hub could be copied into a private immutable pilot pack, published through the zero-based Google Drive/Core transaction path to `COMMITTED` at canonical epoch 1, and leave the selected production source bytes unchanged. The pilot remains development evidence; it is not production qualification and does not authorize production Hub mutation.

Production Manager 4.17.12 and the production Hub remain outside this implementation path until migration is separately designed and qualified.

## Deferred beyond MVP

### Automatic independent backup

Automated independent disaster backup of Keelaryn / the Hub is deferred. MVP retains per-change `history/` for rollback and recovery; the owner may maintain independent whole-Hub copies separately.

### History retention policy

Automatic deletion or retention management for `history/` is deferred. MVP deletes no history automatically.

### Multi-Hub and Hub switching

Multiple Hub instances, switching and associated registry semantics are deferred. The zero-based MVP targets one Hub.

### Mobile canonical writing

Direct canonical-writing workflows from mobile devices are deferred. Mobile read/access workflows may evolve independently, but canonical publication remains governed by the same safe-publication protocol.

### Event-driven Core wakeup

Google Drive push notifications, webhooks or other event-driven wakeup mechanisms are deferred. MVP uses polling; wakeup events remain non-authoritative hints when introduced later.

### Separate Drive permissions / identity

Physical permission separation between Project AI, Reconciliation AI and Core using separate Google identities or Drive permission boundaries is deferred to hardening. MVP may enforce the role model at protocol level under one account.

### Stronger independent AI semantic verification

Independent semantic review by additional AI models, multiple independent checks, risk-class human approval, deterministic verification of selected claims and similar higher-assurance mechanisms are deferred until the minimal system is operating reliably.

### Structural review automation

Automated review of Hub structure, duplicate truth, routing quality, stale indexes and related information-architecture issues is deferred.

### Project concurrency locking

Additional machine-enforced locking for concurrent writers to one project work area is deferred unless practical use shows protocol-level single-writer discipline is insufficient.

### Remote-first execution

Move as much Keelaryn development, validation, qualification and routine operation as practical off the maintainer's local Windows workstation into managed or disposable environments, primarily GitHub Actions and the Linux VPS. Keep local Windows execution only where evidence materially depends on private artifacts, DPAPI/OAuth, workstation or production integration, Windows-specific filesystem/ACL/desktop behavior, or other host-local state.

This is a future engineering and operational direction, not an MVP requirement. It must preserve Keelaryn's transaction-safety and qualification rules rather than trading validation for convenience.

## Explicitly not implied by the roadmap

A roadmap item is not automatically approved for implementation, does not reserve a product version and does not become an MVP requirement merely by appearing here. Each item must be re-justified against current needs, safety, complexity and operating evidence before implementation.
