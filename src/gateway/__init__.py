"""
Desktop God Agent - 模型网关
统一路由：Ollama本地 / DeepSeek云端(Flash+Pro) / Google Gemini视觉

模型分工策略：
  Ollama (deepseek-r1:8b)     → 高频简单判断、记忆检索、状态分类
  DeepSeek Flash              → 轻量决策、文本理解、快速推理
  DeepSeek V4 Pro             → 复杂规划、长链推理、异常恢复
  Google Gemini               → 图片识别、视觉理解、OCR增强
"""
