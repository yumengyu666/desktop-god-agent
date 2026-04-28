"""
Desktop God Agent — 主入口程序

启动流程：
  1. 加载配置 (.env)
  2. 初始化各子系统
     ├── 模型网关 (DeepSeek + Ollama + Gemini)
     ├── 感知系统 (屏幕截图 + UIA + OCR)
     ├── 执行引擎 (鼠标键盘 + Win32)
     ├── 双鼠标系统 (透明窗口 + 蓝光标)
     ├── 世界模型 (状态快照 + 变化检测)
     ├── 记忆系统 (三层记忆 + 晋升)
     ├── 多Agent系统 (5角色编排)
     └── 安全控制 (急停 + 审计 + 权限)
  3. 启动监控循环
  4. 进入命令循环（等待用户指令）

使用方式：
  python main.py                    # 交互模式
  python main.py "打开Chrome"       # 单指令模式
  python main.py --headless         # 无GUI模式
"""

import sys
import os
import time
import logging
import argparse

# ---- 确保项目根目录在路径中 ----
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# 日志配置
# ============================================================

def setup_logging(level: str = "INFO") -> None:
    """配置日志系统"""
    from src.config.settings import settings
    
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-5s | %(message)s',
        datefmt='%H:%M:%S',
    ))
    
    # 文件输出
    from datetime import datetime
    log_file = log_dir / f"agent_{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(name)-30s | %(levelname)-8s | %(funcName)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


from pathlib import Path


