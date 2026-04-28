"""
Desktop God Agent - 感知系统
100ms高频屏幕捕获 + UIA结构化元素 + OCR文字识别 + Delta变化检测

感知层级（第十卷）：
  高频 100ms  → 状态监听、窗口变化、下载进度（纯代码，不用模型）
  中频 500ms  → 卡住判断、页面加载判断、UI状态分析（Ollama本地）
  按需低频    → 复杂视觉理解、截图分析（Gemini云端）

渐进升级策略（问题前置.md记录的混合模式6级）：
  L1 desktop   → 纯桌面信息（进程/窗口/文件）
  L2 get_state → 结构化UIA文本
  L3 full      → 完整DOM/UIA树
  L4 cdp       → 浏览器CDP协议
  L5 gemini find → Gemini定位元素
  L6 gemini screenshot → Gemini全屏理解
"""
