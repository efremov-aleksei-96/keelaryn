# Keelaryn Hub Relay — сокращение ручного участия в Hub workflow

## Контекст

Нужно исследовать и реализовать способ максимально сократить ручное участие пользователя в цикле обновления персонального Keelaryn Hub.

Текущий принципиальный workflow:

```text
CURRENT
→ Keelaryn Workspace
→ scoped CHECKOUT
→ Keelaryn — Chats
→ RETURN PACKET
→ Workspace rebase against current CURRENT
→ worker CANDIDATE
→ Chat Manager reconciliation
→ APPROVED
→ local Manager install
→ next CURRENT
```

Сейчас значительная часть участия пользователя заключается не в принятии решений, а в механическом переносе файлов между чатами:

- загрузить CURRENT;
- скачать CHECKOUT;
- передать CHECKOUT в тематический чат;
- скачать RETURN;
- передать RETURN в Workspace;
- скачать CANDIDATE;
- передать CURRENT + CANDIDATE в Chat Manager;
- скачать APPROVED/CURRENT;
- установить локально;
- снова загрузить новый CURRENT в следующий Workspace-сеанс.

Цель — убрать максимально возможную часть этого ручного транспорта, **не ослабляя governance, provenance, ancestry и validation guarantees Keelaryn**.

---

# Основная идея

Использовать **Google Drive как relay/transport layer**, но не как новый источник канонической истины.

В ChatGPT уже доступен Google Drive connector, который умеет:

- искать файлы;
- читать их;
- скачивать raw-файлы;
- загружать файлы;
- обновлять/заменять содержимое;
- перемещать;
- переименовывать;
- работать с папками.

Следовательно, ChatGPT-side workflow потенциально может самостоятельно передавать:

```text
CURRENT
CHECKOUT
RETURN
CANDIDATE
APPROVED
```

через Drive без ручного скачивания/прикладывания файлов пользователем.

На локальной машине Google Drive Desktop может предоставить обычную синхронизируемую filesystem-папку.

---

# Ключевой архитектурный принцип

**Google Drive не должен становиться canonical authority.**

Canonical/trust boundaries должны сохраниться:

```text
Chat Manager
→ APPROVED artifact

local Keelaryn Manager
→ validation / installation
→ installed Hub
→ next CURRENT
```

Drive должен быть транспортом.

Нельзя строить механизм по принципу:

> взять самый новый ZIP в папке.

Все операции должны опираться на **точную artifact identity и ancestry**.

Минимально учитывать:

- Hub `instance_id`;
- system version;
- data revision;
- artifact ID;
- artifact role/status;
- producer role;
- base artifact ID;
- payload/content SHA-256;
- ancestry;
- expected predecessor;
- downgrade protection;
- ambiguity detection.

Если точная цепочка не разрешается однозначно — fail closed.

---

# Нежелательная конструкция

Не использовать один постоянно перезаписываемый файл вида:

```text
Keelaryn__Hub_CURRENT.zip
```

как единственный механизм идентификации состояния.

Причина:

- разные ChatGPT-чаты могут работать с разными revision;
- RETURN может быть построен от старого CURRENT;
- CANDIDATE может появиться после более нового CURRENT;
- Drive modification time не является provenance;
- возможны concurrent/stale readers;
- выбор «самого свежего» файла недостаточен для Keelaryn.

Предпочтительны immutable/revision-addressed artifacts.

Например:

```text
CURRENT/
  Keelaryn__Hub_CURRENT_r0067_appr-....zip

RETURNS/
  KEELARYN__HUB_RETURN_....md

CANDIDATES/
  Keelaryn__Hub_CANDIDATE_r0068_cand-....zip

APPROVED/
  Keelaryn__Hub_APPROVED_r0068_appr-....zip
```

Плюс при необходимости отдельный маленький relay index/state pointer.

Например концептуально:

```json
{
  "schema": "keelaryn.relay-state.v1",
  "instance_id": "...",
  "current_revision": "r0067",
  "current_artifact_id": "appr-r0067-...",
  "current_payload_sha256": "...",
  "current_drive_file_id": "..."
}
```

Сам pointer не должен подменять валидацию самого artifact.

---

# Требуется исследовать три уровня интеграции

## Phase 1 — ChatGPT-side Drive Relay

