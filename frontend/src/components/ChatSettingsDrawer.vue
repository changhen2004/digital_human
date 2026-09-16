<script setup>
import { computed, onMounted, ref } from 'vue'
import { Trash2 } from 'lucide-vue-next'

const emit = defineEmits(['close', 'chat-cleared'])
const platforms = ref([])
const categories = ref([])
const activeCategories = ref([])
const modelId = ref('')
const summaryModelId = ref('')
const embeddingModelId = ref('')
const temperature = ref(0.7)
const topP = ref(0.9)
const maxTokens = ref(2000)
const isLoading = ref(true)
const isSaving = ref(false)
const clearingChat = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const clearChatError = ref('')
const clearChatSuccess = ref('')

const availableModels = computed(() => {
  const models = []
  for (const platform of platforms.value) {
    for (const model of platform.models) {
      if (model.enabled) models.push({ id: model.id, platformId: platform.id, label: `${platform.name} / ${model.name}` })
    }
  }
  return models
})

async function requestJson(url, options = {}) {
  let response
  try { response = await fetch(url, options) } catch (error) { throw new Error('无法连接后端，请确认Python服务已经启动') }
  let data = {}
  try { data = await response.json() } catch (error) { data = {} }
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试')
  return data
}

async function loadSettings() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [platformData, categoryData, settings] = await Promise.all([
      requestJson('/api/platforms'), requestJson('/api/knowledge-bases'), requestJson('/api/chat-settings'),
    ])
    platforms.value = Array.isArray(platformData.platforms) ? platformData.platforms : []
    categories.value = Array.isArray(categoryData.categories) ? categoryData.categories : []
    const validIds = new Set(categories.value.map((item) => item.id))
    activeCategories.value = Array.isArray(settings.activeCategories) ? settings.activeCategories.filter((item) => validIds.has(item)) : []
    modelId.value = settings.modelId || ''
    summaryModelId.value = settings.summaryModelId || ''
    embeddingModelId.value = settings.embeddingModelId || ''
    temperature.value = settings.temperature
    topP.value = settings.topP
    maxTokens.value = settings.maxTokens
  } catch (error) { errorMessage.value = error.message } finally { isLoading.value = false }
}

function findModel(id) { return availableModels.value.find((model) => model.id === id) }

async function saveSettings() {
  if (clearingChat.value) return
  const selectedModel = findModel(modelId.value)
  const selectedSummaryModel = findModel(summaryModelId.value)
  const selectedEmbeddingModel = findModel(embeddingModelId.value)
  if (!selectedModel) { errorMessage.value = '请选择一个已启用的对话模型'; return }
  isSaving.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const data = await requestJson('/api/chat-settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platformId: selectedModel.platformId, modelId: selectedModel.id,
        summaryPlatformId: selectedSummaryModel?.platformId || '', summaryModelId: selectedSummaryModel?.id || '',
        embeddingPlatformId: selectedEmbeddingModel?.platformId || '', embeddingModelId: selectedEmbeddingModel?.id || '',
        temperature: Number(temperature.value), topP: Number(topP.value), maxTokens: Number(maxTokens.value),
        activeCategories: activeCategories.value,
      }),
    })
    successMessage.value = data.message || '对话设置已保存'
    setTimeout(() => emit('close'), data.message ? 1800 : 600)
  } catch (error) { errorMessage.value = error.message } finally { isSaving.value = false }
}

async function clearChatHistory() {
  if (clearingChat.value || isSaving.value) return
  const confirmed = confirm('确定清空全部聊天记录吗？此操作无法恢复，但不会删除长期记忆、用户信息和知识库。')
  if (!confirmed) return
  clearingChat.value = true
  clearChatError.value = ''
  clearChatSuccess.value = ''
  try {
    const data = await requestJson('/api/chat-history', { method: 'DELETE' })
    clearChatSuccess.value = data.warning ? `${data.message}；${data.warning}` : data.message
    emit('chat-cleared', data)
  } catch (error) {
    clearChatError.value = error.message
  } finally {
    clearingChat.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <div class="chat-settings-overlay" @click.self="emit('close')">
    <aside class="chat-settings-drawer">
      <header class="drawer-header"><h2>对话设置</h2><button class="drawer-close" type="button" @click="emit('close')">关闭</button></header>
      <div v-if="isLoading" class="drawer-state">正在加载设置……</div>
      <div v-else class="drawer-content">
        <div v-if="errorMessage" class="drawer-notice error">{{ errorMessage }}</div>
        <div v-if="successMessage" class="drawer-notice success">{{ successMessage }}</div>
        <div v-if="!availableModels.length" class="drawer-empty">没有可用模型，请先去API仓库添加并启用模型。</div>
        <form v-else @submit.prevent="saveSettings">
          <label class="drawer-field">对话模型<select v-model="modelId"><option value="">请选择模型</option><option v-for="model in availableModels" :key="`chat-${model.id}`" :value="model.id">{{ model.label }}</option></select></label>
          <label class="drawer-field">记忆总结模型<select v-model="summaryModelId"><option value="">不启用自动总结</option><option v-for="model in availableModels" :key="`summary-${model.id}`" :value="model.id">{{ model.label }}</option></select><span>未选择时跳过自动总结。</span></label>
          <label class="drawer-field">向量化模型<select v-model="embeddingModelId"><option value="">不启用向量功能</option><option v-for="model in availableModels" :key="`embedding-${model.id}`" :value="model.id">{{ model.label }}</option></select><span>同时用于RAG知识库和长期记忆。</span></label>
          <fieldset class="drawer-categories"><legend>启用知识库</legend><label v-for="category in categories" :key="category.id"><input v-model="activeCategories" type="checkbox" :value="category.id" />{{ category.name }}</label><p v-if="!categories.length">暂无知识库分类</p></fieldset>
          <label class="drawer-field">Temperature<input v-model="temperature" type="number" min="0" max="2" step="0.1" /><span>范围0到2。</span></label>
          <label class="drawer-field">Top P<input v-model="topP" type="number" min="0" max="1" step="0.1" /><span>范围0到1。</span></label>
          <label class="drawer-field">Max Tokens<input v-model="maxTokens" type="number" min="1" step="1" /></label>
          <button class="primary-button drawer-save" :disabled="isSaving || clearingChat">{{ isSaving ? '保存中' : '保存设置' }}</button>
        </form>

        <section class="drawer-danger-zone">
          <h3>危险操作</h3>
          <p>清空后将删除全部聊天消息，且无法恢复。</p>
          <div v-if="clearChatSuccess" class="drawer-clear-message success">{{ clearChatSuccess }}</div>
          <div v-if="clearChatError" class="drawer-clear-message error">{{ clearChatError }}</div>
          <button class="clear-chat-button" type="button" title="清空全部聊天记录" aria-label="清空全部聊天记录" :disabled="clearingChat || isSaving" @click="clearChatHistory">
            <Trash2 />
            <span>{{ clearingChat ? '正在清空……' : '清空聊天记录' }}</span>
          </button>
        </section>
      </div>
    </aside>
  </div>
</template>
