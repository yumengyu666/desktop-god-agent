"""
Desktop God Agent - 执行引擎
仿人鼠标键盘控制 + 动作验证 + 回滚机制

设计哲学（第九卷）：
  所有操作通过鼠标键盘完成（像人一样）
  不做系统级注入、不做API直连
  每个动作都有验证和回滚能力
  
动作语言：
  click(x, y)          → 点击坐标
  double_click(x, y)   → 双击
  right_click(x, y)    → 右键
  type(text)           → 键盘输入
  key(key)             → 单按键
  hotkey(k1, k2, ...)  → 组合键
  scroll(delta)        → 滚轮
  drag(start, end)     → 拖拽
"""