class DesktopGodAgent:
    """
    Desktop God Agent 主类
    
    整合所有子系统的总控制器，
    提供统一的用户接口和任务执行入口。
    """

    def __init__(self):
        self._logger = logging.getLogger("GodAgent")
        
        # 子系统实例（延迟初始化）
        self._gateway = None
        self._screencap = None
        self._uia_scanner = None
        self._ocr = None
        self._executor = None
        self._dual_mouse = None
        self._world_model = None
        self._memory = None
        self._orchestrator = None
        self._safety = None
        
        self._running = False

    def initialize(self) -> bool:
        """
        初始化所有子系统
        
        Returns:
            True表示全部成功，False表示部分失败
        """
        self._logger.info("=" * 60)
        self._logger.info("Desktop God Agent 初始化中...")
        self._logger.info("=" * 60)

        from src.config.settings import settings
        
        # 检查配置完整性
        missing = settings.validate()
        if missing:
            self._logger.warning(f"缺少配置项: {missing}，相关功能可能不可用")
        
        settings.ensure_dirs()

        success_count = 0
        total = 9

        # 1. 模型网关
        try:
            from src.gateway.model_gateway import get_gateway
            self._gateway = get_gateway()
            success_count += 1
            self._logger.info("[✓] 模型网关")
        except Exception as e:
            self._logger.error(f"[✗] 模型网关: {e}")

        # 2. 屏幕截图
        try:
            from src.perception.screenshot import get_screencap
            self._screencap = get_screencap()
            w, h = self._screencap.screen_size
            self._logger.info(f"[✓] 屏幕截图 ({w}x{h})")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] 屏幕截图: {e}")

        # 3. UIA扫描器
        try:
            from src.perception.uia_scanner import UIAScanner
            self._uia_scanner = UIAScanner()
            self._logger.info("[✓] UIA扫描器")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] UIA扫描器: {e}")

        # 4. OCR引擎
        try:
            from src.perception.ocr_engine import get_ocr
            self._ocr = get_ocr()
            self._logger.info("[✓] OCR引擎")
            success_count += 1
        except Exception as e:
            self._logger.warning(f"[△] OCR引擎: {e} (可选)")

        # 5. 执行引擎
        try:
            from src.execution.executor import get_executor
            self._executor = get_executor()
            self._logger.info("[✓] 执行引擎")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] 执行引擎: {e}")

        # 6. 双鼠标系统
        try:
            from src.dual_mouse.ai_cursor import DualMouseSystem
            self._dual_mouse = DualMouseSystem()
            if self._dual_mouse.start():
                self._logger.info("[✓] 双鼠标系统")
                success_count += 1
            else:
                self._logger.warning("[△] 双鼠标系统: 启动失败（可选）")
                self._dual_mouse = None
        except Exception as e:
            self._logger.warning(f"[△] 双鼠标系统: {e} (可选)")
            self._dual_mouse = None

        # 7. 世界模型
        try:
            from src.world_model.world_model import WorldModel
            self._world_model = WorldModel()
            self._logger.info("[✓] 世界模型")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] 世界模型: {e}")

        # 8. 记忆系统
        try:
            from src.memory.memory_system import MemorySystem
            self._memory = MemorySystem(db_path=settings.MEMORY_DB_PATH)
            stats = self._memory.get_stats()
            self._logger.info(f"[✓] 记忆系统 ({stats['total']} 条记忆)")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] 记忆系统: {e}")

        # 9. 安全控制
        try:
            from src.security.safety import SafetySystem
            self._safety = SafetySystem(audit_dir=settings.AUDIT_LOG_DIR)
            self._safety.start_stop_listener(settings.EMERGENCY_STOP_KEY)
            self._logger.info(f"[✓] 安全控制 (急停: {settings.EMERGENCY_STOP_KEY})")
            success_count += 1
        except Exception as e:
            self._logger.error(f"[✗] 安全控制: {e}")

        # Agent编排器（依赖上面所有）
        if self._gateway and self._executor:
            try:
                from src.agent.agents import get_orchestrator
                self._orchestrator = get_orchestrator()
                self._orchestrator.initialize(
                    model_gateway=self._gateway,
                    executor=self._executor,
                )
                self._logger.info("[✓] Agent编排器")
            except Exception as e:
                self._logger.error(f"[✗] Agent编排器: {e}")

        # 启动后台监控
        if self._world_model:
            self._world_model.start_monitoring(interval_sec=2.0)

        self._logger.info("=" * 60)
        self._logger.info(f"初始化完成: {success_count}/{total+1} 个子系统就绪")
        self._logger.info("=" * 60)

        return success_count >= total // 2  # 超过一半就算可用

    def run(self, instruction: str = "") -> dict:
        """
        执行用户指令或进入交互模式
        
        Args:
            instruction: 单条指令，空字符串则进入交互模式
            
        Returns:
            执行结果字典
        """
        if not self._running:
            self.initialize()
            self._running = True

        if instruction:
            return self._execute_single(instruction)
        else:
            return self._interactive_loop()

    def _execute_single(self, instruction: str) -> dict:
        """执行单条指令"""
        self._logger.info(f"\n{'─'*50}")
        self._logger.info(f">>> 用户指令: {instruction}")
        self._logger.info(f"{'─'*50}\n")

        start_time = time.time()

        try:
            # 通过Agent编排器运行任务
            if self._orchestrator:
                import asyncio
                
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                result = loop.run_until_complete(
                    self._orchestrator.run_task(instruction)
                )
                
                elapsed = (time.time() - start_time) * 1000
                result['elapsed_ms'] = elapsed
                
                self._logger.info(f"\n{'='*50}")
                status_icon = '🟢' if result.get('status') == 'completed' else '🟡'
                self._logger.info(f"{status_icon} 完成 | "
                           f"{result.get('completed_steps', 0)}"
                           f"/{result.get('total_steps', 0)} 步 | "
                           f"{elapsed:.0f}ms")
                self._logger.info(f"{'='*50}\n")
                
                return result
            
            else:
                # 降级：直接用模型网关处理
                from src.gateway.model_gateway import ChatMessage
                resp = self._gateway.chat([
                    ChatMessage(role="user", content=instruction)
                ])
                
                return {
                    'status': 'completed',
                    'response': resp.content,
                    'model': resp.model_name,
                    'latency_ms': resp.latency_ms,
                }

        except KeyboardInterrupt:
            self._logger.warning("\n[!] 操作被用户中断")
            return {'status': 'interrupted', 'error': 'KeyboardInterrupt'}
            
        except Exception as e:
            self._logger.error(f"\n[✗] 执行错误: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'error': str(e)}

    def _interactive_loop(self) -> dict:
        """交互式命令循环"""
        self._logger.info("\n" + "╔" + "═"*58 + "╗")
        self._logger.info("║" + "  Desktop God Agent 交互模式".center(58) + "║")
        self._logger.info("║" + "  输入自然语言指令，Ctrl+C 或 'exit' 退出".center(56) + " ║")
        self._logger.info("╚" + "═"*58 + "╝\n")

        results_history = []
        
        while self._running:
            try:
                user_input = input("🤖 GodAgent > ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ('exit', 'quit', 'q', '退出'):
                    self._logger.info("用户请求退出")
                    break
                    
                if user_input.lower() == 'status':
                    self._print_status()
                    continue
                    
                if user_input.lower().startswith('mem'):
                    self._print_memory(user_input)
                    continue
                    
                if user_input.lower() == 'help':
                    self._print_help()
                    continue

                result = self._execute_single(user_input)
                results_history.append(result)
                
                # 显示结果摘要
                if 'response' in result:
                    print(f"\n📝 回答:\n{result['response']}\n")
                elif 'status' in result:
                    steps = f"{result.get('completed_steps', 0)}/{result.get('total_steps', 0)}"
                    print(f"\n✅ 状态: {result['status']} | 步骤: {steps}\n")

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n(按 Ctrl+C 强制退出请再次按下)")
                time.sleep(0.5)

        self.shutdown()
        return {'status': 'exited', 'history_length': len(results_history)}

    def _print_status(self) -> None:
        """打印系统状态"""
        from src.config.settings import settings
        print(f"""
┌────────────────────────────────────────────┐
│  Desktop God Agent 系统状态                 │
├────────────────────────────────────────────┤
│  模型网关:   {'● 就绪' if self._gateway else '○ 未连接'}                        │
│  屏幕感知:   {'● 就绪' if self._screencap else '○ 未连接'} ({self._screencap.screen_size if self._screencap else '?'})              │
│  UIA扫描:    {'● 就绪' if self._uia_scanner else '○ 未连接'}                        │
│  OCR识别:    {'● 就绪' if self._ocr else '○ 未连接'}                          │
│  执行引擎:   {'● 就绪' if self._executor else '○ 未连接'}                        │
│  双鼠标:     {'● 运行中' if self._dual_mouse else '○ 未启动'}                      │
│  世界模型:   {'● 监控中' if self._world_model and self._world_model._monitoring else '○ 待机'}                   │
│  记忆系统:   {'● 就绪' if self._memory else '○ 未连接'} ({self._memory.get_stats()['total'] if self._memory else '?'}条)           │
│  安全控制:   {'● 急停已激活' if self._safety and not self._safety.is_stopped else '○ 急停未激活'}               │
│  Agent团队:  {'● 就绪' if self._orchestrator else '○ 未连接'}                        │
├────────────────────────────────────────────┤
│  急停热键:   {settings.EMERGENCY_STOP_KEY:<34} │
│  前台应用:   {(self._world_model.get_foreground_app() or '-')[:34]:<34} │
│  审计日志:   {self._safety.get_today_log_count() if self._safety else 0} 条今日                     │
└────────────────────────────────────────────┘
""")

    def _print_memory(self, cmd: str) -> None:
        """打印/搜索记忆"""
        if not self._memory:
            print("(记忆系统未启用)")
            return
        
        parts = cmd.split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        
        results = self._memory.search(query or "*", limit=10)
        
        if not results:
            print(f"(无匹配记忆: '{query}')")
            return
        
        print(f"\n📚 记忆搜索结果 ({len(results)}条):\n")
        for entry in results[:10]:
            score_bar = "█" * int(entry.score * 10) + "░" * (10 - int(entry.score * 10))
            print(f"  [{entry.tier.value}] {entry.title[:40]}")
            print(f"  评分: [{score_bar}] {entry.score:.2f} | "
                  f"成功:{entry.success_count} 失败:{entry.failure_count}")
            print(f"  内容: {entry.content[:80]}...")
            print()

    @staticmethod
    def _print_help() -> None:
        print("""
╔══════════════════════════════════════════╗
║  可用命令                                   ║
╠══════════════════════════════════════════╣
║  <自然语言指令>  执行任务                  ║
║  status          查看系统状态              ║
║  mem [关键词]    搜索记忆                  ║
║  help            显示此帮助                ║
║  exit / quit     退出系统                  ║
║                                            ║
║  Ctrl+Alt+Shift+Q  触发紧急停止           ║
╚══════════════════════════════════════════╝
""")

    def shutdown(self) -> None:
        """优雅关闭所有子系统"""
        self._logger.info("\n正在关闭...")
        self._running = False

        shutdown_order = [
            ("安全控制", lambda: self._safety.reset_emergency() if self._safety else None),
            ("世界模型", lambda: self._world_model.stop_monitoring() if self._world_model else None),
            ("双鼠标", lambda: self._dual_mouse.stop() if self._dual_mouse else None),
            ("截图器", lambda: self._screencap.close() if self._screencap else None),
            ("UIA扫描", lambda: self._uia_scanner.stop_monitoring() if self._uia_scanner else None),
            ("记忆系统", lambda: self._memory.close() if self._memory else None),
        ]

        for name, fn in shutdown_order:
            try:
                fn()
                self._logger.info(f"[✓] {name} 已关闭")
            except Exception as e:
                self._logger.warning(f"[△] {name}: {e}")

        self._logger.info("Desktop God Agent 已关闭。再见！")


def main():
    """CLI入口"""
    parser = argparse.ArgumentParser(
        description="Desktop God Agent - 你的桌面AI自治代理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                              # 交互模式
  python main.py "打开Chrome并访问百度"          # 单指令
  python main.py --headless                    # 无GUI
  python main.py --log-level DEBUG             # 调试日志
""",
    )
    parser.add_argument(
        "command", nargs="?", default="",
        help="要执行的指令（留空则进入交互模式）"
    )
    parser.add_argument("--headless", action="store_true",
                       help="无头模式（不启动双鼠标等GUI）")
    parser.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="日志级别")
    args = parser.parse_args()

    # 配置日志
    setup_logging(args.log_level)
    
    logger = logging.getLogger("GodAgent")
    
    # 启动
    agent = DesktopGodAgent()
    
    if args.headless:
        logger.info("Headless mode: dual mouse disabled")
    
    try:
        result = agent.run(args.command)
        
        # 如果是单指令模式，打印结果后退出
        if args.command:
            if 'response' in result:
                print(result['response'])
            elif 'status' in result:
                exit_code = 0 if result['status'] in ('completed', 'partial') else 1
                sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
