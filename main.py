"""
Desktop God Agent v0.2 — 主入口程序

架构（12卷全部实现）：
  模型层：DeepSeek Flash/Pro + Gemini 2.5 Flash (视觉)
  感知层：mss截图 + UIA元素树 + PaddleOCR
  执行层：Win32鼠标键盘(SHM贝塞尔)
  展示层：双鼠标(淡蓝70%) + 悬浮面板
  认知层：世界模型 + 三层记忆 + 圈养工种 + 联网学习
  控制层：安全急停 + 审计日志

启动方式：
  python main.py                    # 交互模式
  python main.py "打开Chrome"       # 单指令模式
  python main.py --headless         # 无GUI模式
"""

import sys
import os
import time
import asyncio
import logging
import argparse
from pathlib import Path

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


def setup_logging(level: str = "INFO") -> None:
    """使用统一日志系统"""
    from src.config.settings import settings
    from src.utils.logger import setup_logging as _setup
    _setup(
        level=level,
        log_dir=str(settings.LOG_DIR),
        console=True,
        file_log=True,
    )


class DesktopGodAgent:
    """
    Desktop God Agent — 总控制器
    
    整合12卷设计文档中的所有子系统，
    提供统一的用户接口和任务执行入口。
    
    v0.2 更新：
    - 去掉Ollama，全面使用 DeepSeek V4 Flash/Pro + Gemini 2.5 Flash
    - 新增圈养体系(5工种) + 联网学习 + 产品交互系统
    - 工具层统一异常/日志/性能监控
    """

    def __init__(self):
        self._log = logging.getLogger("GodAgent")
        
        # ---- 核心子系统 ----
        self._gateway = None           # 模型网关
        self._screencap = None         # 屏幕截图
        self._uia_scanner = None       # UIA扫描
        self._ocr = None               # OCR引擎
        self._executor = None          # 执行引擎
        self._dual_mouse = None        # 双鼠标
        self._world_model = None       # 世界模型
        self._memory = None            # 三层记忆
        
        # ---- v0.2 新增子系统 ----
        self._ranch = None             # 圈养体系总控
        self._learning = None          # 联网学习
        self._feedback_mgr = None      # 反馈管理器
        self._confirm_center = None    # 确认中心
        self._result_cards = None      # 结果卡片
        self._templates = None         # 模板管理
        self._history = None           # 任务历史
        self._command_input = None     # 命令解析
        self._overlay_panel = None     # 悬浮面板
        self._safety = None            # 安全控制
        self._orchestrator = None      # Agent编排器
        
        self._running = False
        self._init_count = 0
        self._total_subsystems = 15

    def initialize(self) -> bool:
        """初始化所有子系统"""
        from src.config.settings import settings
        
        self._log.info("=" * 60)
        self._log.info("🚀 Desktop God Agent v0.2 初始化中...")
        self._log.info("=" * 60)

        missing = settings.validate()
        if missing:
            self._log.warning(f"⚠ 缺少配置项: {missing}")
        
        settings.ensure_dirs()

        # === 1. 模型网关 (Flash + Pro + Gemini Vision) ===
        try:
            from src.gateway.model_gateway import get_gateway
            self._gateway = get_gateway()
            hc = self._gateway.health_check()
            models_ok = sum(1 for m in hc.values() if m.get("ok"))
            self._log.info(f"[✓] 模型网关 ({models_ok}/3 后端就绪)")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 模型网关: {e}")

        # === 2. 屏幕截图 ===
        try:
            from src.perception.screenshot import get_screencap
            self._screencap = get_screencap()
            w, h = self._screencap.screen_size
            self._log.info(f"[✓] 屏幕截图 ({w}x{h})")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 屏幕截图: {e}")

        # === 3. UIA扫描器 ===
        try:
            from src.perception.uia_scanner import UIAScanner
            self._uia_scanner = UIAScanner()
            self._log.info("[✓] UIA扫描器")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] UIA扫描器: {e}")

        # === 4. OCR引擎 ===
        try:
            from src.perception.ocr_engine import get_ocr
            self._ocr = get_ocr()
            self._log.info("[✓] OCR引擎")
            self._init_count += 1
        except Exception as e:
            self._log.warning(f"[△] OCR引擎: {e} (可选)")

        # === 5. 执行引擎 ===
        try:
            from src.execution.executor import get_executor
            self._executor = get_executor()
            self._log.info("[✓] 执行引擎 (SHM贝塞尔)")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 执行引擎: {e}")

        # === 6. 双鼠标系统 ===
        try:
            from src.dual_mouse.ai_cursor import DualMouseSystem
            self._dual_mouse = DualMouseSystem()
            if self._dual_mouse.start():
                self._log.info("[✓] 双鼠标系统 (#409CFF 70%透明)")
                self._init_count += 1
            else:
                self._dual_mouse = None
                self._log.warning("[△] 双鼠标: 启动失败(可选)")
        except Exception as e:
            self._log.warning(f"[△] 双鼠标: {e} (可选)")
            self._dual_mouse = None

        # === 7. 世界模型 ===
        try:
            from src.world_model.world_model import WorldModel
            self._world_model = WorldModel()
            self._log.info("[✓] 世界模型 (三层状态+Delta)")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 世界模型: {e}")

        # === 8. 三层记忆系统 ===
        try:
            from src.memory.memory_system import MemorySystem
            self._memory = MemorySystem(db_path=settings.MEMORY_DB_PATH)
            stats = self._memory.get_stats()
            self._log.info(f"[✓] 三层记忆 ({stats['total']}条)")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 记忆系统: {e}")

        # === 9. 圈养体系 (v0.2新增) ===
        if self._gateway:
            try:
                from src.model_ranch.controller import RanchController
                self._ranch = RanchController(gateway=self._gateway)
                asyncio.get_event_loop().run_until_complete(self._ranch.initialize())
                self._log.info("[✓] 圈养体系 (5工种已热身)")
                self._init_count += 1
            except Exception as e:
                self._log.error(f"[✗] 圈养体系: {e}")

        # === 10. 联网学习 (v0.2新增) ===
        if self._gateway:
            try:
                from src.learning.learning_system import LearningSystem
                self._learning = LearningSystem(gateway=self._gateway, memory=self._memory)
                self._log.info("[✓] 联网学习系统")
                self._init_count += 1
            except Exception as e:
                self._log.error(f"[✗] 联网学习: {e}")

        # === 11-14. 产品交互系统 (v0.2新增) ===
        try:
            from src.product_ui.task_feedback import FeedbackManager
            from src.product_ui.confirmation_center import ConfirmationCenter
            from src.product_ui.result_cards import ResultCards
            from src.product_ui.templates import TemplateManager
            from src.product_ui.task_history import TaskHistoryCenter
            from src.product_ui.command_input import CommandInput
            from src.product_ui.overlay_panel import OverlayPanel
            
            self._feedback_mgr = FeedbackManager()
            self._confirm_center = ConfirmationCenter()
            self._result_cards = ResultCards()
            self._templates = TemplateManager()
            self._history = TaskHistoryCenter()
            self._command_input = CommandInput()
            self._overlay_panel = OverlayPanel()
            
            self._log.info("[✓] 产品交互系统 (命令/反馈/确认/模板/历史)")
            self._init_count += 1
        except Exception as e:
            self._log.warning(f"[△] 产品交互系统部分加载失败: {e}")

        # === 15. 安全控制 ===
        try:
            from src.security.safety import SafetySystem
            self._safety = SafetySystem(audit_dir=settings.AUDIT_LOG_DIR)
            self._safety.start_stop_listener(settings.EMERGENCY_STOP_KEY)
            self._log.info(f"[✓] 安全控制 (急停:{settings.EMERGENCY_STOP_KEY})")
            self._init_count += 1
        except Exception as e:
            self._log.error(f"[✗] 安全控制: {e}")

        # === Agent编排器（依赖上面核心模块） ===
        if self._gateway and self._executor and self._ranch:
            try:
                from src.agent.agents import get_orchestrator
                self._orchestrator = get_orchestrator()
                self._orchestrator.initialize(
                    model_gateway=self._gateway,
                    executor=self._executor,
                    ranch_controller=self._ranch,
                    learning_system=self._learning,
                    memory_system=self._memory,
                )
                self._log.info("[✓] Agent编排器")
            except Exception as e:
                self._log.error(f"[✗] Agent编排器: {e}")

        # === 启动后台监控 ===
        if self._world_model:
            self._world_model.start_monitoring(interval_sec=2.0)

        # === 打印启动摘要 ===
        ready_rate = self._init_count / self._total_subsystems * 100
        self._log.info("=" * 60)
        self._log.info(
            f"✅ 初始化完成: {self._init_count}/{self._total_subsystems} 子系统 "
            f"({ready_rate:.0f}% 就绪)"
        )
        self._log.info(f"   模型: DeepSeek-V4-Flash/Pro + Gemini-2.5-Flash(Vision)")
        self._log.info(f"   工种: 浏览器/文件/Office/恢复/搜索 (圈养体系)")
        self._log.info("=" * 60)

        return ready_rate >= 50  # 超过一半就算可用

    def run(self, instruction: str = "") -> dict:
        """执行用户指令或进入交互模式"""
        if not self._running:
            self.initialize()
            self._running = True

        if instruction:
            return self._execute_single(instruction)
        else:
            return self._interactive_loop()

    def _execute_single(self, instruction: str) -> dict:
        """执行单条指令（完整流程）"""
        self._log.info(f"\n{'─'*50}")
        self._log.info(f">>> {instruction}")
        self._log.info(f"{'─'*50}\n")

        start = time.time()
        task_id = f"task_{int(time.time() % 100000)}"

        try:
            # Step 1: 命令解析
            cmd = self._command_input.parse(instruction)

            # Step 2: 创建反馈跟踪
            fb = self._feedback_mgr.create_task(
                task_id=task_id,
                description=cmd.target or instruction,
            )
            self._feedback_mgr.push(task_id, "开始分析指令...", "info")

            # Step 3: 收集上下文
            context = self._gather_context()

            # Step 4: 通过圈养体系或Agent编排执行
            if self._ranch and cmd.command_type in ("natural",):
                result = asyncio.get_event_loop().run_until_complete(
                    self._ranch.dispatch(instruction, context)
                )
            elif self._orchestrator:
                result = asyncio.get_event_loop().run_until_complete(
                    self._orchestrator.run_task(instruction)
                )
            elif self._gateway:
                # 最简降级：直接问模型
                resp = self._gateway.chat(user_message=instruction, tier="flash")
                result = {
                    "status": "completed",
                    "response": resp.content,
                    "model": resp.model_name,
                    "latency_ms": resp.latency_ms,
                }
            else:
                result = {"status": "error", "error": "No backend available"}

            elapsed = (time.time() - start) * 1000
            result["elapsed_ms"] = round(elapsed, 0)

            # Step 5: 记录结果
            status_icon = "🟢" if result.get("status") == "done" or result.get("status") == "completed" else "🟡"
            self._log.info(f"\n{status_icon} 完成 | {elapsed:.0f}ms")

            # Step 6: 反馈 & 结果卡片
            self._feedback_mgr.push(task_id, "任务完成", "success",
                                     progress=100, confidence=0.9)
            self._feedback_mgr.complete(task_id, success=True)

            if self._result_cards:
                card = self._result_cards.create(
                    title=instruction[:50],
                    status="success" if "error" not in result else "failed",
                    summary=result.get("response", str(result))[:200],
                    time_spent_s=elapsed / 1000,
                )

            # Step 7: 写入历史
            if self._history:
                self._history.record(
                    instruction=instruction,
                    status=result.get("status", "unknown"),
                    started_at=start,
                    completed_at=time.time(),
                    worker=result.get("_worker_used", ""),
                    estimated_time_saved=elapsed / 1000 * 3,  # 估算节省3倍时间
                )

            return result

        except KeyboardInterrupt:
            self._log.warning("\n[!] 用户中断操作")
            self._feedback_mgr.complete(task_id, success=False)
            return {"status": "interrupted"}
        except Exception as e:
            self._log.error(f"[✗] 执行错误: {e}", exc_info=True)
            self._feedback_mgr.complete(task_id, success=False)
            return {"status": "error", "error": str(e)}

    def _gather_context(self) -> dict:
        """收集当前上下文（屏幕、前台应用等）"""
        ctx = {}
        try:
            if self._screencap:
                img = self._screencap.capture()
                ctx["has_screenshot"] = True
            if self._world_model:
                ctx["foreground_app"] = self._world_model.get_foreground_app()
                ctx["processes"] = [p[:30] for p in self._world_model.get_running_processes()[:10]]
        except Exception:
            pass
        return ctx

    def _interactive_loop(self) -> dict:
        """交互式命令循环"""
        self._log.info("\n" + "╔" + "═"*58 + "╗")
        self._log.info("║" + "  Desktop God Agent v0.2 交互模式".center(56) + " ║")
        self._log.info("╠" + "═"*58 + "╣")
        self._log.info("║  输入自然语言 | Ctrl+C 或 exit 退出".center(54) + "║")
        self._log.info("╚" + "═"*58 + "╝\n")

        while self._running:
            try:
                user_input = input("🤖 GodAgent > ").strip()
                
                if not user_input:
                    continue
                
                lower = user_input.lower()
                
                if lower in ('exit', 'quit', 'q', '退出'):
                    break
                
                if lower == 'status':
                    self._print_status()
                    continue
                
                if lower.startswith('mem'):
                    self._print_memory(user_input)
                    continue
                
                if lower == 'help':
                    self._print_help()
                    continue
                
                if lower == '模板' or lower == '/模板':
                    self._print_templates()
                    continue
                
                if lower == '历史':
                    self._print_history()
                    continue

                result = self._execute_single(user_input)
                
                if 'response' in result:
                    print(f"\n📝 {result['response']}\n")

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n(再按一次Ctrl+C强制退出)")

        self.shutdown()
        return {"status": "exited"}

    # ---- 显示方法 ----

    def _print_status(self):
        """打印系统状态面板"""
        from src.config.settings import settings
        mem_stats = self._memory.get_stats() if self._memory else {}
        ranch_stats = self._ranch.get_status() if self._ranch else {}
        
        print(f"""
┌──────────────────────────────────────────────────┐
│  Desktop God Agent v0.2 — 系统状态               │
├──────────────────────────────────────────────────┤
│  模型网关: {'● 就绪' if self._gateway else '○ 未连接'}                              │
│  屏幕感知: {'● 就绪' if self._screencap else '○ 未连接'} ({self._screencap.screen_size if self._screencap else '?'})                   │
│  UIA扫描:  {'● 就绪' if self._uia_scanner else '○ 未连接'}                              │
│  OCR识别:  {'● 就绪' if self._ocr else '○ 未连接'}                              │
│  执行引擎: {'● 就绪' if self._executor else '○ 未连接'}                              │
│  双鼠标:   {'● 运行中' if self._dual_mouse else '○ 未启动'}                            │
│  世界模型: {'● 监控中' if self._world_model else '○ 待机'}                             │
│  三层记忆: {'● 就绪' if self._memory else '○ 未连接'} ({mem_stats.get('total', '?')}条)                      │
│  圈养体系: {'● 5工种就绪' if self._ranch else '○ 未连接'}                          │
│  学习系统: {'● 就绪' if self._learning else '○ 未连接'}                              │
│  安全控制: {'● 急停激活' if self._safety else '○ 未激活'} ({settings.EMERGENCY_STOP_KEY})              │
├──────────────────────────────────────────────────┤
│  急停热键: {settings.EMERGENCY_STOP_KEY:<36} │
│  今日任务: {self._history.get_today().__len__() if self._history else 0} 个                               │
│  已有模板: {self._templates.count if self._templates else 0} 个                                │
│  审计日志: {self._safety.get_today_log_count() if self._safety else 0} 条                           │
└──────────────────────────────────────────────────┘""")

    def _print_memory(self, cmd: str):
        """打印/搜索记忆"""
        if not self._memory:
            print("(记忆系统未启用)")
            return
        
        parts = cmd.split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        results = self._memory.search(query or "*", limit=10)
        
        print(f"\n📚 记忆 ({len(results)}条):\n")
        for entry in results:
            bar = "█" * int(getattr(entry, 'score', 0.5) * 10) + "░" * (10 - int(getattr(entry, 'score', 0.5) * 10))
            print(f"  [{getattr(entry, 'tier', {}).value if hasattr(entry,'tier') else '?'}] {getattr(entry, 'title', '')[:40]}")
            print(f"  评分:[{bar}] | 内容:{str(getattr(entry, '', ''))[:80]}...\n")

    def _print_templates(self):
        """打印可用模板"""
        if not self._templates:
            print("(模板系统未启用)")
            return
        
        templates = self._templates.list_all()
        print(f"\n📋 可用模板 ({len(templates)}个):\n")
        for t in templates:
            runs = f"{t.run_count}次运行"
            avg = f"{t.avg_time_s:.0f}s平均" if t.avg_time_s > 0 else ""
            print(f"  🔹 {t.name}: {t.description[:40]} [{runs}] [{avg}]")
        print()

    def _print_history(self):
        """打印最近任务历史"""
        if not self._history:
            print("(历史记录未启用)")
            return
        
        recent = self._history.get_recent(10)
        stats = self._history.get_statistics(1)
        
        print(f"\n📊 任务统计:\n")
        print(f"  今日: {stats['total_tasks']}个 | 成功率: {stats['success_rate']}")
        if float(stats.get('total_time_saved_s', 0)) > 0:
            print(f"  节省: {stats.get('total_time_saved_human', '-')}")
        print(f"\n📝 最近任务:\n")
        for r in recent:
            icon = {"success": "✅", "failed": "❌", "partial": "⚠️"}.get(r.status, "🔄")
            print(f"  {icon} {r.instruction[:45]} ({r.date_str})")
        print()

    @staticmethod
    def _print_help():
        print("""
╔════════════════════════════════════════════════╗
║  Desktop God Agent v0.2 — 可用命令               ║
╠════════════════════════════════════════════════╣
║  <自然语言指令>    执行任务                       ║
║  /日报 /清理桌面    快捷指令                       ║
║  status            查看系统状态                     ║
║  mem [关键词]      搜索记忆                         ║
║  模板               列出可用模板                     ║
║  历史               查看任务历史                     ║
║  help              显示此帮助                       ║
║  exit / quit       退出系统                         ║
║                                                 ║
║  Ctrl+Alt+Shift+Q 触发紧急停止                    ║
╚════════════════════════════════════════════════╝""")

    def shutdown(self):
        """优雅关闭"""
        self._log.info("\n正在关闭所有子系统...")
        self._running = False

        order = [
            ("安全控制", lambda: self._safety.reset_emergency() if self._safety else None),
            ("世界模型", lambda: self._world_model.stop_monitoring() if self._world_model else None),
            ("双鼠标", lambda: self._dual_mouse.stop() if self._dual_mouse else None),
            ("圈养体系", lambda: asyncio.get_event_loop().run_until_complete(
                self._ranch.shutdown()) if self._ranch else None),
            ("截图器", lambda: self._screencap.close() if self._screencap else None),
            ("UIA扫描", lambda: self._uia_scanner.stop_monitoring() if self._uia_scanner else None),
            ("记忆系统", lambda: self._memory.close() if self._memory else None),
        ]

        for name, fn in order:
            try:
                fn()
                self._log.info(f"[✓] {name}")
            except Exception as e:
                self._log.warning(f"[△] {name}: {e}")

        self._log.info("👋 Desktop God Agent v0.2 已关闭。再见！")


def main():
    parser = argparse.ArgumentParser(
        description="Desktop God Agent v0.2 — 你的桌面AI自治代理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                              # 交互模式
  python main.py "打开Chrome并访问百度"          # 单指令
  python main.py --headless                    # 无GUI模式
  python main.py --log-level DEBUG             # 调试日志""",
    )
    parser.add_argument("command", nargs="?", default="", help="要执行的指令")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(args.log_level)
    log = logging.getLogger("GodAgent")

    agent = DesktopGodAgent()

    try:
        result = agent.run(args.command)
        if args.command:
            if 'response' in result:
                print(result['response'])
            elif 'status' in result:
                sys.exit(0 if result['status'] in ('completed', 'done', 'partial') else 1)
    except Exception as e:
        log.critical(f"Fatal: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
