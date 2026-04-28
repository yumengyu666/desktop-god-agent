# Desktop God Agent (电脑全能管家)

> **像人一样操作电脑 · 像神一样理解电脑**

下一代桌面 AI 自治代理系统——认知无限 + 执行受限。

## 🎯 核心设计

```
认知权限 ≈ 系统级（可读进程/文件/DOM/网络/记忆）
执行权限 = 用户级（仅鼠标键盘）
```

### 标志性创新

| 特性 | 描述 |
|------|------|
| **双鼠标系统** | 真实白色光标(用户) + 淡蓝色70%透明光标(AI)，AI操作全程可见 |
| **三层记忆** | 临时→短期→长期，自动晋升机制，经验越用越强 |
| **圈养模型** | 同一模型底座多角色人格（浏览器工/文件工/Office工），岗前热身训练 |
| **5-Agent编排** | Commander→Planner→Executor→Verifier→Recovery 流水线 |
| **急停安全** | Ctrl+Alt+Shift+Q 全局热键紧急停止，审计日志完整追踪 |

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────┐
│              用户指令入口                     │
│         (CLI / 交互模式 / API)               │
├──────────┬──────────┬────────────────────────┤
│          │          │                        │
│  🧠 模型网关      │   👁️ 感知系统           │
│ ├ Ollama 本地     │ ├ mss 屏幕截图(100ms)  │
│ ├ DeepSeek Flash  │ ├ UIA 元素树            │
│ ├ DeepSeek Pro    │ └ PaddleOCR 文字识别    │
│ └ Google Gemini   │                        │
│                  │   🖱️ 执行引擎            │
│  🧠 Agent团队     │ ├ Win32 鼠标控制(SHM)   │
│ ├ Commander 总控  │ ├ Win32 键盘输入        │
│ ├ Planner 规划    │ └ 动作验证+回滚          │
│ ├ Executor 执行   │                        │
│ ├ Verifier 验证   │   🖼️ 双鼠标渲染          │
│ └ Recovery 恢复   │ └ PyQt5 透明窗口        │
│                  │                        │
│  🌍 世界模型       │   🔒 安全控制            │
│ ├ 即时状态快照     │ ├ 急停热键              │
│ ├ 任务上下文       │ ├ 风险评估              │
│ └ Delta变化检测    │ └ 审计日志              │
│                  │                        │
│  📚 三层记忆       │                        │
│ ├ 临时(Session)   │                        │
│ ├ 短期(Working)   │                        │
│ └ 长期(Knowledge) │                        │
└──────────────────┴─────────────────────────┘
```

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置API密钥（复制模板并填入真实密钥）
cp .env.example .env
# 编辑 .env 填入 DeepSeek / Google AI / GitHub 密钥

# 3. 启动交互模式
python main.py

# 4. 单指令执行
python main.py "打开Chrome并访问百度"

# 5. 调试模式
python main.py --log-level DEBUG

# 急停: Ctrl+Alt+Shift+Q
```

## 📂 项目结构

```
D:\computeruser/
├── main.py                    # 主入口
├── .env                       # API密钥配置 (不入Git!)
├── .env.example               # 配置模板
├── requirements.txt           # Python依赖
├── .gitignore                 # Git忽略规则
│
├── src/                       # 核心源码
│   ├── config/                # 配置管理
│   │   └── __init__.py        # Settings单例(.env加载)
│   ├── gateway/               # 模型网关
│   │   ├── __init__.py
│   │   └── model_gateway.py   # 多模型自动路由
│   ├── perception/            # 感知系统
│   │   ├── __init__.py
│   │   ├── screenshot.py      # 高速屏幕截图(mss)
│   │   ├── uia_scanner.py     # UIA元素扫描
│   │   └── ocr_engine.py      # OCR文字识别(PaddleOCR)
│   ├── execution/             # 执行引擎
│   │   ├── __init__.py
│   │   └── executor.py        # 鼠标键盘Win32控制
│   ├── dual_mouse/            # 双鼠标系统
│   │   ├── __init__.py
│   │   └── ai_cursor.py       # 透明蓝光标(PyQt5)
│   ├── world_model/           # 世界模型
│   │   ├── __init__.py
│   │   └── world_model.py     # 状态快照+Delta检测
│   ├── memory/                # 记忆系统
│   │   ├── __init__.py
│   │   └── memory_system.py   # 三层记忆+晋升
│   ├── agent/                 # 多Agent系统
│   │   ├── __init__.py
│   │   └── agents.py          # 5角色Agent编排
│   └── security/              # 安全控制
│       ├── __init__.py
│       └── safety.py          # 急停+审计+权限
│
├── 第一卷.md ~ 第十二卷.md    # 设计白皮书(~10万字)
├── 大体目标.md                # 项目定位文档
└── 问题前置.md                # 问题引入
```

## 🤖 模型分工

| 模型 | 用途 | 延迟 | 成本 |
|------|------|------|------|
| **Ollama** `deepseek-r1:8b` | 高频判断、状态分类、记忆检索 | ~42 tok/s本地 | 免费 |
| **DeepSeek Flash** | 轻量决策、文本理解、快速推理 | <1s | 低 |
| **DeepSeek V4 Pro** | 复杂规划、长链推理、异常恢复 | 2-3s | 中 |
| **Google Gemini** | 图片识别、视觉理解、OCR增强 | 1-2s | 中 |

> 自动路由：有图片走Gemini，简单判断走Ollama，复杂规划走Pro，其余走Flash

## 🔐 安全设计

- ✅ **执行受限**: 只能鼠标键盘，不做系统注入
- ✅ **全局急停**: Ctrl+Alt+Shift+Q 随时可中断
- ✅ **风险评分**: 每个操作自动评估风险等级
- ✅ **审计日志**: 所有操作完整记录(JSONL格式)
- ✅ **权限白名单**: 受保护应用(注册表/CMD等)需额外确认
- ✅ **双鼠标可见**: AI每一步操作用户都能看到

## 📊 开发进度

- [x] Phase 1: 核心骨架（项目结构+配置+网关+感知+执行+双鼠标）
- [x] Phase 2: 智能层（世界模型+三层记忆+Agent编排+安全控制）
- [x] Phase 3: 主循环（交互模式+单指令+状态查看+帮助）
- [ ] Phase 4: 产品化（悬浮GUI面板+联网学习+更多专家模型）
- [ ] Phase 5: 测试与优化（端到端集成测试+性能调优）

## 📝 设计文档

12卷白皮书位于项目根目录：

| 卷号 | 内容 | 字数约 |
|------|------|--------|
| 第01卷 | 总体架构与核心哲学 | 1万 |
| 第02卷 | 双鼠标系统设计 | 1万 |
| 第03卷 | 认知无限执行受限 | 1万 |
| 第04卷 | 世界模型（数字孪生） | 1万 |
| 第05卷 | 三层记忆系统 | 1万 |
| 第06卷 | 本地模型圈养体系 | 1万 |
| 第07卷 | 联网学习系统 | 1万 |
| 第08卷 | 任务规划与多Agent | 1万 |
| 第09卷 | 执行引擎 | 1万 |
| 第10卷 | 感知系统 | 1万 |
| 第11卷 | 安全控制系统 | 1万 |
| 第12卷 | 产品交互系统 | 1万 |

## License

MIT License — 私有仓库，仅供学习研究使用
