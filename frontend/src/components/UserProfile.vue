<script setup>
import { computed, onMounted, ref } from 'vue'
import { Lock, Pencil, Trash2, Unlock } from 'lucide-vue-next'

const categoryLabels = { basic: '基础信息', preference: '偏好', interest: '兴趣', habit: '习惯', other: '其他' }
const profile = ref({ entries: [], autoExtractionEnabled: true, extractionInterval: 5 })
const isLoading = ref(true)
const isWorking = ref(false)
const notice = ref('')
const noticeType = ref('success')
const showForm = ref(false)
const editingId = ref('')
const formCategory = ref('basic')
const formContent = ref('')
const formSource = ref('用户手动添加')
const formConfidence = ref(1)
const formLocked = ref(false)
const groupedEntries = computed(() => Object.keys(categoryLabels).map((category) => ({ category, label: categoryLabels[category], entries: profile.value.entries.filter((entry) => entry.category === category) })))

async function requestApi(url, options = {}) {
  let response
  try { response = await fetch(url, options) } catch (error) { throw new Error('无法连接后端，请确认Python服务已经启动') }
  let data = {}
  try { data = await response.json() } catch (error) { data = {} }
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试')
  return data
}
function showNotice(message, type = 'success') { notice.value = message; noticeType.value = type }
async function loadProfile() { isLoading.value = true; try { profile.value = await requestApi('/api/user-profile') } catch (error) { showNotice(error.message, 'error') } finally { isLoading.value = false } }
async function saveSettings() {
  isWorking.value = true
  try {
    profile.value = await requestApi('/api/user-profile/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ autoExtractionEnabled: profile.value.autoExtractionEnabled, extractionInterval: Number(profile.value.extractionInterval) }) })
    showNotice('自动提取设置已保存')
  } catch (error) { showNotice(error.message, 'error'); await loadProfile() } finally { isWorking.value = false }
}
async function extractNow() {
  isWorking.value = true
  try {
    const data = await requestApi('/api/user-profile/extract', { method: 'POST' })
    await loadProfile()
    showNotice(data.message)
  } catch (error) { showNotice(error.message, 'error') } finally { isWorking.value = false }
}
function openAddForm(category = 'basic') { editingId.value = ''; formCategory.value = category; formContent.value = ''; formSource.value = '用户手动添加'; formConfidence.value = 1; formLocked.value = false; showForm.value = true }
function openEditForm(entry) { editingId.value = entry.id; formCategory.value = entry.category; formContent.value = entry.content; formSource.value = entry.source; formConfidence.value = entry.confidence; formLocked.value = entry.locked; showForm.value = true }
async function saveEntry() {
  if (!formContent.value.trim()) { showNotice('用户信息内容不能为空', 'error'); return }
  isWorking.value = true
  try {
    const body = JSON.stringify({ category: formCategory.value, content: formContent.value.trim(), source: formSource.value.trim() || '用户手动添加', confidence: Number(formConfidence.value), locked: formLocked.value })
    await requestApi(editingId.value ? `/api/user-profile/entries/${editingId.value}` : '/api/user-profile/entries', { method: editingId.value ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body })
    showForm.value = false
    await loadProfile()
    showNotice(editingId.value ? '用户信息已更新' : '用户信息已添加')
  } catch (error) { showNotice(error.message, 'error') } finally { isWorking.value = false }
}
async function toggleLock(entry) {
  isWorking.value = true
  try { await requestApi(`/api/user-profile/entries/${entry.id}/lock`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ locked: !entry.locked }) }); await loadProfile(); showNotice(entry.locked ? '已解锁' : '已锁定') } catch (error) { showNotice(error.message, 'error') } finally { isWorking.value = false }
}
async function deleteEntry(entry) {
  if (!confirm(`确定删除“${entry.content}”吗？`)) return
  isWorking.value = true
  try { await requestApi(`/api/user-profile/entries/${entry.id}`, { method: 'DELETE' }); profile.value.entries = profile.value.entries.filter((item) => item.id !== entry.id); showNotice('用户信息已删除') } catch (error) { showNotice(error.message, 'error') } finally { isWorking.value = false }
}
function formatTime(value) { return value ? new Date(value).toLocaleString() : '' }
onMounted(loadProfile)
</script>

