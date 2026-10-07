<template>
  <div style="padding:16px;max-width:420px">
    <h1>设置 · 邻里互借</h1>
    <div class="muted">看板名：{{ boardName }}</div>
    <label class="muted" for="grace">宽限日（天，0 或正整数；逾期 = 应还日 + 宽限日之后）</label>
    <input id="grace" v-model="graceInput" placeholder="0" />
    <button @click="save">保存</button>
    <div v-if="err" class="muted" style="color:#a33">{{ err }}</div>
    <div v-if="ok" class="muted">已保存，看板逾期分栏已按新宽限刷新</div>
  </div>
</template>
<script setup>
import { ref, inject, onMounted } from 'vue'
import { api } from '../api'
const reload = inject('reloadBoard')
const boardName = ref('')
const graceInput = ref('0')
const err = ref('')
const ok = ref(false)
let saved = '0'
onMounted(async () => {
  const s = await api('/settings')
  boardName.value = s.board_name || ''
  saved = String(s.grace_days ?? '0')
  graceInput.value = saved
})
async function save() {
  err.value = ''; ok.value = false
  const raw = graceInput.value.trim()
  const n = Number(raw)
  if (raw === '' || !Number.isInteger(n) || n < 0) {
    err.value = '宽限日必须是 0 或正整数'
    graceInput.value = saved
    return
  }
  try {
    const r = await api('/settings', { method: 'PUT', body: JSON.stringify({ grace_days: n }) })
    saved = String(r.grace_days)
    graceInput.value = saved
    ok.value = true
    await reload()
  } catch (e) {
    err.value = '保存失败：' + e.message
    graceInput.value = saved
    await reload()
  }
}
</script>
