# 智能数字人助手

基于 AI 大模型的智能数字人系统，支持自然语言对话、知识库问答、用户画像自动提取、长期记忆和动态数字人形象。

## 功能列表

- 登录注册（多用户，各自独立的聊天记录、知识库、用户信息和 API 配置）
- 自然语言对话（SSE 流式输出，文字逐步显示）
- API 仓库（支持 OpenAI、智谱、豆包、DeepSeek、Anthropic 及自定义平台）
- 本地 Ollama 模型支持
- 三类模型独立配置（对话模型、总结模型、向量模型）
- RAG 知识库（分类管理、TXT 上传、向量索引、语义检索）
- 用户画像自动提取（自然对话中提取用户偏好，支持手动提取、编辑、删除、锁定）
- 长期记忆（自动总结历史对话，向量召回相关记忆）
- 动态数字人球体（idle 待机 / thinking 思考 / speaking 说话，三种动画状态）
- 聊天记录持久化（SQLite 存储，刷新页面自动恢复）
- 清空聊天记录（只清消息，保留知识库、用户信息和长期记忆）
- 消息管理（复制、删除单轮问答、重新生成）
- 停止生成（流式输出中可随时取消）

## 技术栈

- 后端：Python + FastAPI
- 前端：Vue 3 + Vite
- 模型接口：OpenAI 兼容 API
- 知识库：LangChain + Chroma
- 记忆：SQLite + 自动总结 + 向量召回
- 用户画像：自然对话自动提取 + JSON 结构化管理

## 目录结构

```
digital_human/
├── requirements.txt           # Python 依赖
├── backend/
│   ├── main.py                # 程序入口（组合根 + 路由挂载 + 静态资源）
│   ├── config.py              # 全局配置（System Prompt、路径等）
│   ├── routers/
│   │   ├── errors.py          # 统一错误映射
│   │   ├── auth.py            # 登录注册路由
│   │   ├── platforms.py       # API 仓库路由
│   │   ├── knowledge.py       # 知识库路由
│   │   ├── settings.py        # 对话设置路由
│   │   ├── profile.py         # 用户画像路由
│   │   └── conversation.py    # 对话路由（聊天、历史、SSE）
│   ├── modules/
│   │   ├── chat.py            # 对话编排（Prompt 拼接、流式/非流式、消息保存）
│   │   ├── memory.py          # 记忆系统（SQLite 读写、长期记忆、聊天历史）
│   │   └── rag.py             # RAG 知识库（文档切块、Chroma 索引、语义检索）
│   ├── services/
│   │   ├── model_clients.py   # 模型调用（普通请求 + 流式 SSE）
│   │   ├── api_repository.py  # API 仓库管理（平台、Key、模型列表）
│   │   ├── chat_settings.py   # 对话设置管理
│   │   ├── user_profile.py    # 用户画像（提取、存储、编辑、锁定）
│   │   ├── auth.py            # 用户账号与登录会话（SQLite）
│   │   └── workspace.py       # 用户工作区（每个用户一套独立数据目录和服务）
│   ├── tests/
│   │   └── test_auth_flow.py  # 登录注册与多用户隔离自检脚本
│   └── data/                  # 运行时数据（各用户数据在 data/users/<用户id>/ 下）
├── frontend/
│   ├── src/
│   │   ├── App.vue            # 主界面（聊天、球体动画、SSE 解析、状态管理）
│   │   ├── main.js            # Vue 入口
│   │   ├── style.css          # 全局样式和球体动画
│   │   └── components/
│   │       ├── AuthPage.vue            # 登录注册页面
│   │       ├── ChatSettingsDrawer.vue  # 对话设置侧栏（模型选择、知识库、清空聊天）
│   │       ├── ApiRepository.vue      # API 仓库管理界面
│   │       ├── KnowledgeBase.vue      # 知识库管理界面
│   │       ├── UserProfile.vue        # 用户画像管理界面
│   │       └── AdminPanel.vue         # 后台管理面板
│   └── dist/                  # 前端构建产物（已构建，可直接运行）
└── venv/                      # Python 虚拟环境
```

## 环境要求

- Python 3.10+
- Node.js 18+（仅开发时需要，运行时不需要）
- 至少一个 OpenAI 兼容 API（云端或本地 Ollama）

## 安装步骤

### 1. 创建虚拟环境并安装依赖

