<script setup>
import { computed, onMounted, ref } from 'vue'

const platforms = ref([])
const selectedPlatformId = ref('')
const isLoading = ref(false)
const loadError = ref('')
const notice = ref('')
const noticeType = ref('success')
const showPlatformForm = ref(false)
const formMode = ref('create')
const platformName = ref('')
const platformBaseUrl = ref('')
const platformApiKey = ref('')
const clearSavedKey = ref(false)
const isSavingPlatform = ref(false)
const isTesting = ref(false)
const isFetchingModels = ref(false)
const modelName = ref('')
const isAddingModel = ref(false)
const busyModelId = ref('')
let noticeTimer

const selectedPlatform = computed(() => {
  return platforms.value.find((platform) => platform.id === selectedPlatformId.value) || null
})

function showNotice(message, type = 'success') {
  clearTimeout(noticeTimer)
  notice.value = message
  noticeType.value = type

  if (type === 'success') {
    noticeTimer = setTimeout(() => {
      notice.value = ''
    }, 3000)
  }
}

async function requestApi(url, options = {}) {
  let response

  try {
    response = await fetch(url, options)
  } catch (error) {
    throw new Error('无法连接后端，请确认Python服务已经启动')
  }

  let data = {}
  try {
    data = await response.json()
  } catch (error) {
    data = {}
  }

  if (!response.ok) {
    throw new Error(data.error || '请求失败，请稍后重试')
  }

  return data
}

async function loadPlatforms(preferredId = '') {
  isLoading.value = true
  loadError.value = ''

  try {
    const data = await requestApi('/api/platforms')
    platforms.value = Array.isArray(data.platforms) ? data.platforms : []
    const nextId = preferredId || selectedPlatformId.value
    selectedPlatformId.value = platforms.value.some((item) => item.id === nextId)
      ? nextId
      : platforms.value[0]?.id || ''
  } catch (error) {
    loadError.value = error.message
  } finally {
    isLoading.value = false
  }
}

function openCreateForm() {
  formMode.value = 'create'
  platformName.value = ''
  platformBaseUrl.value = ''
  platformApiKey.value = ''
  clearSavedKey.value = false
  showPlatformForm.value = true
}

function openEditForm() {
  if (!selectedPlatform.value) {
    return
  }

  formMode.value = 'edit'
  platformName.value = selectedPlatform.value.name
  platformBaseUrl.value = selectedPlatform.value.baseUrl
  platformApiKey.value = ''
  clearSavedKey.value = false
  showPlatformForm.value = true
}

function closePlatformForm() {
  if (isSavingPlatform.value) {
    return
  }
  platformApiKey.value = ''
  showPlatformForm.value = false
}

