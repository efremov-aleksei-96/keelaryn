# Keelaryn Roadmap

**Status:** durable direction, not a release commitment.  
**Architecture baseline:** Zero-Based Architecture r2.

This roadmap records deliberately deferred work so that it survives chat boundaries without being mistaken for MVP requirements.

## Current implementation path

The active implementation sequence is:

1. freeze the zero-based architecture and roadmap in repository documentation;
2. define strict machine-readable schemas and a deterministic state machine;
3. implement Keelaryn Core against a disposable local filesystem;
4. build fault-injection and restart/recovery coverage before remote storage integration;
5. add a Google Drive backend;
6. deploy the Core poller on Linux VPS;
7. prove a disposable Project → RESULT → Reconciliation → Core end-to-end cycle;
8. pilot only on a copy of a limited real-Hub subset;
9. design production-Hub migration after the pilot.

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

## Explicitly not implied by the roadmap

A roadmap item is not automatically approved for implementation, does not reserve a product version and does not become an MVP requirement merely by appearing here. Each item must be re-justified against current needs, safety, complexity and operating evidence before implementation.