```bash
cd D:\digital_human
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 前端构建（可选，dist 已包含在项目中）

如需修改前端代码后重新构建：

```bash
cd frontend
npm install
npm run build
cd ..
```

如果不修改前端，直接使用现有 dist 目录即可，不需要安装 Node.js。

### 3. 启动

```bash
cd D:\digital_human
venv\Scripts\activate
cd backend
uvicorn main:app --host 127.0.0.1 --port 5000
```

启动后浏览器访问：http://127.0.0.1:5000

## 首次使用

### 注册并登录

打开页面会先看到登录/注册页。第一次使用点“注册”，填用户名（2-32位）和密码（至少6位），注册成功后自动登录。

- 每个用户有自己独立的聊天记录、长期记忆、用户画像、知识库和 API 配置，互相看不到。
- 右上角显示当前用户名，旁边的按钮可以退出登录。登录状态保留30天。
- 第一个注册的用户会自动接管旧版单用户模式留下的数据（原来的 data/ 目录内容）。

### 配置 API

1. 点击页面右上角齿轮图标，打开对话设置。
2. 点击 API 仓库，选择一个平台（如 OpenAI、智谱、DeepSeek 等）。
3. 填写 API 地址和 Key。
4. 点击拉取模型或手动添加模型。
5. 回到对话设置，选择对话模型。
6. 总结模型和向量模型可选配置，不配置时相关功能自动降级。

### 使用本地 Ollama

1. 确保 Ollama 已启动（默认地址 http://localhost:11434）。
2. 在 API 仓库中选择自定义平台或 OpenAI 平台。
3. API 地址填写：http://localhost:11434/v1
4. Key 填写任意字符串（如 ollama）。
5. 拉取模型列表，选择已下载的模型。

### 知识库

1. 打开对话设置，进入知识库管理。
2. 创建分类（如"公司资料""产品手册"）。
3. 上传 TXT 文件到对应分类。
4. 点击建立索引。
5. 在对话设置中勾选需要启用的知识库分类。
6. 聊天时模型会自动检索相关知识。

需要配置向量模型才能使用知识库索引功能。

### 用户画像

系统会在对话过程中自动提取用户偏好信息（如喜好、习惯、基本信息等）。

- 自动提取：累计一定轮数后自动触发。
- 手动提取：在用户信息页面点击"立即提取"。
- 支持编辑、删除和锁定（锁定后不会被自动覆盖）。

需要配置总结模型才能使用画像提取功能。

## 对话功能说明

### 流式输出

首次发送消息使用 SSE 流式输出，文字逐步显示。左侧球体会依次经历：

- 待机（缓慢漂浮）→ 思考（球体变形，小球分散）→ 说话（节奏性挤压回弹）→ 待机

### 重新生成

点击 AI 回复下方的重新生成按钮，会删除当前轮次并重新请求模型。重新生成期间球体显示说话动画。

### 停止生成

流式输出过程中，发送按钮会变为停止按钮，点击可取消当前生成。未完成的回复不会被保存。

### 清空聊天记录

在对话设置底部的"危险操作"区域，可清空全部聊天消息。清空范围：

- 会删除：全部聊天消息
- 不会删除：用户画像、长期记忆、知识库、API 配置和对话设置

## 数据存储位置

所有运行时数据保存在 data/ 目录下：

- 账号和登录会话：users.db（所有用户共用）
- 每个用户的数据：data/users/<用户id>/ 下各自一份
  - 聊天记录和长期记忆：memories.db
  - 用户画像：user_profile.json
  - 知识库文件：knowledge_base/ 按分类存放的 TXT 文件
  - 知识库索引：chroma_db/ 向量数据库
  - API 配置：api_repository.json
  - 对话设置：chat_settings.json

data/ 目录可以用环境变量 DIGITAL_HUMAN_DATA_DIR 指向别处（多实例部署或跑测试时用）。

### 自检脚本

在 backend 目录执行，验证注册登录、登录态校验和多用户数据隔离：

```bash
python tests/test_auth_flow.py
```

## 常见问题

### 注册后看不到以前的聊天记录

旧版单用户数据只会迁移给第一个注册的用户。如果不是，手动把 data/ 下的 memories.db、chroma_db、knowledge_base、user_profile.json、api_repository.json、chat_settings.json 移到 data/users/<用户id>/ 即可。

### 启动后页面空白

确认 frontend/dist 目录存在且包含 index.html。如果缺失，需要执行前端构建。

### 模型回复客服腔

在对话设置中修改 System Prompt，明确要求自然简洁回复，避免客服式套话。

### 本地 Ollama 连接失败

确认 Ollama 已启动，API 地址为 http://localhost:11434/v1，Key 填写任意非空字符串。

### 知识库检索不到内容

确认已上传 TXT 文件、已建立索引、已在对话设置中勾选对应分类、已配置向量模型。

### 用户画像提取显示"新增 0 条"

可能是模型未发现可保存的稳定信息，或所有信息已存在。页面会显示具体原因（空结果、重复、过滤等）。

### 清空聊天后模型仍提到旧内容

长期记忆不会被清空聊天删除。如果长期记忆中保存了旧对话的总结，模型仍可能引用。