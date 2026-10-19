<script setup lang="ts">
import { computed } from 'vue'
import { useDashboard } from '../state/context'

const dash = useDashboard()
const CATALOG = ['catalog', 'platform', 'provider']
const YOURS = ['tools', 'secrets', 'resources', 'detail', 'wbtool', 'wbinstall']
const HUB = ['hub', 'run']
const scope = computed(() => CATALOG.includes(dash.view) ? 'catalog' : HUB.includes(dash.view) ? 'hub' : YOURS.includes(dash.view) ? 'yours' : '')
const scopes = computed(() => [
  { key: 'catalog', label: 'Catalog', n: dash.toolCountText, go: 'catalog' },
  { key: 'yours', label: 'Yours', n: dash.ownToolCount || '', go: 'tools' },
  ...(dash.hubOn ? [{ key: 'hub', label: 'Hub', n: '', go: 'hub' }] : []),
])
</script>

<template>
<div class="pl tools-scope-wrap"><div class="seg pl-seg tools-scope" role="radiogroup" aria-label="Tools">
  <button v-for="s in scopes" :key="s.key" role="radio" :aria-checked="scope === s.key" :class="{ on: scope === s.key }" @click="scope === s.key || dash.go(s.go)">{{ s.label }} <span v-if="s.n">{{ s.n }}</span></button>
</div></div>
</template>

<style>
.tools-scope-wrap{padding-bottom:0;margin-bottom:-14px}
.tools-scope{margin:18px 0 0}
</style>