Без изменения локальной установки Manager.

Цель:

полностью убрать ручной перенос файлов **между Workspace, Keelaryn — Chats и Chat Manager**.

Желаемый поток:

```text
Workspace
→ получает exact CURRENT из Drive
→ создаёт CHECKOUT
→ публикует CHECKOUT в Drive

Keelaryn — Chats
→ получает exact CHECKOUT
→ выполняет domain work
→ публикует RETURN

Workspace
→ обнаруживает RETURN
→ получает current CURRENT
→ проверяет source checkout/baseline
→ делает rebase
→ публикует CANDIDATE

Chat Manager
→ получает exact CURRENT + CANDIDATE
→ reconciliation
→ публикует APPROVED
```

Нужно определить:

- relay folder layout;
- naming contract;
- artifact discovery;
- status lifecycle;
- stale artifact handling;
- concurrency handling;
- exact identity checks;
- multi-Hub compatibility;
- replay protection;
- archive strategy;
- negative/failed/rejected artifact handling.

---

# Phase 2 — Local Relay helper

Предпочтительный первый локальный вариант — **не встраивать Google API непосредственно в Manager**.

Google Drive Desktop синхронизирует relay directory локально.

Отдельный минимальный helper, например:

```text
KeelarynRelay.ps1
```

или аналогичный компонент может выполнять:

```text
Drive synced relay
→ validate identity envelope
→ copy APPROVED into normal Manager inbox
```

и:

```text
Manager-produced CURRENT
→ relay publish directory
→ Google Drive Desktop
→ Drive
```

Критически важно:

**helper не должен сам устанавливать Hub и не должен обходить Manager validation.**

Установка:

```text
APPROVED
→ standard Manager inbox
→ existing Manager validation/install path
```

Manager остаётся единственным локальным authority для установки.

Исследовать, можно ли Phase 2 сделать практически полностью вне Manager core и тем самым уменьшить regression surface.

---

# Phase 3 — Native Manager Relay UX

Только после стабилизации Phase 1/2 рассмотреть интеграцию в production Manager.

Возможный UX:

```text
Keelaryn Manager

[4] Install pending updates
[...]
[R] Relay
```

или:

```text
Relay status
- CURRENT published: yes
- pending APPROVED: 1
- identity: exact
- ancestry: valid

[1] Import pending APPROVED
[2] Publish CURRENT
[3] Sync relay
```

В идеале пользовательский путь:

```text
Chat Manager creates APPROVED
→ Drive relay
→ Drive Desktop
→ Manager detects exact pending APPROVED
→ user selects ordinary install
→ Manager validates and installs
→ Doctor
→ Manager publishes new CURRENT
→ Drive relay
```

Пользователь не должен вручную скачивать и копировать ZIP.

---

# Возможный конечный UX

Желаемый уровень участия пользователя:

```text
тематический чат:
"закрываем / верни результат в Hub"

Workspace:
"обработай pending returns"

Chat Manager:
"обработай pending candidate"

локально:
Install pending updates
```

Или ещё лучше, где это безопасно:

```text
тематический chat
→ RETURN автоматически в relay

Workspace
→ видит pending RETURN

Chat Manager
→ видит pending CANDIDATE

Manager
→ видит pending APPROVED
```

При этом человеческое подтверждение governance-sensitive действий можно сохранить.

---

# Pending inbox model

Исследовать возможность relay inboxes:

```text
00_STATE/
10_CURRENT/
20_CHECKOUTS/
30_RETURNS/
40_CANDIDATES/
50_APPROVED/
90_ARCHIVE/
99_REJECTED/
```

Это только концепт — структура должна быть выбрана после архитектурного анализа.

Workspace при инициализации потенциально может сообщать:

```text
Pending RETURNS: 2
- Nutrition System Rebuild
- Physical Activity Restart
```

и после команды пользователя обрабатывать их.

Не следует автоматически объединять несколько RETURN в один CANDIDATE без проверки:

- overlap touched entities;
- shared Areas;
- revision ancestry;
- conflicting decisions;
- ordering dependencies.

---

# Multi-Hub requirement

Решение должно быть совместимо с нынешней/будущей multi-Hub архитектурой Manager.

Недопустимо выбирать:

