# Cosplay Photo Library Stat

一个面向大型 Cosplay 图库的 FastAPI 仪表盘，用来扫描本地图库、缓存统计结果、展示排行与封面，并维护多语言翻译数据。

## 项目结构

```text
.
├── .github/workflows/        # CI / 镜像构建
├── app/                      # FastAPI 应用、模板、静态资源、默认 UI 语言包
├── deploy/compose/           # Docker Compose 示例
├── scripts/                  # 开发辅助脚本
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── uv.lock
```

运行时数据默认写入 `data/`，属于本地缓存与业务数据，不纳入版本管理：

```text
data/
├── cache/
│   ├── library.sqlite3
│   └── thumbnails/
└── i18n/
    ├── entities/
    └── ui/
```

## 功能概览

- 扫描两级目录结构的 Cosplay 图库并缓存统计数据
- 提供 coser / 角色排行榜与封面浏览
- 支持 SQLite，必要时可切换 MySQL
- 支持 UI 文案与实体名称的多语言 JSON / CSV 流程
- 提供翻译导出脚本，基于缓存结果补齐本地化数据
- 支持 Docker 部署，并通过 GitHub Actions 自动构建容器镜像

## 图库目录要求

扫描器假设图库采用如下结构：

```text
LIBRARY_ROOT/
├── arty huang/
│   ├── arty huang - alicization administrator/
│   │   ├── artyhuang_alicizationadministrator_001.jpg
│   │   └── ...
│   └── arty huang - asuna/
└── alexis lust/
    └── alexis lust - triss merigold, yennefer/
```

约定如下：

- 一级目录名表示 coser 名称
- 二级目录名必须包含 ` - `
- ` - ` 之后的部分会被解析为角色列表
- 多角色使用英文逗号 `,` 分隔
- 角色名末尾的数字后缀会被归一化，例如 `nyotengu 2` 会归并到 `nyotengu`

## 本地开发

1. 创建虚拟环境并安装依赖
2. 指定图库根目录与数据目录
3. 启动 FastAPI

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export LIBRARY_ROOT=/absolute/path/to/cosplay_photo_library_v3
export DATA_DIR=$(pwd)/data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

访问 [http://localhost:8080](http://localhost:8080)。

## Docker 部署

仓库提供两个 Compose 示例：

- `deploy/compose/docker-compose.example.yml`：通用 Docker Compose 示例
- `deploy/compose/docker-compose.unraid.yml`：Unraid 场景示例

推荐先复制到仓库根目录再使用，这样相对路径更直观：

```bash
cp deploy/compose/docker-compose.example.yml docker-compose.yml
# 按实际机器修改挂载路径与环境变量
docker compose up -d --build
```

默认推荐 SQLite：

- 宿主机应用数据目录挂载到容器 `/data`
- 图库目录只读挂载到容器 `/library:ro`
- 默认数据库路径为 `sqlite:////data/cache/library.sqlite3`

如需改用 MySQL，可将 `DATABASE_URL` 改为：

```text
mysql+pymysql://<username>:<password>@<mysql-host>:3306/<database>?charset=utf8mb4
```

## 翻译导出脚本

如果已经完成扫描，可以直接基于缓存数据库导出并补齐翻译数据，而不必重新扫描图库：

```bash
uv run python scripts/export_translate_entities.py \
  --locale zh-CN \
  --entity both \
  --preserve-existing
```

说明：

- 导出结果默认写入 `data/i18n/exports/`
- 研究缓存默认写入 `data/i18n/research_cache/`
- 除非显式传入 `--skip-import`，脚本会同步更新实体翻译 JSON
- 翻译策略由脚本内部研究逻辑自动判断，不需要额外传 `--coser-strategy` 或 `--character-strategy`

## GitHub Actions 镜像构建

仓库内置 `/.github/workflows/docker-image.yml`，在以下场景自动构建并推送镜像：

- push 到 `master`
- 创建以 `v*` 命名的 tag
- 手动触发 `workflow_dispatch`

默认推送到 GitHub Container Registry：

- 镜像名：`ghcr.io/<owner>/cosplay-photo-library-stat`
- 登录方式：使用 GitHub Actions 自带的 `GITHUB_TOKEN`
- 不需要额外的 Docker Hub 凭据

如果仓库或组织禁用了 `packages: write` 权限，工作流会因无法推送 GHCR 而失败，这时需要在 GitHub 仓库设置中开启对应权限。

## 常用 API

- `GET /api/config`
- `GET /api/dashboard?locale=zh-CN&sort=images`
- `GET /api/cosers/{key}?locale=zh-CN&sort=images`
- `GET /api/characters/{key}?locale=zh-CN&sort=images`
- `GET /api/scan/status`
- `POST /api/scan/start`
- `GET /api/sets/{id}/cover`
- `GET /api/i18n/export?entity=cosers&locale=zh-CN`
- `POST /api/i18n/import?entity=cosers&locale=zh-CN`

## 维护建议

- 图库目录建议始终以只读方式挂载
- 不要把真实账号、密码、内网地址或图库数据提交到仓库
- `data/` 属于运行时数据目录，建议完整挂载到宿主机持久化
