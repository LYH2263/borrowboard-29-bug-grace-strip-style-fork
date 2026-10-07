<template>
  <div>
    <div class="status-bar">
      <span>可借 {{ counts.available || 0 }}</span>
      <span>在借 {{ counts.active || 0 }}</span>
      <span>逾期 {{ counts.overdue || 0 }}</span>
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
const board = ref({ available: [], active: [], overdue: [] })
async function load() {
  // 顶细条数字只认 /board 这一个世界；借还记录页挂载时按同一判定自取。
  board.value = await api('/board')
  counts.value = board.value.counts || {}
}
provide('board', board)
provide('reloadBoard', load)
onMounted(load)
</script>
