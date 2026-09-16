<script setup>
import { ref } from 'vue'

const emit = defineEmits(['authenticated'])
const mode = ref('login')
const username = ref('')
const password = ref('')
const isSubmitting = ref(false)
const notice = ref('')

async function submit() {
  const name = username.value.trim()
  if (!name || !password.value) { notice.value = '请输入用户名和密码'; return }
  isSubmitting.value = true
  notice.value = ''
  try {
    let response
    try {
      response = await fetch(`/api/auth/${mode.value}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: name, password: password.value }),
      })
    } catch (error) { throw new Error('无法连接后端，请确认Python服务已经启动') }
    let data = {}
    try { data = await response.json() } catch (error) { data = {} }
    if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试')
    emit('authenticated', data)
  } catch (error) { notice.value = error.message } finally { isSubmitting.value = false }
}

function switchMode(next) { mode.value = next; notice.value = '' }
</script>

<template>
  <main class="auth-page">
    <section class="auth-card">
      <h1>智能数字人助手</h1>
      <p class="auth-subtitle">登录后使用自己的对话记录、知识库和用户信息</p>
      <div class="auth-tabs">
        <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>
      <p v-if="notice" class="auth-notice">{{ notice }}</p>
      <div class="auth-fields">
        <input v-model="username" type="text" autocomplete="username" placeholder="用户名（2-32位）" @keydown.enter="submit" />
        <input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" placeholder="密码（至少6位）" @keydown.enter="submit" />
      </div>
      <button class="auth-submit" type="button" :disabled="isSubmitting" @click="submit">
        {{ isSubmitting ? '请稍候……' : mode === 'login' ? '登录' : '注册并登录' }}
      </button>
      <p class="auth-hint">{{ mode === 'login' ? '还没有账号？点上方“注册”创建。' : '注册后自动登录，数据保存在独立目录中。' }}</p>
    </section>
  </main>
</template>
