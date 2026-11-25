# 记忆 MCP 接口

Codex、Claude Code、Gemini CLI 及其他支持 MCP stdio 的客户端，可以用同一套工具检索和读取 Stellar Secretary 知识库。

| 工具 | 用途 |
| --- | --- |
| `search_memory` | 按关键词检索，返回记录 ID、标题、来源和匹配片段。可以用 `next_offset` 继续查看。 |
| `read_memory` | 按记录 ID 读取归档正文或摘要。长正文可按 `next_offset` 分段读取。 |

## 桌面安装版

打开「模型与设置 → 连接 AI 助手」，开启只读访问，选择客户端，复制并合并配置。Claude Code 的 .mcp.json 位于项目目录。点击「测试连接」，保持知识秘书运行并重新打开客户端。多个 MCP 服务器可同时保留。有附件出处的搜索结果会返回 citations，包含文件名、已知页码、命中片段和可打开的本机链接。

## 从源码启用

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

## 一次工具调用是怎么完成的

假设你在已经连接知识秘书的 AI 客户端里问：“上次采购的发票里列了哪些项目？给我原文出处。”这里有三个角色。模型根据问题选择工具并给出参数，客户端负责执行调用、把结果放回对话，知识秘书负责检索和读取资料。MCP 规定了客户端如何发现和调用这些工具。下面的参数和记录 ID 均为示例。

1. **发现工具。** 客户端按配置启动 `stellar-memory`（源码版启动 `memory_mcp.py`），通过标准输入输出建立 MCP 会话。调用 `tools/list` 时，客户端能看到工具名、用途和参数定义。项目用 FastMCP 的 `@server.tool` 注册 Python 函数，由函数签名、类型标注和文档字符串提供这些信息。[工具定义](../secretary/memory_mcp.py)
2. **搜索发票。** 模型可以选择 `search_memory`，给出参数 `{"query":"采购发票","limit":3}`。客户端通过 `tools/call` 将这次调用交给桥接程序。桥接程序访问本机的 `/api/status`，确认应用身份，取得令牌，再向 `/api/memory` 提交带有 `action: "search"` 的请求。桌面服务检查只读访问开关和公司模式后，调用知识库的 `library.query`。[桥接实现](../secretary/memory_mcp.py) · [服务端入口](../secretary/server.py) · [检索实现](../secretary/memory_access.py)
3. **按需读正文。** 搜索结果中的每条记录都有 `id`、标题和片段。若命中附件中的已知出处，`citations` 还会给出文件名、摘录、可用的页码和本机链接。如果片段只显示发票抬头，模型可以取其中一条记录的 ID，发起第二次调用：

   ```json
   {
     "name": "read_memory",
     "arguments": {
       "record_id": "0123456789abcdef0123456789abcdef",
       "field": "text",
       "limit": 5000
     }
   }
   ```

   这是 MCP `tools/call` 的参数示例。服务按 ID 读取这条归档，把已提取的正文放在 `content` 里。也可以指定 `field: "summary"` 读取已有摘要。若 `next_offset` 有值，客户端可以用它继续读下一段。[分页读取实现](../secretary/memory_access.py)
4. **回答并给出来源。** 客户端把工具结果交回模型。模型可以根据读到的发票项目作答，并引用搜索时拿到的出处链接。如果第一次搜索返回的摘录已经足够，模型也可以直接回答。下一步取决于问题和已返回的内容。

### 微信分享的文件怎么生成摘要

从微信选择文件，在手机归档页勾选几份材料并填写文字后，手机把它们作为一次归档请求发给电脑。桌面先保存归档。对于新建的附件归档，电脑开启自动总结、且该手机已授权当前模型服务生成摘要时，桌面会将这条记录加入总结队列。这里由应用代码选定要处理的记录并安排模型请求。合并几张图片、一份 PDF 和文字生成摘要，整个过程都可以在关闭 Memory MCP 的情况下完成。[手机提交](../ios/StellarSecretary/Companion.swift) · [桌面接收与摘要授权](../secretary/mobile.py)

### 怎么验证

在已安装项目及 MCP 依赖的源码环境中运行：

```sh
.venv/bin/python -m unittest tests.test_memory_mcp -v
```

测试会用临时知识库启动真实的 stdio 客户端和工具进程，列出两个工具，搜索一份测试资料，再用返回的 ID 读取正文。它还检查关闭访问和启用公司模式时的拒绝行为。这验证的是工具能否被发现、执行并返回正确数据；具体模型在一段对话里会选择调用几次，由客户端和模型决定。[集成测试](../tests/test_memory_mcp.py)
