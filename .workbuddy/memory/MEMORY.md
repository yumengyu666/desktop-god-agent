# Desktop God Agent 项目记忆

## 项目概况
- **项目名称**：Desktop God Agent（电脑全能管家）
- **项目位置**：D:\computeruser
- **核心定位**：下一代桌面 AI 自治代理系统 — "像人一样操作电脑，像神一样理解电脑"
- **设计文档**：已完成12卷白皮书（第一卷~第十二卷）+ 大体目标 + 问题前置

## 设计哲学
- **认知无限，执行受限**：AI可读取系统全信息（进程/文件/DOM/网络/记忆），但执行仅限鼠标键盘仿人操作
- **双鼠标系统**：真实用户鼠标(白色) + AI虚拟鼠标(淡蓝色70%透明)，AI操作全程可见
- **三层记忆**：临时记忆→短期记忆→长期记忆，经验晋升机制（成功1次→临时，3次→短期，10次→长期）
- **圈养模式**：同一本地模型底座，多实例不同岗位人格，启动时岗前热身训练10轮

## API密钥（用户已提供）
- **DeepSeek**：sk-602a57de77f24b8ca02145d3a099cb18 / sk-e17fb5d89a7e43e5ada33ed9705ef05d
  - flash用于简单任务，v4-pro用于复杂任务
  - base_url: https://api.deepseek.com
  - 无图片识别功能
- **Google Gemini**：AIzaSyCxf9XUwGkafBzqnOxObMeqkzELUoE-f0g
  - 有图片识别/视觉理解能力（对象检测、分割、OCR等）
  - 模型：gemini-3-flash-preview
- **GitHub PAT**：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 / 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

## 模型分工策略
- DeepSeek flash：简单分类、小决策、文本理解
- DeepSeek v4-pro：复杂推理、长链规划、异常处理
- Gemini：图片识别、视觉理解、OCR、对象检测
- Ollama本地模型：日常高频判断、记忆查询、经验匹配

## 12卷白皮书结构
1. 总体架构 — 项目定义、核心哲学、六大核心能力、双鼠标概念
2. 双鼠标系统 — 透明顶层窗口、贝塞尔曲线移动、人机共存、抢占机制
3. 认知无限执行受限 — 认知层设计（UI/文件/进程/网络/记忆/搜索）、执行白名单/黑名单
4. 世界模型 — 电脑数字孪生、三层状态(即时/任务/长期)、Delta Engine、异常识别
5. 三层记忆 — 临时/短期/长期、晋升机制、向量检索、评分系统
6. 本地模型圈养 — 浏览器工/文件工/Office工/恢复工/搜索工、热身训练
7. 联网学习 — 遇阻→搜索→筛选→提炼→沙盒验证→执行→沉淀
8. 任务规划多Agent — Commander/Planner/Executor/Verifier/Recovery、DAG任务图
9. 执行引擎 — 动作语言、路径规划、仿人操作、验证器、回滚机制
10. 感知系统 — 100ms高频/500ms中频/按需低频、Delta Engine、注意力机制
11. 安全控制 — 分级权限、急停、风险评分、审计日志、沙盒模式
12. 产品交互 — 输入方式、反馈系统、成长感设计、模板系统

## 原有代码参考（问题前置.md中记录）
- 之前已有claudeccs三种模式的实现：Gemini Vision纯AI识图、screen_tool结构化文本、混合模式渐进感知
- 混合模式6级感知升级：desktop→get_state→full→cdp→gemini find→gemini screenshot
- SHM简谐运动鼠标移动、归一化坐标系统

## 开发优先级（文档中确定）
1. 双鼠标系统  2. 执行引擎  3. 世界模型  4. 验证系统  5. 记忆系统  6. 多模型调度  7. 联网学习

## 技术栈方向
- Runtime: Python + Rust
- Windows控制: UIA + pywinauto
- 浏览器: Playwright
- OCR: PaddleOCR
- 视觉: Gemini API
- AI: DeepSeek API (flash/pro) + Ollama本地
- UI: Tauri / Electron悬浮窗
- 状态流: Redis Streams
