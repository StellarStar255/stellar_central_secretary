# 记忆 MCP 接口

Codex、Claude Code、Gemini CLI 及其他支持 MCP stdio 的客户端，可以用同一套工具检索和读取 Stellar Secretary 知识库。

| 工具 | 用途 |
| --- | --- |
| `search_memory` | 按关键词检索，返回记录 ID、标题、来源和匹配片段。可以用 `next_offset` 继续查看。 |
| `read_memory` | 按记录 ID 读取归档正文或摘要。长正文可按 `next_offset` 分段读取。 |

## 启用

在项目源码目录安装可选依赖。按平时的方式退出旧服务后，启动源码并加上 `--memory-mcp`。如使用自定义知识库，`--data-dir` 填应用中显示的当前资料目录。

```sh
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -m secretary.launcher --data-dir "/path/to/your/library" --memory-mcp
```

Windows 使用 `.venv\Scripts\python.exe`。启动后保持知识秘书运行。使用自定义端口时，应用和 MCP 命令应使用同一个 `--port`。

## 配置客户端

在客户端的 stdio MCP 配置中填写项目里的 Python 解释器和脚本的绝对路径。通用配置如下。

```json
{
  "mcpServers": {
    "stellar-memory": {
      "command": "/path/to/stellar_central_secretary/.venv/bin/python",
      "args": ["/path/to/stellar_central_secretary/secretary/memory_mcp.py", "--port", "8768"]
    }
  }
}
```

Codex CLI 和 Claude Code 也可以用各自的添加命令。

```sh
codex mcp add stellar-memory -- /path/to/python /path/to/secretary/memory_mcp.py
claude mcp add --transport stdio stellar-memory -- /path/to/python /path/to/secretary/memory_mcp.py
```

Gemini CLI 可以把上面的 `mcpServers` 配置放进其 `settings.json`。自己写的应用可以用 MCP 客户端调用这两个工具，再把所需结果交给你选用的模型 API。 [Gemini CLI MCP 文档](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md) · [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

例如向客户端说「先用 stellar-memory 查找最近整理的‘日报例会’，读相关条目，再给出结论和来源」。

## 访问范围

- 连接限本机。默认关闭，公司模式开启时返回拒绝。
- 工具只返回归档记录的标题、来源、匹配片段、正文和摘要。附件原件、聊天历史、写入和删除功能未开放。
- 桥接程序只与本机知识秘书通信。选配的客户端可以将工具返回的资料作为上下文发送给它连接的模型。
