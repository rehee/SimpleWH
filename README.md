# 归位 · 家庭库存系统

中文、适配手机的家庭库存网站。Flask + PostgreSQL，网站、数据库、Cloudflare Tunnel 分别运行在 Docker 容器中。照片保存在独立持久卷，数据库不暴露宿主机端口。

## 已实现

- 主账号首次启动创建；只有主账号可创建、删除普通账号，没有公开注册入口。
- 密码哈希、HttpOnly 会话、CSRF 验证、登录限速；删除账号和修改密码立即撤销会话。
- 架子 / 柜子自动生成具体层；箱子、袋子、无包装支持照片、描述及嵌套位置；地面位置需文字说明。
- 新物品先拍照，填写名称、描述、自定义单位、标签，选择具体容器入库；已有物品可重复入库到不同容器。
- 标签自动持久化、去重，可编辑物品资料与标签。
- 数量支持最多 3 位小数；例如一箱 12 瓶洗碗液按「瓶」入库 12。百分比按每一份包装单独记录，不将不同包装的百分比相加。
- 出库、部分数量转移、完整包装转移、容器转移、清除不符记录、目测剩余百分比。
- 查询显示完整储存链；搜索名称、描述、位置、标签；按标签、容器及其下级、计量方式筛选。
- 容器显示直接库存记录数及包含下级的记录数，点击查看该容器内全部物品。
- 操作历史保留名称、数量、路径、操作人和时间；移动上级容器后，所有下级储存链随之更新。

## 默认容器与规则

默认共 7 个架子：「左1、左2、中1、中2、右1、右2」各 6 层，「中3」5 层；「柜1、柜2」各 5 层。已初始化的旧库会在下次应用启动时自动补上「中3」，不会重复创建已有的同名架子。初始化标记保证重启不会重新生成已经删除的默认设施。

| 容器 | 可放置位置 |
| --- | --- |
| 架子、柜子 | 地面 |
| 层 | 由架子、柜子创建，不能单独移动或删除 |
| 箱子 | 具体层、另一个箱子、地面 |
| 袋子 | 具体层、箱子、另一个袋子、地面 |
| 无包装 | 具体层、箱子、袋子、地面 |

无包装是一组散装物品的收纳记录，可装物品，不能装其他容器。所有物品库存都必须属于一个容器。系统按前述明确类型规则限制「箱子不能放入袋子」。容器不能移动到自身或自身下级。删除前必须移走全部物品及下级容器。

## 本地容器部署

需要已启动的 Docker Desktop（Linux 容器模式），或 Linux 上的 Docker Engine + Compose。

1. 在项目目录准备 `.env`。本次开发已生成一个被 Git 忽略的 `.env`，其中包含随机主账号密码和数据库密码；后续新安装可复制示例：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 填写环境变量：
   - `ADMIN_USERNAME`：主账号名称，3–32 位字母、数字、`_.-`。
   - `ADMIN_PASSWORD`：主账号初始密码，至少 12 位。只在数据库没有主账号时使用，之后在网页修改密码。
   - `POSTGRES_PASSWORD`：数据库密码，建议用随机十六进制字符串。拼接进连接 URL，使用其他特殊字符需 URL 编码。数据库初始化后不能仅靠改 `.env` 更换数据库密码。
   - `COOKIE_SECURE=false`：仅本地 HTTP 使用；通过 Cloudflare HTTPS 使用时设为 `true`。
   - `BIND_ADDRESS=127.0.0.1`：只开放本机；需要家庭局域网访问时可改为 `0.0.0.0`。
   - `APP_PORT=6001`：本机访问端口，可改。

3. 启动和检查：

   ```powershell
   docker compose -f compose.yaml -f compose.build.yaml up -d --build --wait
   docker compose ps
   docker compose logs --tail 100 app
   ```

4. 打开 <http://localhost:6001>，用 `.env` 内的主账号登录。在「家庭账号」创建成员账号。

停止服务用 `docker compose --profile tunnel down`，数据库和照片卷仍保留。**不要使用 `down -v`，它会删除数据卷。** 本地源码更新用 `up.ps1`，已发布镜像更新用 `up_image.ps1`，用法如下。

## GitHub Actions 和启动脚本

`.github/workflows/publish-image.yml` 在推送到 `main` 时自动执行，也可以在 GitHub Actions 页面手动运行。工作流先运行真实 PostgreSQL 集成测试、PowerShell 脚本检查、JavaScript 和 Compose 校验，通过后构建并推送 Linux AMD64 / ARM64 镜像：

