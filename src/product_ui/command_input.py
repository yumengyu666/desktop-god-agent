"""
命令输入层 - 支持多种输入方式
1. 自然语言输入（主入口）
2. 快捷指令（/日报 /清理 /发送）
3. 指向输入（配合双鼠标）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("ProductUI.Command")


@dataclass
class ParsedCommand:
    """解析后的命令"""
    raw: str                          # 原始输入
    command_type: str                 # natural / shortcut / point / drag
    action: str                       # 动作词
    target: str = ""                  # 目标对象
    params: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    suggested_template: Optional[str] = None  # 匹配到的模板名
    context_hint: Dict = field(default_factory=dict)


# 内置快捷指令映射
SHORTCUT_COMMANDS: Dict[str, Dict] = {
    "/日报": {
        "action": "generate_daily_report",
        "template": "daily_report",
        "description": "生成今日工作日报",
        "params": {"date": "today"},
    },
    "/周报": {
        "action": "generate_weekly_report", 
        "template": "weekly_report",
        "description": "生成本周工作周报",
    },
    "/清理桌面": {
        "action": "cleanup_desktop",
        "template": "desktop_cleanup",
        "description": "整理并分类桌面文件",
    },
    "/清理下载": {
        "action": "cleanup_downloads",
        "template": "downloads_cleanup",
        "description": "整理下载文件夹",
    },
    "/状态": {
        "action": "show_status",
        "description": "显示系统当前状态面板",
    },
    "/记忆": {
        "action": "show_memory",
        "description": "查看AI记忆内容",
    },
    "/历史": {
        "action": "show_history",
        "description": "查看任务执行历史",
    },
    "/帮助": {
        "action": "show_help",
        "description": "显示可用命令列表",
    },
}


class CommandInput:
    """
    命令解析器 - 统一处理各种输入方式
    """

    def __init__(self):
        self._custom_shortcuts: Dict[str, Dict] = dict(SHORTCUT_COMMANDS)

    def parse(self, user_input: str, screen_context: Optional[Dict] = None) -> ParsedCommand:
        """
        解析用户输入
        
        Args:
            user_input: 原始用户输入
            screen_context: 当前屏幕上下文（可选，用于指向输入理解）
            
        Returns:
            解析后的结构化命令
        """
        raw = user_input.strip()
        if not raw:
            return ParsedCommand(raw="", command_type="empty", action="none")

        # 1. 快捷指令检测
        if raw.startswith("/"):
            return self._parse_shortcut(raw)

        # 2. 拖拽文件输入检测 (如: "压缩这个 [file_path]")
        if self._is_drag_input(raw):
            return self._parse_drag(raw)

        # 3. 自然语言解析
        return self._parse_natural(raw, screen_context)

    def _parse_shortcut(self, raw: str) -> ParsedCommand:
        """解析快捷指令"""
        cmd_def = self._custom_shortcuts.get(raw.lower())
        
        if cmd_def:
            return ParsedCommand(
                raw=raw,
                command_type="shortcut",
                action=cmd_def["action"],
                target=cmd_def.get("description", ""),
                params=cmd_def.get("params", {}),
                confidence=0.98,
                suggested_template=cmd_def.get("template"),
            )

        # 未知的快捷指令
        return ParsedCommand(
            raw=raw,
            command_type="shortcut",
            action="unknown_command",
            target=raw,
            confidence=0.3,
        )

    def _parse_drag(self, raw: str) -> ParsedCommand:
        """解析拖拽文件输入"""
        # 提取文件路径
        path_match = re.search(r'[A-Z]:\\[^\s]+|[a-z]:/[^\s]+|"[^"]+\.\w+"', raw)
        file_path = path_match.group(0).strip('"') if path_match else ""

        # 提取动作
        action_match = re.match(r'(压缩|翻译|整理|发送|打开|转换|重命名)\s*', raw)
        action = action_match.group(1) if action_match else "process"

        return ParsedCommand(
            raw=raw,
            command_type="drag",
            action=f"file_{action}",
            target=file_path or "unknown_file",
            params={"file_path": file_path},
            confidence=0.9 if file_path else 0.5,
        )

    def _parse_natural(self, raw: str, context: Optional[Dict]) -> ParsedCommand:
        """自然语言解析"""
        lower = raw.lower()

        # 动作词识别
        action_keywords = [
            ("打开", "open"), ("访问", "visit"), ("搜索", "search"),
            ("下载", "download"), ("上传", "upload"), ("发送", "send"),
            ("整理", "organize"), ("删除", "delete"), ("移动", "move"),
            ("复制", "copy"), ("创建", "create"), ("导出", "export"),
            ("帮助", "help"), ("查找", "find"), ("修复", "fix"),
        ]
        
        detected_action = "do_task"  # 默认通用任务
        for cn_word, en_action in action_keywords:
            if cn_word in raw or en_action in lower:
                detected_action = en_action
                break

        # 目标提取（去掉动作词后剩下的部分）
        target = raw
        for cn_word, _ in action_keywords:
            if cn_word in raw:
                target = raw.replace(cn_word, "", 1).strip()
                break

        # 置信度评估
        confidence = min(0.95, 0.6 + len(raw) * 0.01 + (1.0 if context else 0))

        # 模板匹配建议
        template = self._suggest_template(raw)

        return ParsedCommand(
            raw=raw,
            command_type="natural",
            action=detected_action,
            target=target[:200],
            confidence=confidence,
            suggested_template=template,
            context_hint=context or {},
        )

    def _is_drag_input(self, text: str) -> bool:
        """检测是否为拖拽文件输入"""
        has_path = bool(re.search(r'[A-Za-z]:[/\\]', text))
        drag_indicators = ["这个", "它", "该文件", "附件", "图片"]
        return has_path and any(ind in text for ind in drag_indicators)

    def _suggest_template(self, text: str) -> Optional[str]:
        """根据输入建议匹配模板"""
        for keyword, cmd_def in SHORTCUT_COMMANDS.items():
            if keyword.lstrip("/") in text or keyword in text:
                return cmd_def.get("template")
        return None

    def get_available_commands(self) -> List[Dict]:
        """获取所有可用命令列表"""
        result = []
        for key, val in self._custom_shortcuts.items():
            result.append({
                "command": key,
                "description": val.get("description", ""),
                "template": val.get("template", ""),
            })
        result.sort(key=lambda x: x["command"])
        return result

    def register_shortcut(self, trigger: str, definition: Dict):
        """注册自定义快捷指令"""
        if not trigger.startswith("/"):
            trigger = f"/{trigger}"
        self._custom_shortcuts[trigger] = definition
