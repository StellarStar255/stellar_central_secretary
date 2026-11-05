---
name: stellar-release
description: 发布 Stellar Secretary 的当前改动，包括版本与说明、三平台构建、Mac 签名公证、远端附件校验、GitHub 正式发布和本机更新。在此项目中用户说“发版”或“发布新版”时使用。
---

用户明确要求发版，即授权完成当前版本的正常发布步骤；沿用会话中已确定的设置，不在提交、打标签、上传、公开发布、本机更新之前重复询问。系统沙箱审批必须通过工具正常申请，不能绕过。只有新增凭据、目标不明确、数据冲突等实际阻塞才向用户询问。不要仅因这里列出发布步骤而新增确认环节。

## 项目和工具

在 Stellar Secretary 仓库根目录工作。此机路径为 `/Users/huangqiliang/Documents/Stellar_Mac/stellar_central_secretary`，公开仓库是 `StellarStar255/stellar_central_secretary`。使用 `.venv/bin/python`、`gh` 和仓库中的 `packaging/release.py`，不再逐版生成临时发布脚本。

`packaging/release.py` 从 `secretary/__init__.py` 读取版本，将阶段结果保存在 `build/release-state/<version>/`。子命令限定为当前项目的构建、签名、校验、上传、公开和本机更新。申请可复用的命令前缀 `.venv/bin/python packaging/release.py`，减少后续版本重复系统授权。

## 执行流程

1. 查看工作区、现有版本、远端标签和 release 状态。保留无关改动；不发布截图、真实内网地址、凭据或本地测试资料。发现目标版本已经公开时先核实，不覆盖公开资产。
2. 递增补丁版本，同步两份 README 的版本/发布说明链接，编写 `docs/releases/v<version>.md`，围绕本次最终功能描述。运行相关界面回归、`node --test tests/test_chat_ui.cjs`、完整单元测试与 `git diff --check`。已经通过的检查只在有新改动或新问题时重跑。
3. 使用 GitHub 隐私邮箱 `17609819+StellarStar255@users.noreply.github.com` 提交发布改动；不要把默认个人邮箱推送到公开历史。创建版本标签，`git push --atomic origin main v<version>` 触发三平台流水线。不自动强推或改写已公开版本历史。
4. 在本机运行以下 helper 子命令，日志可写入 `/tmp`。构建和源代码固定后，再按顺序 smoke、签名和验证，避免签名过程中测试同一 app。

```sh
.venv/bin/python packaging/release.py build-mac
.venv/bin/python packaging/release.py smoke-mac
.venv/bin/python packaging/release.py sign-mac --identity 'Developer ID Application: Qiliang Huang (3QCL9WNFBB)' --profile notary
.venv/bin/python packaging/release.py verify-mac --team-id 3QCL9WNFBB
```

签名使用既有钥匙串 `notary` profile，不读取或输出密钥。Mac app 位于 `dist/release-v<version>/Stellar Secretary.app`。检查新 UI/二进制依赖确实被打包，相关场景用隔离的合成资料验证，不修改用户资料。

5. 用 `packaging/release.py ci` 或 `gh run view` 观察带标签提交的最新运行。必要时读失败日志、修复后发布新提交；网络/运行器容量问题最多对失败作业重试两次，保留已成功的平台结果。若同一错误仍出现，报告具体阻塞，不无限重试或跳过检查。等待期间每约 60 秒提供简短进展。
6. 三平台与 release job 全部成功后，依次执行：

```sh
.venv/bin/python packaging/release.py prepare
.venv/bin/python packaging/release.py upload
.venv/bin/python packaging/release.py publish
```

CI 在未配置签名 secrets 时只生成草稿。helper 核对全部 8 个附件，将草稿 Mac 包替换为本机已公证包、更新 SHA256SUMS，再逐项验证远端大小/SHA256 后设为最新正式版。任何校验失败都不公开。上传结果不确定时先读取远端状态；公开后禁止盲目重传。

7. 用户未另有要求时，沿用此项目的既有习惯更新 `/Applications/Stellar Secretary.app`：运行 `packaging/release.py install-local`。helper 要求无活动任务，验证已公证来源与签名，保留旧 app 备份、平稳重启，并核对资料表所有列、公司模式、本机资料目录、正在运行的版本和 UI。若用户正在处理任务，继续完成不受影响的发布工作，延后本机替换，不能终止用户任务来迁就更新。启动或资料核对异常时报告备份路径，不删除备份或操作用户数据库。
8. 最终回复正式 release 链接、主要变化、本机更新结果及实际验证。不要把草稿、上传中或 CI 尚未完成描述成已发版。