- текущий активный Hub;
- первый найденный Hub;
- единственный файл с подходящим именем;

если artifact явно относится к другому instance.

Relay contract должен связывать artifacts как минимум с:

```text
instance_id
artifact_id
revision
base_artifact_id
```

Если registry содержит несколько Hub и identity отсутствует/не разрешается — fail closed.

---

# Recovery and concurrency

Нужно отдельно threat-model/reliability review для случаев:

### Stale CURRENT

Worker начал работу от r0067, пока canonical уже r0069.

Нормальное поведение:

```text
RETURN retains its source baseline
→ Workspace rebases against current r0069
```

а не пытается заменить r0069 старым состоянием.

### Multiple candidates

Если одновременно существуют:

```text
candidate A based on r0067
candidate B based on r0067
```

после принятия A:

```text
r0068
```

B нельзя молча ставить как прямого successor.

Нужен rebase/reconciliation.

### Drive conflict copies

Drive может создать conflict/duplicate copies.

Имя файла не может быть trust signal.

### Partial sync

Файл может ещё синхронизироваться или быть временно недоступен.

Нужен atomic/stable-file strategy.

### Rejected candidate

Reject не должен повторно обнаруживаться как pending.

### Already installed APPROVED

Не должен повторно устанавливаться.

### Rollback/downgrade

Старый APPROVED не должен подменить более новый CURRENT.

---

# Security / privacy boundary

Персональный Keelaryn Hub содержит чувствительные данные:

- Health;
- Finance;
- Legal;
- identity/admin;
- relationships;
- potentially credentials metadata.

Поэтому:

- не использовать публичные ссылки;
- не расширять sharing автоматически;
- не переносить Hub в GitHub как замену Drive;
- GitHub оставить для Manager/framework source development;
- Drive использовать только как private relay/storage под пользовательским аккаунтом;
- secrets, которые уже исключены из Hub, не должны появиться в relay metadata/logs.

Исследовать, какие минимальные metadata нужны relay для маршрутизации без раскрытия лишнего содержания.

---

# GitHub boundary

Сохранить разделение:

```text
Manager/framework source
→ GitHub

Personal Hub artifacts
→ private Drive relay
```

Не смешивать разработку универсального Manager и персональное содержимое Hub.

---

# Compatibility requirement

Новая функция не должна ломать пользователей, которым Drive Relay не нужен.

Manager должен по-прежнему поддерживать обычный:

```text
manual inbox
→ validation
→ install
```

Relay должен быть:

```text
optional capability
```

а не новым обязательным storage backend.

---

# Critical invariants

Нельзя ослабить:

- source/base ancestry validation;
- exact artifact identity;
- producer-role validation;
- CURRENT/installed-Hub equality model;
- Chat Manager reconciliation requirement;
- APPROVED-only install boundary;
- Doctor;
- fail-closed behavior;
- multi-Hub instance binding;
- existing update/install path;
- portable Hub semantics.

Drive timestamps, folder order and filenames — informational only.

---

# Что нужно получить от Manager Development

Сначала не писать код вслепую.

Нужно:

1. исследовать текущую Manager/Hub architecture и существующий inbox/install/current-generation path;
2. определить минимальный regression surface;
3. определить, какие части вообще требуют изменения Manager;
4. оценить вариант внешнего helper прежде, чем добавлять Drive-specific logic в Manager core;
5. разработать relay contract/schema;
6. threat-model stale/concurrent/multi-Hub/replay cases;
7. сформировать phased implementation plan;
8. добавить permanent regression tests;
9. только после этого реализовывать.

Приоритет:

> **максимально уменьшить ручное участие пользователя, не уменьшая надёжность Keelaryn.**

Если автоматизация и strict provenance конфликтуют, strict provenance имеет приоритет.

---

# Expected product result

В идеальном конечном состоянии пользователь не должен вручную переносить Keelaryn ZIP/MD между ChatGPT-чатами.

ChatGPT-side components используют Drive Relay.

Локальная сторона получает APPROVED через Drive Desktop/helper/native relay integration.

Manager остаётся authority:

```text
validate
→ install
→ Doctor
→ produce/publish CURRENT
```

Главная метрика успеха:

> ручное участие пользователя должно остаться только там, где требуется реальное решение или governance approval, а не механическая передача файлов.
