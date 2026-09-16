<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { Copy, LogOut, Menu, RefreshCw, Send, Settings, Trash2 } from 'lucide-vue-next'
import AdminPanel from './components/AdminPanel.vue'
import AuthPage from './components/AuthPage.vue'
import ChatSettingsDrawer from './components/ChatSettingsDrawer.vue'

const currentUser = ref(null)
const currentPage = ref('chat')
const showChatSettings = ref(false)
const inputText = ref('')
const isLoading = ref(false)
const isHistoryLoading = ref(true)
const regeneratingIndex = ref(-1)
const animationState = ref('idle')
const activeAbortController = ref(null)
const generationId = ref(0)
const messageList = ref(null)
const actionNotice = ref('')
const historyNotice = ref('')
const messages = ref([])
const welcomeMessage = { role: 'assistant', content: '你好，我是智能数字人助手。你可以向我提问。', welcome: true }

async function scrollToBottom() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function requestJson(url, options = {}) {
  let response
  try { response = await fetch(url, options) } catch (error) { throw new Error('无法连接后端，请确认Python服务已经启动') }
  let data = {}
  try { data = await response.json() } catch (error) { data = {} }
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试')
  return data
}

async function loadChatHistory() {
  try {
    const data = await requestJson('/api/chat-history?limit=100')
    const history = Array.isArray(data.messages) ? data.messages : []
    messages.value = history.map((message, index) => {
      const restored = { id: message.id, role: message.role, content: message.content, timestamp: message.timestamp }
      if (message.role === 'assistant' && history[index - 1]?.role === 'user') restored.userContent = history[index - 1].content
      return restored
    })
    if (!messages.value.length) messages.value = [{ ...welcomeMessage }]
  } catch (error) {
    historyNotice.value = `聊天历史加载失败：${error.message}`
    messages.value = [{ ...welcomeMessage }]
  } finally {
    isHistoryLoading.value = false
    animationState.value = 'idle'
    await scrollToBottom()
  }
}

function handleChatCleared(data) {
  generationId.value += 1
  if (activeAbortController.value) activeAbortController.value.abort()
  activeAbortController.value = null
  messages.value = [{ ...welcomeMessage }]
  actionNotice.value = data.warning ? `${data.message}；${data.warning}` : data.message
  historyNotice.value = ''
  regeneratingIndex.value = -1
  isLoading.value = false
  animationState.value = 'idle'
  inputText.value = ''
  scrollToBottom()
}

function removeTemporaryMessage(message) {
  const index = messages.value.indexOf(message)
  if (index >= 0) messages.value.splice(index, 1)
}

function parseSseEvent(eventText) {
  const dataText = eventText.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  if (!dataText || dataText === '[DONE]') return dataText === '[DONE]' ? { type: 'done' } : null
  try { return JSON.parse(dataText) } catch (error) { throw new Error('流式响应格式无法解析') }
}

async function streamChat(userContent, temporaryMessage, currentGeneration) {
  const controller = new AbortController()
  activeAbortController.value = controller
  animationState.value = 'thinking'
  let response
  try {
    response = await fetch('/api/chat/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userContent }), signal: controller.signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('无法连接后端，请确认Python服务已经启动')
  }
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok) {
    let data = {}
    try { data = await response.json() } catch (error) { data = {} }
    throw new Error(data.error || '请求失败，请稍后重试')
  }
  if (!contentType.includes('text/event-stream')) throw new Error('服务器未返回流式响应')
  if (!response.body) throw new Error('流式响应不可用')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let receivedDone = false
  let receivedContent = false
  try {
    while (true) {
      const result = await reader.read()
      if (currentGeneration !== generationId.value) return false
      if (result.done) break
      buffer += decoder.decode(result.value, { stream: true })
      const events = buffer.split(/\r?\n\r?\n/)
      buffer = events.pop() || ''
      for (const eventText of events) {
        const event = parseSseEvent(eventText)
        if (!event) continue
        if (event.type === 'delta' && typeof event.content === 'string' && event.content) {
          temporaryMessage.content += event.content
          receivedContent = true
          animationState.value = 'speaking'
          await scrollToBottom()
        } else if (event.type === 'error') {
          throw new Error(event.message || '模型请求失败，请检查API配置')
        } else if (event.type === 'done') {
          receivedDone = true
        }
      }
      if (receivedDone) break
    }
    buffer += decoder.decode()
    if (buffer.trim() && !receivedDone) {
      const event = parseSseEvent(buffer)
      if (event?.type === 'delta' && typeof event.content === 'string' && event.content) {
        temporaryMessage.content += event.content
        receivedContent = true
      } else if (event?.type === 'done') receivedDone = true
      else if (event?.type === 'error') throw new Error(event.message || '模型请求失败，请检查API配置')
    }
    if (!receivedDone) throw new Error('流式响应提前结束')
    if (!receivedContent || !temporaryMessage.content.trim()) throw new Error('AI没有返回有效内容')
    return true
  } finally {
    try { await reader.cancel() } catch (error) { }
    if (activeAbortController.value === controller) activeAbortController.value = null
  }
}

