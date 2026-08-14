# Docker 自启动问题排查与修复记录

> 日期：2026-08-14
> 状态：**已解决**

## 问题描述

Windows 开机后，Docker Desktop 自动在后台运行（进程存在、容器运行、端口正常），但：
- **桌面托盘看不到 Docker 图标**
- **双击 Docker 快捷方式报错** `Unable to launch Docker Desktop`
- **右下角系统托盘无 Docker 图标**
- 占用约 885MB 内存（vmmemWSL 进程）

用户期望：开机后 Docker 不应自动启动。

## 错误排查路径（踩坑记录）

### ❌ 误判 1：WSL 发行版 Flags（已排除）

曾误以为 `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss\{GUID}\Flags=15` 的某一位控制自启，
将 Flags 从 15 改为 7，导致 Docker 引擎完全无法启动（`WSL_E_WSL2_NEEDED`）。

**结论**：Flags=15 是 Docker Desktop WSL2 模式的正常值，**绝不能修改**。

### ❌ 误判 2：Windows 快速启动 / 休眠恢复（部分相关但非根因）

观察到 `HiberbootEnabled=1`（快速启动开启），"关机"实际是休眠 → WSL 虚拟机从休眠恢复 →
Docker 引擎自动恢复运行。LastBootUpTime 在快速启动下不可靠。

**结论**：快速启动确实会让 Docker"看起来像自启"，但关闭快速启动只是治标。

### ✅ 根因：注册表 Run 键"禁用"方式无效

**真正原因**：之前通过重命名注册表 Run 键值名来"禁用"Docker 自启：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  "Docker Desktop" → 重命名为 "Docker Desktop__DISABLED_BY_OPT"
  "OneDriveSetup" → 重命名为 "OneDriveSetup__DISABLED_BY_OPT"
```

**关键发现**：**Windows 仍然执行了被重命名的 Run 键值！** 重命名 ≠ 删除，Windows 不在乎值名是什么，
只要存在于 Run 键下就会在登录时执行。所以 Docker 每次登录照样被拉起。

同时 Docker Desktop 内部设置 `AutoStart=false` 和 `OpenUIOnStartupDisabled=true`
只能控制 Docker 自己的行为（不弹 UI），但如果外部已经通过 Run 键启动了 Docker 进程，
这些设置就无法阻止引擎和容器运行。

## 正确修复方案

### 操作步骤

1. **删除**（而非重命名）Docker Desktop 的两个注册表登录启动项：
   - `HKCU\...\Run\Docker Desktop`
   - `HKCU\...\Run\OneDriveSetup`（如果也需要禁用）

2. **保留 Docker 配置**：
   - `AutoStart: false`（应用内不自启）
   - `OpenUIOnStartupDisabled: true`（启动不弹 UI）

3. **停止 Docker Desktop 并关闭 WSL 虚拟机**：
   ```powershell
   docker desktop stop    # 停止 Docker Desktop
   wsl --shutdown         # 关闭 WSL 虚拟机（释放 vmmemWSL 内存）
   ```

4. **验证**：重启电脑后检查
   - 任务管理器中无 `Docker Desktop.exe`、`vmmemWSL`、`com.docker.*` 进程
   - `docker info` 无响应（引擎未运行）
   - 双击 Docker 快捷方式可正常打开

### 备份

操作前导出注册表备份：
```reg
; docker-startup-before-disable-20260814-192745.reg
[HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run]
"Docker Desktop"="\"C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe\""
"OneDriveSetup"="C:\\Program Files\\OneDrive\\SetUp\\OneDriveSetup.exe /thsetupfirst"
```

如需恢复：双击 `.reg` 文件即可重新导入。

## 当前使用方式

Docker 不再开机自启。需要使用时：

1. **日常使用**：双击桌面「公众号论文观察台」→ `start_web.ps1` 自动完成：
   - 启动 Docker Desktop（如未运行）
   - 启动 WeWe RSS 容器（如未运行）
   - 启动 Web 后端（8032）
   - 弹出浏览器（WeWe RSS + 观察台）

2. **单独启动 Docker**：双击桌面 Docker 快捷方式即可正常打开

## 经验教训

| 误区 | 正确做法 |
|------|----------|
| 重命名注册表 Run 键值 = 禁用 | **必须删除**键值，改名无效 |
| AutoStart=false 能阻止外部启动 | AutoStart 只管 Docker 自身行为，不管注册表 Run |
| LastBootUpTime 可判断是否真关机 | 快速启动下不可靠，需看事件日志 6005/6006 |
| 改 WSL Flags 控制自启 | Flags 是内部标志，**绝对不能改** |
| 快速启动 = Docker 自启根因 | 快速启动是放大因素，**Run 键才是触发源** |

## 相关文件

- 启动脚本：`web/start_web.ps1`（含 Docker 自动检测和启动逻辑）
- Docker 配置备份：`.workbuddy/backup/2026-08-14/settings-store.json.bak`
- 注册表备份：`docs/docker-startup-before-disable-20260814-192745.reg`
