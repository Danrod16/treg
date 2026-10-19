---
title: The Workbench — tables, runs and triggers in the dashboard
status: shell behind TREG_WORKBENCH_ENABLED; the tabs fill in over the next changes
sources:
  - contracts/workbench/openapi.yaml
  - frontend/src/workbench/WorkbenchPage.vue
  - frontend/src/workbench/routes.ts
  - frontend/src/workbench/api/client.ts
  - frontend/src/state/workbench.js
  - frontend/scripts/fixture-plugin.mjs
related:
  - interface/dashboard.md
  - architecture/workbench-storage.md
  - architecture/hub.md
---

# The Workbench

One navigation item, three tabs: the team's tables, the runs that fill them, and the triggers that
start those runs. `/meta.workbench` (`workbench_enabled`) decides whether the entry exists; with it
off the dashboard is unchanged.

## The contract comes first

`contracts/workbench/openapi.yaml` is the agreed shape of the Workbench API, written before the
routes exist so the dashboard, the CLI and the MCP tools are built against one description. It sits
at the repository root, not under `frontend/`, because the server's tests validate their responses
against the same file. `contracts/workbench/fixtures/` holds one JSON answer per operation and case,
named `<operationId>.<case>.json`; they are the only invented data and carry example names and
amounts only.

The TypeScript types are generated from the contract (`npm --prefix frontend run contract:types`)
and committed; `frontend/src/workbench/api/client.ts` is the only module that imports them, and
pages read view models from it. Changing the API means changing the yaml, regenerating, and
adjusting fixtures in the same change.

## Fixtures reach the page two ways, from one directory

`TREG_FIXTURES=1 npm --prefix frontend run dev` mounts `scripts/fixture-plugin.mjs`, which answers
`/api/workbench/*` from the fixtures instead of proxying to the server. Browser tests will
intercept the same paths with Playwright and read the same files. There is no second copy of the
data anywhere.

## Addresses

`#workbench/<tab>` with the table, run or cell carried the way `routes.ts` parses and prints it.
The view is in both hash whitelists, like every other view ([dashboard](dashboard.md)), and
`syncTabUrl` keeps the address current as the tab or the open object changes.

## Table contract boundaries

The contract distinguishes the verified database generation and schema version from the metadata
revision and each row's revision. Ready tables require verified versions; creating tables can
return null. `columns` is the API projection of `TableDoc.column_metadata`; column IDs survive SQL
renames. `Row.cells` contains business values, while write requests use explicit `values` envelopes.

Presentation edits address stable column IDs. Physical changes use separate maintenance operations,
never business Runs. Creation defines structure; imports use bounded writes after readiness.
Conditional patch never recreates a deleted row. A matching committed write receipt precedes new
schema/row revision checks, after authorization, maintenance, generation and expiry checks. Expired
or unknown outcomes cannot be retried with an automatically replaced identity. The write-key wire
encoding and recovery window must be agreed before SDK writes ship.