async function sendMessage() {
  const content = inputText.value.trim()
  if (!content || isLoading.value || isHistoryLoading.value) return
  messages.value.push({ role: 'user', content })
  const temporaryMessage = { role: 'assistant', content: '', userContent: content, temporary: true }
  messages.value.push(temporaryMessage)
  inputText.value = ''
  isLoading.value = true
  const currentGeneration = ++generationId.value
  await scrollToBottom()
  try {
    const completed = await streamChat(content, temporaryMessage, currentGeneration)
    if (completed) temporaryMessage.temporary = false
  } catch (error) {
    removeTemporaryMessage(temporaryMessage)
    if (error.name !== 'AbortError') { console.error(error); actionNotice.value = error.message }
  } finally {
    if (currentGeneration === generationId.value) { isLoading.value = false; animationState.value = 'idle' }
    await scrollToBottom()
  }
}

function stopGeneration() {
  generationId.value += 1
  if (activeAbortController.value) activeAbortController.value.abort()
  activeAbortController.value = null
  const temporary = messages.value.find((message) => message.temporary)
  if (temporary) removeTemporaryMessage(temporary)
  isLoading.value = false
  regeneratingIndex.value = -1
  animationState.value = 'idle'
  actionNotice.value = '已停止生成'
}

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

async function copyMessage(content) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(content)
    else {
      const textarea = document.createElement('textarea')
      textarea.value = content
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    actionNotice.value = '已复制'
    setTimeout(() => (actionNotice.value = ''), 1800)
  } catch (error) { actionNotice.value = '复制失败' }
}

async function deleteTurn(message, index) {
  if (isLoading.value || !message.userContent) return
  try {
    await requestJson('/api/chat-turn', {
      method: 'DELETE', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userContent: message.userContent, assistantContent: message.content }),
    })
    if (messages.value[index - 1]?.role === 'user') messages.value.splice(index - 1, 2)
    actionNotice.value = '对话已删除'
    setTimeout(() => (actionNotice.value = ''), 1800)
  } catch (error) { actionNotice.value = error.message }
}

async function regenerateMessage(message, index) {
  if (isLoading.value || !message.userContent) return
  const userContent = message.userContent
  const assistantContent = message.content
  animationState.value = 'speaking'
  isLoading.value = true
  regeneratingIndex.value = index
  actionNotice.value = '正在重新生成……'
  await scrollToBottom()
  try {
    await requestJson('/api/chat-turn', {
      method: 'DELETE', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userContent, assistantContent }),
    })
  } catch (error) {
    actionNotice.value = '重新生成失败：' + error.message
    isLoading.value = false
    regeneratingIndex.value = -1
    animationState.value = 'idle'
    await scrollToBottom()
    return
  }
  try {
    const data = await requestJson('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userContent }),
    })
    const reply = typeof data.reply === 'string' ? data.reply.trim() : ''
    if (!reply) throw new Error('AI没有返回有效内容')
    message.content = reply
    actionNotice.value = '已重新生成'
    setTimeout(() => (actionNotice.value = ''), 1800)
  } catch (error) {
    if (messages.value[index] === message) messages.value.splice(index, 1)
    actionNotice.value = '重新生成失败：' + error.message
  } finally {
    isLoading.value = false
    regeneratingIndex.value = -1
    animationState.value = 'idle'
    await scrollToBottom()
  }
}

onMounted(loadCurrentUser)

