<script setup>
import { ref } from 'vue'
import ApiRepository from './ApiRepository.vue'
import KnowledgeBase from './KnowledgeBase.vue'
import UserProfile from './UserProfile.vue'

const emit = defineEmits(['back'])
const activeSection = ref('api')
</script>

<template>
  <main class="admin-page">
    <section class="admin-container">
      <aside class="admin-sidebar">
        <button class="back-button" type="button" @click="emit('back')">返回聊天</button>
        <h1>后台管理</h1>
        <nav class="admin-nav">
          <button type="button" :class="{ active: activeSection === 'api' }" @click="activeSection = 'api'">API仓库</button>
          <button type="button" :class="{ active: activeSection === 'knowledge' }" @click="activeSection = 'knowledge'">知识库</button>
          <button type="button" :class="{ active: activeSection === 'user' }" @click="activeSection = 'user'">用户信息</button>
        </nav>
      </aside>
      <div class="admin-content">
        <ApiRepository v-if="activeSection === 'api'" />
        <KnowledgeBase v-if="activeSection === 'knowledge'" />
        <UserProfile v-if="activeSection === 'user'" />
      </div>
    </section>
  </main>
</template>
