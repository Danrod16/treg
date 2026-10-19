import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FIXTURES = fileURLToPath(new URL('../../contracts/workbench/fixtures/', import.meta.url))

// Only mounted when TREG_FIXTURES=1: the dev proxy otherwise forwards /api/workbench to the Python
// server, and the same requests must keep reaching it once the real routes exist.
const ROUTES = [
  ['GET', /^\/tables$/, 'listTables.default'],
  ['POST', /^\/tables$/, 'createTable.default'],
  ['GET', /^\/tables\/tbl_01HZX1NEW$/, 'getTable.creating'],
  ['GET', /^\/tables\/[^/]+$/, 'getTable.leads'],
  ['GET', /^\/tables\/[^/]+\/rows/, 'listRows.leads'],
  ['POST', /^\/tables\/[^/]+\/rows$/, 'writeRows.default'],
  ['POST', /^\/tables\/[^/]+\/export$/, 'exportTable.default'],
  ['POST', /^\/query$/, 'query.default'],
  ['GET', /^\/runs$/, 'listRuns.default'],
  ['GET', /^\/runs\/r_8e90/, 'getRun.r_8e90.partial'],
  ['GET', /^\/runs\/[^/]+$/, 'getRun.r_8f21'],
  ['POST', /^\/runs\/[^/]+\/stop$/, 'stopRun.default'],
  ['POST', /^\/runs\/[^/]+\/retry-failed$/, 'retryFailedRows.default'],
  ['GET', /^\/installs$/, 'listInstalls.default'],
  ['GET', /^\/installs\/competitor-watch$/, 'getInstall.competitor-watch'],
  ['GET', /^\/installs\/[^/]+$/, 'getInstall.lead-emails'],
  ['PUT', /^\/installs\/[^/]+$/, 'getInstall.lead-emails'],
  ['POST', /^\/installs\/[^/]+\/run$/, 'runInstall.dryRun'],
  ['GET', /^\/tools\/mine$/, 'listMyTools.default'],
  ['GET', /^\/tools\/[^/]+$/, 'getTool.lead-emails'],
  ['GET', /^\/triggers$/, 'listTriggers.default'],
]

export function workbenchFixtures() {
  return {
    name: 'treg-workbench-fixtures',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (!url.pathname.startsWith('/api/workbench/')) return next()
        const path = url.pathname.slice('/api/workbench'.length)
        const hit = ROUTES.find(([method, re]) => method === req.method && re.test(path))
        const file = hit && `${FIXTURES}${hit[2]}.json`
        if (!file || !existsSync(file)) { res.statusCode = 404; res.end(JSON.stringify({ detail: `no fixture for ${req.method} ${path}`, code: 'not_found' })); return }
        res.setHeader('content-type', 'application/json')
        res.statusCode = req.method === 'GET' || hit[2].startsWith('getInstall') ? 200 : 202
        res.end(readFileSync(file))
      })
    },
  }
}
