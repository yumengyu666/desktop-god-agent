"""
Desktop God Agent - 多Agent系统（第八卷）

Agent角色（参考设计文档）：
  Commander   → 总控，接收用户指令，分配任务
  Planner     → 规划师，拆解复杂任务为DAG步骤
  Executor    → 执行者，调用执行引擎完成具体操作
  Verifier    → 验证者，检查操作结果是否正确
  Recovery    → 恢复者，处理异常和错误恢复

通信协议：
  Agent之间通过消息队列/函数调用通信
  每个消息包含：sender, receiver, type, payload
  支持同步（函数调用）和异步（事件总线）两种模式

圈养模型体系（第六卷）：
  不同任务类型使用不同的system prompt角色人格，
  同一底层模型通过不同prompt实现"多专家"
"""