async function savePlatform() {
  const name = platformName.value.trim()
  const baseUrl = platformBaseUrl.value.trim()

  if (!name || !baseUrl) {
    showNotice('平台名称和API Base URL不能为空', 'error')
    return
  }

  isSavingPlatform.value = true
  const body = { name, baseUrl }
  if (formMode.value === 'create' || platformApiKey.value || clearSavedKey.value) {
    body.apiKey = clearSavedKey.value ? '' : platformApiKey.value
  }

  try {
    const isCreate = formMode.value === 'create'
    const url = isCreate ? '/api/platforms' : `/api/platforms/${selectedPlatformId.value}`
    const data = await requestApi(url, {
      method: isCreate ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    platformApiKey.value = ''
    showPlatformForm.value = false
    await loadPlatforms(data.id)
    showNotice(isCreate ? '平台添加成功' : '平台保存成功')
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isSavingPlatform.value = false
  }
}

async function deletePlatform() {
  const platform = selectedPlatform.value
  if (!platform || !confirm(`确定删除“${platform.name}”吗？该平台下保存的模型也会被删除。`)) {
    return
  }

  try {
    await requestApi(`/api/platforms/${platform.id}`, { method: 'DELETE' })
    selectedPlatformId.value = ''
    await loadPlatforms()
    showNotice('平台已删除')
  } catch (error) {
    showNotice(error.message, 'error')
  }
}

async function testConnection() {
  if (!selectedPlatform.value) {
    return
  }

  isTesting.value = true
  try {
    const data = await requestApi(`/api/platforms/${selectedPlatform.value.id}/test`, {
      method: 'POST',
    })
    showNotice(data.message || '连接成功')
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isTesting.value = false
  }
}

async function fetchModels() {
  if (!selectedPlatform.value) {
    return
  }

  isFetchingModels.value = true
  try {
    const data = await requestApi(`/api/platforms/${selectedPlatform.value.id}/fetch-models`, {
      method: 'POST',
    })
    const count = Array.isArray(data.models) ? data.models.length : 0
    await loadPlatforms(selectedPlatformId.value)
    showNotice(count ? `拉取完成，当前共${count}个模型` : '拉取完成，未发现有效模型')
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isFetchingModels.value = false
  }
}

async function addModel() {
  const name = modelName.value.trim()
  if (!name || !selectedPlatform.value) {
    return
  }

  isAddingModel.value = true
  try {
    await requestApi(`/api/platforms/${selectedPlatform.value.id}/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    modelName.value = ''
    await loadPlatforms(selectedPlatformId.value)
    showNotice('模型添加成功')
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isAddingModel.value = false
  }
}

async function updateModel(model, changes) {
  busyModelId.value = model.id
  try {
    await requestApi(`/api/platforms/${selectedPlatform.value.id}/models/${model.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    })
    await loadPlatforms(selectedPlatformId.value)
    showNotice('模型已更新')
  } catch (error) {
    showNotice(error.message, 'error')
    await loadPlatforms(selectedPlatformId.value)
  } finally {
    busyModelId.value = ''
  }
}

function renameModel(model) {
  const name = prompt('请输入新的模型名称', model.name)
  if (name === null) {
    return
  }
  if (!name.trim()) {
    showNotice('模型名称不能为空', 'error')
    return
  }
  updateModel(model, { name: name.trim() })
}

function toggleModel(model, event) {
  updateModel(model, { enabled: event.target.checked })
}

async function deleteModel(model) {
  if (!confirm(`确定删除模型“${model.name}”吗？`)) {
    return
  }

  busyModelId.value = model.id
  try {
    await requestApi(`/api/platforms/${selectedPlatform.value.id}/models/${model.id}`, {
      method: 'DELETE',
    })
    await loadPlatforms(selectedPlatformId.value)
    showNotice('模型已删除')
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    busyModelId.value = ''
  }
}

onMounted(loadPlatforms)
</script>

<template>
  <section class="repository-section">
    <header class="repository-header">
      <div>
        <h2>API仓库</h2>
        <p>管理OpenAI兼容API平台及模型</p>
      </div>
      <button class="primary-button" type="button" @click="openCreateForm">新增平台</button>
    </header>

    <div v-if="notice" class="notice" :class="noticeType">{{ notice }}</div>

    <div v-if="isLoading" class="state-card">正在加载平台……</div>
    <div v-else-if="loadError" class="state-card error-state">
      <p>{{ loadError }}</p>
      <button class="secondary-button" type="button" @click="loadPlatforms()">重新加载</button>
    </div>
    <div v-else-if="!platforms.length" class="state-card empty-state">
      <h3>还没有API平台</h3>
      <p>添加一个OpenAI兼容平台后，可以测试连接并管理模型。</p>
      <button class="primary-button" type="button" @click="openCreateForm">添加平台</button>
    </div>

    <div v-else class="repository-layout">
      <aside class="platform-panel">
        <div class="panel-title">平台列表</div>
        <button
          v-for="platform in platforms"
          :key="platform.id"
          class="platform-item"
          :class="{ selected: platform.id === selectedPlatformId }"
          type="button"
          @click="selectedPlatformId = platform.id"
        >
          <strong>{{ platform.name }}</strong>
          <span class="platform-url">{{ platform.baseUrl }}</span>
          <span>{{ platform.models.length }} 个模型 · {{ platform.hasApiKey ? '已保存Key' : '无Key' }}</span>
        </button>
        <button class="secondary-button full-button" type="button" @click="openCreateForm">新增平台</button>
      </aside>

      <div v-if="selectedPlatform" class="platform-detail">
        <section class="detail-card">
          <div class="detail-heading">
            <div>
              <h3>{{ selectedPlatform.name }}</h3>
              <p class="break-text">{{ selectedPlatform.baseUrl }}</p>
              <p>{{ selectedPlatform.hasApiKey ? `API Key：${selectedPlatform.apiKeyMask}` : '未保存API Key' }}</p>
            </div>
            <div class="button-group">
              <button class="secondary-button" type="button" @click="openEditForm">编辑平台</button>
              <button class="danger-button" type="button" @click="deletePlatform">删除平台</button>
            </div>
          </div>
          <div class="button-group action-group">
            <button class="secondary-button" type="button" :disabled="isTesting" @click="testConnection">
              {{ isTesting ? '测试中' : '测试连接' }}
            </button>
            <button class="primary-button" type="button" :disabled="isFetchingModels" @click="fetchModels">
              {{ isFetchingModels ? '拉取中' : '拉取模型' }}
            </button>
          </div>
        </section>

        <section class="detail-card">
          <h3>模型列表</h3>
          <form class="model-add-form" @submit.prevent="addModel">
            <input v-model="modelName" type="text" placeholder="输入模型名称" />
            <button class="primary-button" type="submit" :disabled="isAddingModel || !modelName.trim()">
              {{ isAddingModel ? '添加中' : '添加模型' }}
            </button>
          </form>

          <p v-if="!selectedPlatform.models.length" class="empty-models">暂无模型，可以拉取或手动添加</p>
          <div v-else class="model-list">
            <div v-for="model in selectedPlatform.models" :key="model.id" class="model-item">
              <div class="model-info">
                <strong>{{ model.name }}</strong>
                <label>
                  <input
                    type="checkbox"
                    :checked="model.enabled"
                    :disabled="busyModelId === model.id"
                    @change="toggleModel(model, $event)"
                  />
                  {{ model.enabled ? '已启用' : '已禁用' }}
                </label>
              </div>
              <div class="button-group">
                <button
                  class="text-button"
                  type="button"
                  :disabled="busyModelId === model.id"
                  @click="renameModel(model)"
                >
                  改名
                </button>
                <button
                  class="text-button danger-text"
                  type="button"
                  :disabled="busyModelId === model.id"
                  @click="deleteModel(model)"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <div v-if="showPlatformForm" class="form-overlay" @click.self="closePlatformForm">
      <form class="platform-form" @submit.prevent="savePlatform">
        <h3>{{ formMode === 'create' ? '新增平台' : '编辑平台' }}</h3>
        <label>
          平台名称
          <input v-model="platformName" type="text" placeholder="例如：本地Ollama" />
        </label>
        <label>
          API Base URL
          <input v-model="platformBaseUrl" type="text" placeholder="http://127.0.0.1:11434/v1" />
        </label>
        <p class="form-help">也可以填写 http://127.0.0.1:1234/v1 或 https://example.com/v1</p>
        <label>
          API Key
          <input v-model="platformApiKey" type="password" placeholder="允许为空" />
        </label>
        <p v-if="formMode === 'edit'" class="form-help">留空表示保留原有Key</p>
        <label v-if="formMode === 'edit' && selectedPlatform?.hasApiKey" class="clear-key-option">
          <input v-model="clearSavedKey" type="checkbox" />
          清除已保存Key
        </label>
        <div class="form-actions">
          <button class="secondary-button" type="button" :disabled="isSavingPlatform" @click="closePlatformForm">
            取消
          </button>
          <button class="primary-button" type="submit" :disabled="isSavingPlatform">
            {{ isSavingPlatform ? '保存中' : '保存' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
