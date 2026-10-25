// 普通 JSON 请求：网络失败和 HTTP 错误统一转成可直接展示的 Error。
// 不设置 credentials，保持 fetch 默认的同源 Cookie 行为；调用参数原样透传。
// 成功但响应体不是 JSON 时仍返回空对象（已知问题，后续单独修复）。
export async function requestJson(url, options = {}) {
  let response
  try { response = await fetch(url, options) } catch (error) { throw new Error('无法连接后端，请确认Python服务已经启动') }

  let data = {}
  try { data = await response.json() } catch (error) { data = {} }

  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试')
  return data
}