- `ghcr.io/rehee/simplewh:latest`：最近成功发布的 main 版本。
- `ghcr.io/rehee/simplewh:main`：同一版本的 main 标签。
- `ghcr.io/rehee/simplewh:sha-<完整提交SHA>`：对应提交，便于固定版本和回退。

工作流使用自带 `GITHUB_TOKEN`，发布任务申请 `packages: write`，无需额外保存仓库发布密码。Actions 固定到经过核对的 commit SHA。若 fork 本仓库，发布路径自动使用新仓库名的小写形式，同时需要修改部署配置的 `APP_IMAGE`。手动在其他分支运行只执行测试，不发布镜像。

GHCR 包首次发布后可能为私有。如果保持私有，在部署机器上先执行 `docker login ghcr.io -u rehee`，在交互提示中输入具有 `read:packages` 权限的 GitHub token；不要把 token 放进脚本、命令参数或 Git。也可在包设置中主动调整可见性。首次 Actions 发布成功前无法拉取该项目镜像。相关官方说明：[GitHub 镜像发布](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)、[GHCR 认证与可见性](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)。

根目录提供三个标准 PowerShell `.ps1` 脚本，可从任意目录调用，脚本会自动定位项目目录。在 **PowerShell 中进入项目根目录**后，按下面方式执行：

```powershell
# 重新编译网站并启动；会等待网站、数据库健康检查。
.\up.ps1

# 从 GHCR 拉取现成镜像并启动，完全跳过源码编译。
.\up_image.ps1

# 停止并移除网站、数据库和 Tunnel 容器；保留全部数据卷。
.\down.ps1
```

本地编译使用 `compose.yaml` 加 `compose.build.yaml`；拉取镜像只使用 `compose.yaml`。两种模式的 Compose 项目和卷名相同，可以切换而不丢失库存。先在 `.env` 配置密码；`APP_IMAGE` 可设置为 `ghcr.io/rehee/simplewh:latest` 或特定 SHA 标签。不设置时默认为 `ghcr.io/rehee/simplewh:latest`。

需要一并启动 Cloudflare Tunnel 时，为两个启动脚本添加 `-Tunnel`：

```powershell
.\up_image.ps1 -Tunnel
# 或将 up_image.ps1 替换成 up.ps1 来本地编译。
```

若 Docker 没有启动、镜像拉取失败或健康检查未通过，脚本会报告错误；已有服务不会在构建或拉取前被主动停止。使用 Docker Compose v2，支持 `--wait` 与 `--wait-timeout`。运行脚本不会更改 GHCR 可见性或替你登录 GitHub。

`.env`、照片、数据库和测试运行文件均不进入 Git 或镜像。已有草稿的 SQLite `data/warehouse.db` 不会被读取、删除或自动迁移；当前实现使用全新 PostgreSQL 库。

## Cloudflare Zero Trust 公网访问

需要自己的 Cloudflare 账号和托管在 Cloudflare 上的域名。

1. 在 Cloudflare 的 Zero Trust / Cloudflare One 控制台创建 Cloudflare Tunnel，选择 Docker 连接器，取出该 Tunnel 的 token，写入 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN`。
2. 给隧道添加 Published application route：主机名例如 `inventory.example.com`；服务类型 **HTTP**，服务地址 **`app:8000`**。`cloudflared` 与网站处于同一 Compose 网络，容器内不能使用 `localhost:8000` 指向另一个容器。
3. 在 Access → Applications 新建 Self-hosted 应用，绑定同一域名；配置允许访问的家庭成员邮箱或你的身份提供商。避免使用允许所有人的策略。Cloudflare Access 与本网站登录是两层独立认证，不会自动创建网站账号。
4. 将 `COOKIE_SECURE=true`，启动：

   ```powershell
   docker compose -f compose.yaml -f compose.build.yaml --profile tunnel up -d --build --wait
   docker compose logs --tail 100 cloudflared
   ```

5. 使用 `https://inventory.example.com`，完成 Cloudflare Access 验证后再登录家庭库存账号。将该域名的 `/api/*` 与 `/photos/*` 设置为绕过缓存；网站也给认证 API 和照片返回 `Cache-Control: no-store`。