<template>
  <section class="profile-section">
    <header class="profile-header"><div><h2>用户信息</h2><p>系统从自然对话中逐渐了解用户，无需填写固定问卷。</p></div><button class="primary-button" :disabled="isWorking" @click="openAddForm()">手动新增</button></header>
    <div class="profile-settings-card">
      <label><input v-model="profile.autoExtractionEnabled" type="checkbox" :disabled="isWorking" />自动提取</label>
      <label>每<input v-model="profile.extractionInterval" type="number" min="3" max="20" :disabled="isWorking" />轮提取一次</label>
      <button class="secondary-button" :disabled="isWorking" @click="saveSettings">保存设置</button>
      <button class="primary-button" :disabled="isWorking" @click="extractNow">{{ isWorking ? '处理中' : '立即提取' }}</button>
    </div>
    <div v-if="notice" class="notice" :class="noticeType">{{ notice }}</div>
    <div v-if="isLoading" class="state-card">正在加载用户信息……</div>
    <div v-else-if="!profile.entries.length" class="state-card">还没有用户信息，系统会在自然对话中逐渐学习。</div>
    <div v-else class="profile-groups">
      <section v-for="group in groupedEntries" :key="group.category" class="profile-group">
        <div class="profile-group-title"><h3>{{ group.label }}</h3><button class="text-button" @click="openAddForm(group.category)">新增</button></div>
        <div v-if="!group.entries.length" class="profile-empty">暂无信息</div>
        <article v-for="entry in group.entries" :key="entry.id" class="profile-entry" :class="{ locked: entry.locked }">
          <div class="profile-entry-main"><div class="profile-content"><span v-if="entry.locked" class="profile-lock"><Lock />已锁定</span>{{ entry.content }}</div><details><summary>查看来源</summary><p>{{ entry.source }}</p></details><div class="profile-meta">置信度 {{ Math.round(entry.confidence * 100) }}% · 更新于 {{ formatTime(entry.updatedAt) }}</div></div>
          <div class="profile-actions">
            <button class="profile-action-button" :title="entry.locked ? '解锁' : '锁定'" :aria-label="entry.locked ? '解锁用户信息' : '锁定用户信息'" @click="toggleLock(entry)"><Unlock v-if="entry.locked" /><Lock v-else /><span>{{ entry.locked ? '解锁' : '锁定' }}</span></button>
            <button class="profile-action-button" title="编辑" aria-label="编辑用户信息" @click="openEditForm(entry)"><Pencil /><span>编辑</span></button>
            <button class="profile-action-button danger-action" title="删除" aria-label="删除用户信息" @click="deleteEntry(entry)"><Trash2 /><span>删除</span></button>
          </div>
        </article>
      </section>
    </div>
    <div v-if="showForm" class="form-overlay" @click.self="showForm = false"><form class="platform-form" @submit.prevent="saveEntry"><h3>{{ editingId ? '编辑用户信息' : '新增用户信息' }}</h3><label>分类<select v-model="formCategory"><option v-for="(label, key) in categoryLabels" :key="key" :value="key">{{ label }}</option></select></label><label>内容<input v-model="formContent" type="text" /></label><label>来源<input v-model="formSource" type="text" /></label><label>置信度<input v-model="formConfidence" type="number" min="0" max="1" step="0.01" /></label><label class="profile-lock-option"><input v-model="formLocked" type="checkbox" />锁定此信息</label><div class="form-actions"><button class="secondary-button" type="button" @click="showForm = false">取消</button><button class="primary-button" :disabled="isWorking">保存</button></div></form></div>
  </section>
</template>
