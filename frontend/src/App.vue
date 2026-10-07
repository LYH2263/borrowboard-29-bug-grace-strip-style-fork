<template>
  <div>
    <div class="status-bar">
      <span>可借 {{ counts.available || 0 }}</span>
      <span>在借 {{ counts.active || 0 }}</span>
      <span>逾期 {{ counts.overdue || 0 }}</span>
      <span class="muted">宽限 {{ graceDays }} 天</span>
    </div>
    <nav class="topnav">
      <router-link to="/">看板</router-link>
      <router-link to="/list">上架</router-link>
      <router-link to="/loans">借还记录</router-link>
      <router-link to="/owners">物主</router-link>
      <router-link to="/settings">设置</router-link>
    </nav>
    <router-view @refresh="load" />
  </div>
</template>
<script setup>
import { ref, onMounted, provide } from 'vue'
import { api } from './api'
const counts = ref({})
const graceDays = ref(0)
const board = ref({ available: [], active: [], overdue: [] })
async function load() {
  board.value = await api('/board')
  counts.value = board.value.counts || {}
  graceDays.value = board.value.grace_days ?? 0
}
provide('board', board)
provide('reloadBoard', load)
onMounted(load)
</script>
