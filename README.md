# Obsidian 仓库对比页面

仅依赖 Python 3.10+，无须安装第三方包。页面服务必须运行在存放本地仓库的电脑上，输入路径相对于该电脑，而非浏览器所在设备。支持 `~` 和绝对路径。

## 启动页面

```bash
./ob-sync.sh start     # 后台启动
./ob-sync.sh status    # 查看状态
./ob-sync.sh restart   # 重启，沿用上次启动参数
./ob-sync.sh stop      # 停止
```

Linux/macOS 可从任意工作目录调用此脚本。默认监听 `127.0.0.1:8899`，使用 Python 3.10+；自定义 Python 可设置 `PYTHON_BIN`。脚本只管理自身启动且进程身份匹配的服务，旧的手动启动进程需要先停止。

自定义启动参数：

```bash
./ob-sync.sh start --port 8899 --host 127.0.0.1
./ob-sync.sh restart --port 9900
```

不带参数的 `restart` 沿用上次参数；`start` 不带参数使用默认配置。启动参数均传递给 `server.py`，相对仓库目录以项目目录为基准。日志追加写入 `.run/server.log`，进程信息保存在 `.run/server.json`。查看日志：

```bash
tail -f .run/server.log
```

访问 http://127.0.0.1:8899 ，填写本地仓库路径、远程服务地址，点击“扫描并对比”。可选择“另一个仓库目录”，直接比较本机可访问的两个目录（包括已挂载的远程目录）。

- 递归扫描所有目录，本地跳过所有以 `.` 开头的文件及目录；跳过符号链接。
- 文件树仅显示相对路径，支持目录折叠、路径搜索和状态筛选。
- 绿色：内容一致；蓝色“修改”：内容不同；黄色“本地新增”；紫色“远程新增”。
- 点击文档后可切换本地/远程原始文本。读取保留换行，不渲染 HTML。
- 非 UTF-8 文件仍列出，标记“无法对比”，不把读取错误误判为新增。
- 扫描是当时的快照；文件变化后重新扫描。本地新增可 Push 到远程，远程新增可 Pull 到本地，内容不同同时提供两个按钮。Push/Pull 会用来源内容覆盖目标文件，缺失的父目录自动创建；成功后状态更新为一致。远程 HTTP 模式分别调用现有 `/notes/write` 和 `/notes/read`，无需新增写入或拉取接口。

## 远程列表接口

原服务仅支持 `/notes/write` 与 `/notes/read`，无法枚举远程文件。因此，要识别“远程新增”，必须增加 `POST /notes/list`，或使用目录对比模式。可以将本项目的 `server.py` 放到远程电脑，替代原服务运行：

```bash
python3 server.py --remote-only --host 0.0.0.0 --port 9988 --vault /实际远程仓库路径
```

请先停止占用 9988 的旧服务。此脚本不会读取旧 `config.json`，仓库和端口由启动参数指定。保留 `POST /notes/write`（写入）、`POST /notes/read`（读取），增加：

```http
POST /notes/list
Content-Type: application/json

{}
```

```json
{"ok":true,"files":[{"path":"工作/会议.md","hash":"UTF-8 原始内容的 SHA-256 十六进制值"}],"warnings":[]}
```

`hash` 对 UTF-8 解码后重新编码的内容计算，保留 CRLF/LF 差异。也支持只返回 `path`，页面服务会逐个调用 `/notes/read` 计算哈希。读取失败的文件可返回 `error`，同时 `hash` 为 null。路径必须是仓库内相对路径。

本机页面服务默认仅监听 127.0.0.1，因为它允许读取用户指定目录。远程服务无内置身份验证；需公网使用时通过反向代理配置认证和 HTTPS。HTTP 请求由本机 Python 服务转发，无需远程配置 CORS。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

## 示例仓库

页面对比来源选择“另一个仓库目录”，本地填写项目下的 `examples/local`，对比仓库填写 `examples/remote`，即可查看四种状态的演示。使用时换成你的实际路径即可。

## 删除远程笔记

选择远程已存在的笔记后显示 Del 按钮，点击调用 `POST /notes/delete`，请求体为 `{"path":"相对路径"}`，成功响应需包含 `"ok": true`。目录模式删除对比目录中的对应文件。仅删除远程文件；本地存在时状态变为本地新增，否则从树中移除。删除失败时保留原状态。

## Diff 差异对比

选择“修改”状态的文件后，点击 Diff 查看左右并排的逐行对比：左侧为本地，右侧为远程。红色为本地被删除或修改的行，绿色为远程新增或修改的行；带行号及新增、删除、修改统计。行尾标记区分 LF、CRLF、CR 和末尾无换行。每次打开都会重新读取两端内容；使用远程现有 `/notes/read` 接口，不需要新增远程接口。同步后回到内容预览。

填写本地路径、对比仓库路径和远程 HTTP 地址后会立即保存至浏览器 localStorage，无需扫描成功。两个对比来源分别记忆输入内容，重新打开页面自动恢复。保存范围为当前浏览器及页面地址（协议、主机和端口）；清除浏览器站点存储后需重新填写。

## Windows 启停脚本

安装 Python 3.10+ 后，在 PowerShell 或 CMD 中使用：

```powershell
.\ob-sync.cmd start
.\ob-sync.cmd status
.\ob-sync.cmd restart
.\ob-sync.cmd stop
```

自定义参数及含空格的路径：

```powershell
.\ob-sync.cmd start --port 8899 --vault "D:\My Notes"
```

脚本优先使用 `py -3`，其次使用 PATH 中的 `python`；可用环境变量 `PYTHON_BIN` 指定 Python 可执行文件完整路径。后台启动后可以关闭终端，日志及进程记录同样保存在项目 `.run` 目录。不带参数的 restart 沿用上次参数。

Windows 通过系统自带的 Windows PowerShell/CIM 校验进程创建时间和命令行，通过文件锁避免多个启停命令冲突。它不会恢复缺失的进程记录；若手动运行的服务占用了端口，请先在原终端停止服务，再使用脚本启动。原有 Linux/macOS 的 `.sh` 脚本仍可使用。
