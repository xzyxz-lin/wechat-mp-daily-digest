# 安装与配置指南

## 一、Docker Desktop 安装

> 安装包请下载到 `A:\开发环境\开发环境\Docker\`。

### 下载

Docker Desktop for Windows：
https://www.docker.com/products/docker-desktop/

### 安装要点

1. 运行安装包，按向导完成
2. 安装过程中会提示启用 WSL 2（Windows Subsystem for Linux），按提示操作
3. 安装完成后**重启电脑**
4. 启动 Docker Desktop，等待右下角图标变成绿色（Docker 引擎已就绪）
5. 验证安装：
   ```bash
   docker --version
   docker run hello-world
   ```

### 常见问题

- **WSL 2 安装失败**：手动安装 WSL，`wsl --install`，重启后再装 Docker
- **虚拟化未开启**：进 BIOS 开启 VT-x / AMD-V
- **Docker 启动慢**：第一次启动会解压镜像，耐心等待

## 二、WeWe RSS 启动

```bash
cd "A:\workbuddy项目\论文观察台\wewe-rss"
docker-compose -f docker-compose.sqlite.yml up -d
```

查看日志：
```bash
docker-compose -f docker-compose.sqlite.yml logs -f
```

停止：
```bash
docker-compose -f docker-compose.sqlite.yml down
```

启动后浏览器访问 http://localhost:4000。

## 三、微信读书扫码登录

1. 进入 **账号管理** → **添加读书账号**
2. 微信扫码登录（用手机微信扫页面上的二维码）
3. **重要：不要勾选"24小时后自动退出"**，否则每天都要重新扫码

## 四、添加公众号订阅源

1. 进入 **公众号源** 标签
2. 点击 **添加+**，在弹窗中粘贴任意一篇公众号文章链接
   - 例如：`https://mp.weixin.qq.com/s/Xco_si2ARaf5FpHNS8KL-A`
3. WeWe RSS 会自动识别公众号、获取历史和最新文章

**注意**：
- 添加频率过高（一天超过 10 个）会被微信读书风控 24 小时
- 分批添加，今天加 3 个，明天加剩下的

### 获取 feed_id

添加成功后，每个订阅源有独立的 feed id，例如 `MP_WXS_123`。在 `/feeds/all.json` 中，每个 item 都会带这个 id。

获取所有 feed 列表：
```bash
curl http://localhost:4000/feeds/all.json | python -c "import json,sys; d=json.load(sys.stdin); print('\n'.join([f\"{i.get('author','')} - {i.get('id','')}\" for i in d.get('items',[])]))" | sort -u
```

将公众号名与 feed_id 对应填入 `config/config.json`。

## 五、163 邮箱授权码获取

> 推送用的是 SMTP 发邮件，需要"授权码"而不是登录密码。

1. 登录 https://mail.163.com
2. 顶部 **设置** → **POP3/SMTP/IMAP**
3. 开启 **SMTP 服务** 和 **IMAP 服务**
4. 设置"授权密码"（会要求短信验证）
5. 记下授权码（类似 `ABCDEFGHIJKLMNOP` 的字符串）
6. 填入 `config/config.json` 的 `email.password` 字段

## 六、Python 依赖安装

```bash
cd "A:\workbuddy项目\论文观察台\scripts"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 七、首次手动测试

```bash
cd "A:\workbuddy项目\论文观察台\scripts"
python daily.py
```

应该看到：
1. 控制台打印今天抓取到的文章数量
2. 在 `A:\研零课题\研零课题资料\每日推送\每日论文推送\` 生成 `YYYY-MM-DD.html` 和 `.md`
3. 邮箱 `xzyxzy0202@163.com` 收到一封当日文章汇总邮件

如果某一步失败，参考"故障排查"。

## 八、故障排查

### Docker 开机自动启动（已禁用）

Docker Desktop **不会**开机自启。如需使用：
- 双击桌面「论文观察台」快捷方式，脚本会自动启动 Docker
- 或直接双击桌面 Docker 快捷方式手动打开

> 详见 [Docker 自启动问题排查与修复记录](docker-troubleshooting.md)。

### WeWe RSS 启动失败

- 检查端口 4000 是否被占用
- 查看 docker logs
- 重启 Docker Desktop

### 微信读书账号显示"失效"

- 重新扫码登录
- 检查是否勾选了"24小时后自动退出"

### 添加公众号失败 / "今日小黑屋"

- 等 24 小时再试
- 减少每日添加数量
- 切换微信读书账号

### 邮件发送失败

- 检查授权码是否正确（不是登录密码）
- 163 SMTP 服务器：`smtp.163.com`，SSL 端口 `465`
- 检查 config.json 中 receivers 配置正确
- 部分网络环境需要开启"客户端授权码"而非"授权密码"

### 抓取不到文章

- 检查 WeWe RSS 是否在运行（curl http://localhost:4000）
- 检查账号是否过期
- 手动触发更新：在浏览器打开 `http://localhost:4000/feeds/MP_WXS_xxx.rss?update=true`