Tunnel 使用出站连接，路由器无需映射端口，PostgreSQL 无公网路由。没有配置 token、域名和 Access 策略前，项目不会提供公网地址。启动 `tunnel` profile 后只通过 HTTPS 登录；本地 HTTP 无法传送 Secure 登录 Cookie。

官方说明：[创建 Tunnel](https://developers.cloudflare.com/tunnel/get-started/)、[发布自托管应用并配置 Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)。

## 备份和恢复

在 Linux/macOS 上，可停止网站写入后同时备份数据库与照片。以下命令也可从 Windows 的 WSL 中执行，但必须连接到同一个 Docker Engine：

```sh
mkdir -p backups
docker compose stop app cloudflared
docker compose exec -T db pg_dump -U warehouse -d warehouse -Fc > backups/warehouse.dump
docker compose run --rm --no-deps --user root --entrypoint tar app -czf - -C /data photos > backups/photos.tar.gz
docker compose start app cloudflared
```

备份包括账号密码哈希、库存、标签、会话和操作历史，应妥善保管。Windows PowerShell 5 的 `>` 可能损坏二进制输出；使用上述 Unix shell 命令，或 PowerShell 7.4+。没有任何照片时，可跳过照片归档。

恢复到**已初始化的专用空目标库**，先停写入：

```sh
docker compose stop app cloudflared
docker compose exec -T db pg_restore -U warehouse -d warehouse --clean --if-exists --no-owner < backups/warehouse.dump
docker compose run --rm --no-deps --user root --entrypoint tar app -xzf - -C /data < backups/photos.tar.gz
docker compose run --rm --no-deps --user root --entrypoint chown app -R 10001:10001 /data
docker compose exec -T db psql -U warehouse -d warehouse -c 'DELETE FROM sessions;'
docker compose start app cloudflared
```

恢复将替换目标库存记录。不要对正在使用的数据库执行恢复命令。需要核对备份日期及照片与数据库的一致性。

## 开发和测试

```powershell
python -m pip install -r requirements.txt pytest
$env:TEST_DATABASE_URL='postgresql://用户名:密码@127.0.0.1:5432/专用测试库'
python -m pytest -q
node --check static/app.js
docker compose config --quiet
docker compose -f compose.yaml -f compose.build.yaml config --quiet
pwsh -NoProfile -File tests/test_deployment.ps1
```

集成测试使用真实 PostgreSQL，每个测试创建随机独立 schema 并在结束后删除，需要测试库的 schema 创建权限；请只指向专用测试数据库。未指定 `TEST_DATABASE_URL` 时测试会跳过。覆盖权限、CSRF、照片校验、默认初始化、类型限制、循环嵌套、容器转移、标签持久化、数量校验及回滚、百分比包装、清除、会话撤销和并发出库。

本机开发预览可设置 `DATABASE_URL`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`、`COOKIE_SECURE=false` 后运行 `python app.py`。正式容器使用 Gunicorn；开发服务器不应提供公网服务。

### 本次运行状态

2026-10-10：真实 PostgreSQL 集成测试 29 项全部通过（含旧库补齐中3的升级测试），Python/JavaScript 语法及 Compose 配置校验通过。浏览器验证了照片入库、标签、出库、部分转移、箱子创建、容器转移和容器查询；390px 手机布局无横向溢出。

本地 Compose 网站与 PostgreSQL 容器现已启动并通过健康检查，网站访问地址为 <http://127.0.0.1:6001>。Cloudflare 公网连接仍需完成配置。为验证页面，额外启动了仅绑定本机的临时 PostgreSQL 和开发服务器：<http://127.0.0.1:8001>。预览使用独立 `preview` schema，包含明确标记的测试记录；账号 `preview`，密码 `Preview-warehouse2026`。此账号不属于正式容器库。正式主账号的首次初始化配置保存在被 Git 忽略的 `.env`。

预览文件位于 `.local-test/`，不进入代码和镜像。预览服务器命令为 `python .local-test/preview.py`；停止该进程后，可以停止临时 PostgreSQL：

```powershell
& .\.local-test\pgsql\bin\pg_ctl.exe -D .local-test/pgdata -w stop
```

库存数量和容器变更在数据库事务内执行。家庭规模下对写请求使用 PostgreSQL 事务 advisory lock，防止多人同时出库导致负库存或并发移动导致循环嵌套。照片上传会移除 EXIF 并转为 JPEG；浏览器需允许拍照权限，也可从相册选图。HEIC 请先转为 JPEG/PNG/WebP。未使用的已上传照片暂时保留，不自动清理。
