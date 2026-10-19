import type { components, paths } from './types.gen'

export type Schemas = components['schemas']
export type TableSummary = Schemas['TableSummary']
export type Table = Schemas['Table']
export type Row = Schemas['Row']
export type Run = Schemas['Run']
export type RunDetail = Schemas['RunDetail']
export type Install = Schemas['Install']
export type InstallDetail = Schemas['InstallDetail']
export type Trigger = Schemas['Trigger']
export type ToolDefinition = Schemas['ToolDefinition']
export type UnattendedBudget = Schemas['UnattendedBudget']
export type WorkbenchError = Schemas['Error']

type Json<T> = T extends { content: { 'application/json': infer B } } ? B : never
type Ok<P extends keyof paths, M extends keyof paths[P]> =
  paths[P][M] extends { responses: infer R }
    ? R extends { 200: infer S } ? Json<S> : R extends { 202: infer S } ? Json<S> : never
    : never

export type ApiCall = (path: string, opts?: { method?: string, headers?: Record<string, string>, body?: string }) => Promise<unknown>

const BASE = '/api/workbench'
const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v))
  const out = s.toString()
  return out ? `?${out}` : ''
}
const json = (body: unknown) => ({ headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export function workbenchClient(api: ApiCall) {
  const get = <T>(path: string) => api(BASE + path) as Promise<T>
  const send = <T>(method: string, path: string, body?: unknown, headers?: Record<string, string>) =>
    api(BASE + path, { method, ...(body === undefined ? {} : json(body)), ...(headers ? { headers: { ...(body === undefined ? {} : json(body).headers), ...headers } } : {}) }) as Promise<T>
  return {
    listTables: () => get<Ok<'/tables', 'get'>>('/tables'),
    getTable: (id: string) => get<Ok<'/tables/{tableId}', 'get'>>(`/tables/${encodeURIComponent(id)}`),
    listRows: (id: string, cursor?: string, limit?: number) => get<Ok<'/tables/{tableId}/rows', 'get'>>(`/tables/${encodeURIComponent(id)}/rows${q({ cursor, limit })}`),
    query: (sql: string, limit?: number) => send<Ok<'/query', 'post'>>('POST', '/query', { sql, limit }),
    listRuns: (filter: { install?: string, table?: string, status?: string, cursor?: string } = {}) => get<Ok<'/runs', 'get'>>(`/runs${q(filter)}`),
    getRun: (id: string, traceCursor?: string) => get<Ok<'/runs/{runId}', 'get'>>(`/runs/${encodeURIComponent(id)}${q({ trace_cursor: traceCursor })}`),
    stopRun: (id: string) => send<Ok<'/runs/{runId}/stop', 'post'>>('POST', `/runs/${encodeURIComponent(id)}/stop`),
    retryFailedRows: (id: string) => send<Ok<'/runs/{runId}/retry-failed', 'post'>>('POST', `/runs/${encodeURIComponent(id)}/retry-failed`),
    listInstalls: () => get<Ok<'/installs', 'get'>>('/installs'),
    getInstall: (name: string) => get<Ok<'/installs/{installName}', 'get'>>(`/installs/${encodeURIComponent(name)}`),
    listTriggers: () => get<Ok<'/triggers', 'get'>>('/triggers'),
    listMyTools: () => get<Ok<'/tools/mine', 'get'>>('/tools/mine'),
    getTool: (id: string) => get<Ok<'/tools/{toolId}', 'get'>>(`/tools/${encodeURIComponent(id)}`),
  }
}

export type WorkbenchClient = ReturnType<typeof workbenchClient>
