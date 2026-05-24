# Baby Agent

一个极简的 Python Agent 系统，基于 DeepSeek API，实现 Planning、Memory、Tool Use 三大核心能力。

## 项目结构

```
baby_agent/
├── agent.py          # 核心 Agent 循环与系统提示
├── commands.py       # 斜杠命令注册与处理
├── memory.py         # 短期记忆 + 长期记忆
├── tools.py          # 工具定义（Schema）与执行实现
├── run.py            # CLI 入口
├── requirements.txt  # 依赖
└── memory_store/     # 长期记忆存储（自动创建）
    └── index.json
```

## 架构设计

### 核心：单一 Agent Loop

Agent 采用单循环架构，没有独立的状态机或模块间编排：

```
用户输入
  ↓
加入短期记忆
  ↓
构建消息（系统提示 + 长期记忆 + 短期历史 + 当前计划）
  ↓
调用 DeepSeek API（带 tools + thinking 模式）
  ↓
┌─ finish_reason == "stop" → 返回文本，存入短期记忆
│
└─ finish_reason == "tool_calls" → 执行工具，结果存入短期记忆 → 循环回 API 调用
```

LLM 自身决定何时规划、何时直接行动，规划能力通过工具调用暴露，而非硬编码到控制流中。

### Planning

通过两个工具实现 LLM 驱动的规划：

| 工具 | 作用 |
|------|------|
| `create_plan(goal, steps)` | 创建分步计划，存储在 `agent.plan` 中 |
| `update_plan(step_id, status)` | 更新步骤状态：pending / in_progress / completed |

计划数据结构：

```python
{
    "goal": "重构认证模块",
    "steps": [
        {"id": 1, "description": "读取 auth.py", "status": "completed"},
        {"id": 2, "description": "编写重构代码", "status": "in_progress"},
    ]
}
```

当前计划在每次 API 调用时注入系统提示，LLM 始终能看到自己的进度。简单任务可跳过规划直接执行。

### Memory

#### 短期记忆（ShortTermMemory）

- 内存中的消息列表，标准 OpenAI 消息格式
- 最大 80 条消息，超出时从最早的非系统消息开始丢弃
- 每轮会话独立，进程退出即清空
- 保留 DeepSeek thinking 模式返回的 `reasoning_content`，原样传回 API

#### 长期记忆（LongTermMemory）

- 文件持久化，存储在 `memory_store/index.json`
- 键值对结构，带时间戳和分类标签
- 跨会话保留，所有事实在每次 API 调用时注入系统提示

```json
[
  {
    "key": "user_name",
    "value": "Alice",
    "timestamp": "2026-05-25T10:00:00",
    "category": "personal"
  }
]
```

### Tool Use

8 个工具，通过 OpenAI Function Calling 协议接入：

| 类别 | 工具 | 功能 |
|------|------|------|
| 文件操作 | `file_read(path)` | 读取文件内容 |
| | `file_write(path, content)` | 写入文件 |
| | `file_list(path)` | 列出目录内容 |
| 代码执行 | `code_execute(command, timeout)` | 执行 shell 命令 |
| 记忆 | `memory_save(key, value, category)` | 保存到长期记忆 |
| | `memory_recall(key)` | 从长期记忆查找 |
| 规划 | `create_plan(goal, steps)` | 创建计划 |
| | `update_plan(step_id, status)` | 更新计划步骤 |

工具执行统一由 `execute_tool(name, args, agent)` 分发，每个工具内部捕获异常，错误信息作为结果返回给 LLM 让其自行调整。

### 斜杠命令

交互模式下输入 `/` 开头的命令可直接操作 Agent 状态，不经过 LLM：

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/clear` | 清空对话历史 |
| `/plan` | 查看当前计划及步骤状态 |
| `/memory` | 列出所有长期记忆 |
| `/prompt` | 切换 Prompt 显示（等价于 Ctrl+O） |
| `/model` | 查看当前模型；`/model gpt-4` 切换模型 |
| `/tools` | 列出可用工具及参数 |
| `/quit` | 退出 Agent |

命令系统基于 `CommandRegistry`，支持 `register()` 动态扩展。命令在 `run.py` 输入循环中优先拦截：以 `/` 开头的输入不会发送给 LLM。

### Thinking 模式

接入 DeepSeek 的思考能力：

- API 调用时启用 `reasoning_effort="high"` 和 `thinking: {type: "enabled"}`
- 返回的 `reasoning_content` 随消息历史原样传回后续 API 调用
- 确保 DeepSeek 要求的推理上下文不被丢失

### 系统提示动态组装

每次 API 调用的系统提示由三部分拼接：

1. **基础人设** — Jarvis 角色，沉稳管家人格
2. **长期记忆** — 所有持久化事实，格式化注入
3. **当前计划** — 活跃计划的步骤与状态

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 API Key
export DEEPSEEK_API_KEY=your-key

# 运行
python3 run.py
```

## 示例交互

```
Baby Agent | model: deepseek-v4-pro | /help for commands (Ctrl+O: toggle prompt display)

You> 列出当前目录的文件
  [tool] file_list({"path": "."})
Agent> Sir, current directory contains the following: agent.py, memory.py, tools.py, run.py, requirements.txt.

You> 记住我的名字是 Alice
  [tool] memory_save({"key": "user_name", "value": "Alice"})
Agent> Noted, Sir. I shall remember that your name is Alice.

You> /memory
Long-term memories:
  user_name: Alice (personal)

You> /tools
Available tools:
  file_read(path: Absolute or relative path to the file)
    Read the contents of a file at the given path.
  ...

You> 我叫什么？
Agent> Your name is Alice, Sir.
```

## 依赖

- `openai>=1.0.0` — 唯一外部依赖，用于调用 DeepSeek API
- 其余均为 Python 标准库（json, os, subprocess, tempfile, datetime）