async function loadCurrentUser() {
  try {
    currentUser.value = await requestJson('/api/auth/me')
  } catch (error) {
    currentUser.value = null
    return
  }
  await loadChatHistory()
}

async function handleAuthenticated(user) {
  currentUser.value = user
  isHistoryLoading.value = true
  currentPage.value = 'chat'
  await loadChatHistory()
}

async function logout() {
  generationId.value += 1
  if (activeAbortController.value) activeAbortController.value.abort()
  activeAbortController.value = null
  try { await requestJson('/api/auth/logout', { method: 'POST' }) } catch (error) { }
  currentUser.value = null
  messages.value = []
  inputText.value = ''
  actionNotice.value = ''
  historyNotice.value = ''
  isHistoryLoading.value = true
  isLoading.value = false
  animationState.value = 'idle'
  currentPage.value = 'chat'
}
</script>

<template>
  <AuthPage v-if="!currentUser" @authenticated="handleAuthenticated" />
  <AdminPanel v-if="currentUser && currentPage === 'admin'" @back="currentPage = 'chat'" />
  <main v-if="currentUser && currentPage === 'chat'" class="page">
    <section class="app-shell">
      <header class="chat-header main-header">
        <button class="icon-button menu-button" type="button" title="对话设置" aria-label="打开对话设置" @click="showChatSettings = true"><Menu /></button>
        <h1>智能数字人助手</h1>
        <div class="header-actions">
          <span class="user-name">{{ currentUser.username }}</span>
          <button class="icon-button" type="button" title="退出登录" aria-label="退出登录" @click="logout"><LogOut /></button>
          <button class="icon-button settings-button" type="button" title="后台设置" aria-label="打开后台设置" @click="currentPage = 'admin'"><Settings /></button>
        </div>
      </header>
      <div class="main-layout">
        <section class="avatar-panel">
          <div class="orb-stage" :class="animationState" aria-hidden="true">
            <div class="orb-particle particle-one"></div>
            <div class="orb-particle particle-two"></div>
            <div class="orb-particle particle-three"></div>
            <div class="digital-orb"><span></span></div>
          </div>
        </section>
        <section class="chat-container inner-chat">
          <div v-if="actionNotice" class="chat-action-notice">{{ actionNotice }}</div>
          <div v-if="historyNotice" class="history-notice">{{ historyNotice }}</div>
          <div ref="messageList" class="message-list">
            <div v-if="isHistoryLoading" class="history-loading">正在加载聊天历史……</div>
            <template v-for="(message, index) in messages" :key="message.id || index">
              <div v-if="!message.temporary" class="message-row" :class="message.role === 'user' ? 'user-row' : 'assistant-row'">
                <div class="message-column">
                  <div class="message-bubble" :class="message.role === 'user' ? 'user-message' : 'assistant-message'">
                    {{ message.content }}
                  </div>
                  <div v-if="message.role === 'assistant'" class="message-actions">
                    <button class="message-action" type="button" title="复制" aria-label="复制AI回复" @click="copyMessage(message.content)"><Copy /></button>
                    <button v-if="message.userContent && !message.temporary" class="message-action" type="button" title="重新生成" aria-label="重新生成AI回复" :disabled="isLoading" @click="regenerateMessage(message, index)"><RefreshCw /></button>
                    <button v-if="message.userContent && !message.temporary" class="message-action danger-action" type="button" title="删除" aria-label="删除本轮对话" :disabled="isLoading" @click="deleteTurn(message, index)"><Trash2 /></button>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <div class="input-area">
            <textarea v-model="inputText" rows="2" placeholder="请输入你的问题" :disabled="isHistoryLoading" @keydown="handleKeydown"></textarea>
            <button class="send-button" type="button" :disabled="isHistoryLoading" :title="isLoading ? '停止生成' : '发送'" :aria-label="isLoading ? '停止生成' : '发送消息'" @click="isLoading ? stopGeneration() : sendMessage()">
              <Send v-if="!isLoading" />
              <span v-else>停止</span>
            </button>
          </div>
        </section>
      </div>
    </section>
    <ChatSettingsDrawer v-if="showChatSettings" @close="showChatSettings = false" @chat-cleared="handleChatCleared" />
  </main>
</template>
