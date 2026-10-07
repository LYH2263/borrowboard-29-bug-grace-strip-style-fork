<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="i in board.available" :key="i.id" class="item">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <button @click="lend(i.id)">借出通过</button>
      </div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <button @click="ret(l.id)">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const forms = reactive({})
watch(board, (b) => {
  for (const i of (b.available || [])) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31' }
  }
}, { immediate: true, deep: true })
async function lend(id) {
  await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
  await reload()
}
async function ret(id) {
  const p = await api('/loans/' + id + '/return-preview')
  const msg = `确认归还「${p.title}」（${p.borrower}）？\n应还 ${p.due_date} · 宽限 ${p.grace_days} 天 · ${p.overdue ? '已逾期' : '未逾期'}`
  if (!confirm(msg)) return
  try {
    await api('/loans/' + id + '/return', { method: 'POST', body: JSON.stringify({ grace_version: p.grace_version }) })
  } catch (e) {
    if (String(e.message).includes('grace_changed')) {
      alert('宽限设置刚刚变更，逾期判定已变化，请重新确认归还')
    } else {
      alert('归还失败：' + e.message)
    }
  }
  await reload()
}
</script>
