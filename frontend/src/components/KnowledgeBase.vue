<script setup>
import { computed, onMounted, ref } from 'vue'

const categories = ref([])
const selectedId = ref('')
const newCategory = ref('')
const uploadFile = ref(null)
const isLoading = ref(true)
const isWorking = ref(false)
const notice = ref('')
const noticeType = ref('success')

const selectedCategory = computed(() => categories.value.find((item) => item.id === selectedId.value) || null)

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

function showNotice(message, type = 'success') {
  notice.value = message
  noticeType.value = type
}

function validateCategoryName(name) {
  if (!name || name === '.' || name === '..') {
    return '分类名不能为空'
  }
  if (name.length > 50 || !/^[A-Za-z0-9_\- \u4e00-\u9fff]+$/.test(name)) {
    return '支持中文、英文、数字、空格、下划线和短横线，请勿使用路径或特殊符号'
  }
  return ''
}

async function loadCategories(preferredId = '') {
  isLoading.value = true
  try {
    const data = await requestApi('/api/knowledge-bases')
    categories.value = Array.isArray(data.categories) ? data.categories : []
    const nextId = preferredId || selectedId.value
    selectedId.value = categories.value.some((item) => item.id === nextId) ? nextId : categories.value[0]?.id || ''
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isLoading.value = false
  }
}

async function createCategory() {
  const name = newCategory.value.trim()
  const validationError = validateCategoryName(name)
  if (validationError) {
    showNotice(validationError, 'error')
    return
  }
  if (isWorking.value) return
  isWorking.value = true
  try {
    const data = await requestApi('/api/knowledge-bases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    newCategory.value = ''
    await loadCategories(name)
    showNotice(data.message)
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isWorking.value = false
  }
}

function chooseFile(event) {
  const file = event.target.files[0] || null
  if (!file) {
    uploadFile.value = null
    showNotice('未选择文件', 'error')
    return
  }
  if (!file.name.toLowerCase().endsWith('.txt')) {
    uploadFile.value = null
    event.target.value = ''
    showNotice('仅允许TXT文件', 'error')
    return
  }
  uploadFile.value = file
}

async function uploadTxt(event) {
  if (!uploadFile.value) {
    showNotice('未选择文件', 'error')
    return
  }
  if (!selectedCategory.value || isWorking.value) return
  isWorking.value = true
  const formData = new FormData()
  formData.append('file', uploadFile.value)
  try {
    const data = await requestApi(`/api/knowledge-bases/${encodeURIComponent(selectedId.value)}/files`, {
      method: 'POST',
      body: formData,
    })
    uploadFile.value = null
    event.target.reset()
    await loadCategories(selectedId.value)
    showNotice(data.message)
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isWorking.value = false
  }
}

async function rebuildIndex() {
  if (!selectedCategory.value || isWorking.value) return
  isWorking.value = true
  try {
    const data = await requestApi(`/api/knowledge-bases/${encodeURIComponent(selectedId.value)}/rebuild`, { method: 'POST' })
    await loadCategories(selectedId.value)
    showNotice(data.message)
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isWorking.value = false
  }
}

async function deleteFile(filename) {
  if (!confirm(`确定删除“${filename}”吗？`)) return
  isWorking.value = true
  try {
    const data = await requestApi(`/api/knowledge-bases/${encodeURIComponent(selectedId.value)}/files/${encodeURIComponent(filename)}`, { method: 'DELETE' })
    await loadCategories(selectedId.value)
    showNotice(data.message)
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isWorking.value = false
  }
}

async function deleteCategory() {
  const category = selectedCategory.value
  if (!category || !confirm(`确定删除知识库分类“${category.name}”及其中全部TXT文件吗？`)) return
  isWorking.value = true
  try {
    const data = await requestApi(`/api/knowledge-bases/${encodeURIComponent(category.id)}`, { method: 'DELETE' })
    selectedId.value = ''
    await loadCategories()
    showNotice(data.message)
  } catch (error) {
    showNotice(error.message, 'error')
  } finally {
    isWorking.value = false
  }
}

onMounted(loadCategories)
</script>

<template>
  <section class="knowledge-section">
    <header class="knowledge-header">
      <h2>知识库</h2>
      <p>管理TXT资料、分类与向量索引</p>
    </header>

    <form class="category-create-panel" @submit.prevent="createCategory">
      <div class="category-create-fields">
        <input v-model="newCategory" maxlength="50" placeholder="输入分类名称" />
        <button class="primary-button" :disabled="isWorking || !newCategory.trim()">新建分类</button>
      </div>
      <p>支持中文、英文、数字、空格、下划线和短横线，请勿使用路径或特殊符号。</p>
    </form>

    <div v-if="notice" class="notice" :class="noticeType">{{ notice }}</div>
    <div v-if="isLoading" class="state-card">正在加载知识库……</div>

    <div v-else class="knowledge-layout">
      <aside class="knowledge-categories">
        <h3>分类列表</h3>
        <button
          v-for="category in categories"
          :key="category.id"
          class="knowledge-category-item"
          :class="{ selected: category.id === selectedId }"
          type="button"
          @click="selectedId = category.id"
        >
          <strong :title="category.name">{{ category.name }}</strong>
          <span>{{ category.files.length }} 个TXT</span>
          <span class="status-badge" :class="category.indexed ? 'indexed' : 'not-indexed'">
            {{ category.indexed ? '已构建' : '未构建' }}
          </span>
        </button>
        <div v-if="!categories.length" class="knowledge-empty">暂无知识库分类</div>
      </aside>

      <section v-if="selectedCategory" class="knowledge-detail">
        <header class="knowledge-detail-header">
          <div class="knowledge-title-block">
            <h3 :title="selectedCategory.name">{{ selectedCategory.name }}</h3>
            <span class="status-badge" :class="isWorking ? 'processing' : selectedCategory.indexed ? 'indexed' : 'not-indexed'">
              {{ isWorking ? '处理中' : selectedCategory.indexed ? '已构建索引' : '未构建索引' }}
            </span>
          </div>
          <p>分类ID：{{ selectedCategory.id }}</p>
        </header>

        <div class="knowledge-toolbar">
          <form class="upload-form" @submit.prevent="uploadTxt">
            <input type="file" accept=".txt,text/plain" :disabled="isWorking" @change="chooseFile" />
            <button class="primary-button" :disabled="isWorking || !uploadFile">上传TXT</button>
          </form>
          <button class="secondary-button" :disabled="isWorking || !selectedCategory.files.length" @click="rebuildIndex">
            {{ isWorking ? '处理中' : '构建/重建索引' }}
          </button>
        </div>

        <div class="knowledge-files">
          <div v-for="filename in selectedCategory.files" :key="filename" class="knowledge-file-item">
            <span :title="filename">{{ filename }}</span>
            <button class="text-button danger-text" :disabled="isWorking" @click="deleteFile(filename)">删除</button>
          </div>
          <div v-if="!selectedCategory.files.length" class="knowledge-empty files-empty">
            暂无TXT文件，请先上传资料。
          </div>
        </div>

        <footer class="knowledge-danger-zone">
          <div><strong>删除分类</strong><p>将删除该分类中的TXT文件和对应索引。</p></div>
          <button class="danger-button" :disabled="isWorking" @click="deleteCategory">删除分类</button>
        </footer>
      </section>
      <div v-else class="state-card knowledge-no-selection">请新建或选择知识库分类</div>
    </div>
  </section>
</template>
