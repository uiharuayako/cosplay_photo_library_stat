# Cosplay Photo Library Stat

一个为大型 Cosplay 图库重构的 Web 应用。

这个版本使用 FastAPI + 服务端渲染前端，替代了早期的 Streamlit 原型，重点提供以下能力：

- 默认使用 SQLite 持久化扫描缓存，也可选用 MySQL
- 全量扫描时实时显示当前目录与累计统计
- 提供完整的摄影师 / 角色排行榜
- 点击表头即可按图片数、套图数、总大小排序
- 按需生成封面缩略图，并持久化缩略图缓存
- 支持实体翻译 CSV 的导出 / 导入流程
- 提供可选 CLI 工具，可在不改动扫描数据结构的前提下导出并机器翻译 CSV
- UI 文案支持多语言，通过挂载到宿主机的 JSON 语言文件驱动

## 期望的图库目录结构

扫描器要求图库目录采用固定层级：

```text
LIBRARY_ROOT/
├── arty huang/
│   ├── arty huang - alicization administrator/
│   │   ├── artyhuang_alicizationadministrator_001.jpg
│   │   └── ...
│   └── arty huang - asuna/
└── alexis lust/
    └── alexis lust - triss merigold, jennefer/
```

规则如下：

- 第一级目录名 = coser 名称
- 第二级目录名必须包含 ` - `
- ` - ` 后面的部分会被解析为角色字段
- 多个角色使用英文逗号 `,` 分隔
- 角色名尾部的数字后缀会被归一化，例如 `nyotengu 2` 会归并为 `nyotengu`

## 架构

### 后端

- `app/` 下的 FastAPI 应用
- 使用 SQLAlchemy 建模缓存套图元数据与扫描状态
- 后台扫描任务负责遍历整个图库
- JSON 翻译文件存放在挂载的数据目录中
- 缩略图缓存同样存放在挂载的数据目录中

### 持久化目录布局

当 `DATA_DIR=/data` 时，应用会写入：

```text
/data/
├── cache/
│   ├── library.sqlite3
│   └── thumbnails/
└── i18n/
    ├── entities/
    │   ├── characters.en.json
    │   ├── characters.ja.json
    │   ├── characters.zh-CN.json
    │   ├── cosers.en.json
    │   ├── cosers.ja.json
    │   └── cosers.zh-CN.json
    └── ui/
        ├── en.json
        ├── ja.json
        └── zh-CN.json
```

建议把整个 `/data` 目录挂载到宿主机，这样即使容器重建，扫描缓存、缩略图和 i18n 文件也不会丢失。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export LIBRARY_ROOT=/absolute/path/to/cosplay_photo_library_v3
export DATA_DIR=$(pwd)/data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

启动后访问 [http://localhost:8080](http://localhost:8080)。

## Docker 部署

### SQLite 模式（默认推荐）

1. 将 `docker-compose.yml.example` 复制为 `docker-compose.yml`
2. 按实际环境修改宿主机路径
3. 启动容器

```bash
docker compose up -d --build
```

示例挂载：

- 宿主机 `./app_data` -> 容器 `/data`
- 宿主机 `/path/to/cosplay_photo_library_v3` -> 容器 `/library:ro`

### 可选 MySQL 模式

如果你希望把元数据存放到 MySQL，而不是 SQLite，可以将 `DATABASE_URL` 替换为下面这种格式：

```text
mysql+pymysql://<username>:<password>@<mysql-host>:3306/<database>?charset=utf8mb4
```

注意：

- 图库目录仍然必须挂载，因为封面和扫描都需要直接读取原始文件
- `/data` 卷仍然必须保留，因为缩略图和 i18n JSON 仍然是文件存储
- 对于单实例部署，SQLite 更简单，也是默认选项
- 不要把真实账号、密码、内网 IP 或主机名提交到仓库

## 功能说明

### 实时扫描进度

执行全量扫描时，界面会显示：

- 当前 coser 目录
- 当前套图目录
- 已处理 coser 数 / 总 coser 数
- 累计套图数、图片数与总存储体积

扫描结果会在整次遍历成功完成后统一提交，因此如果扫描中途失败，不会覆盖上一次成功的缓存。

### 排行榜与排序

所有排行榜默认按图片数量降序排列。

用户可以点击任意排行榜表头中的指标列，在以下维度之间切换排序：

- 图片数
- 套图数
- 文件总大小

coser 面板和角色面板都会跟随当前排序指标。

### 封面缩略图

应用会为每个套图记录一条封面路径，并按需把 JPEG 缩略图生成到 `/data/cache/thumbnails`。

### i18n 流程

应用支持 UI 多语言和实体名称多语言。

- UI 文案文件位于 `/data/i18n/ui`
- coser 翻译文件位于 `/data/i18n/entities/cosers.<locale>.json`
- 角色翻译文件位于 `/data/i18n/entities/characters.<locale>.json`
- 可在 UI 中导出 CSV，供 AI 本地化使用
- 可将翻译后的 CSV 再导入应用

导出的 CSV 包含以下字段：

- `key`
- `raw_name`
- `translation`
- `set_count`
- `image_count`
- `total_size`

### CLI 导出与翻译辅助工具

如果应用已经完成过扫描，而你只想生成翻译产物，就可以跳过重新扫描，直接基于缓存数据库和 JSON 翻译文件操作：

```bash
uv run python scripts/export_translate_entities.py \
  --locale zh-CN \
  --entity both \
  --coser-strategy identity \
  --character-strategy google
```

默认策略比较保守：

- coser 名称默认使用 `identity`，避免艺名被机器错误翻译
- 角色名称默认使用 Google 机器翻译
- 脚本会把导出后的 CSV 和翻译结果写入 `data/i18n/exports/`
- 除非指定 `--skip-import`，否则脚本还会同步更新现有 JSON 翻译文件

这个流程只会读取现有缓存并写入 i18n 文件，不会改动扫描表，也不需要重新做一次全量扫描。

## API 概览

- `GET /api/config`
- `GET /api/dashboard?locale=zh-CN&sort=images`
- `GET /api/cosers/{key}?locale=zh-CN&sort=images`
- `GET /api/characters/{key}?locale=zh-CN&sort=images`
- `GET /api/scan/status`
- `POST /api/scan/start`
- `GET /api/sets/{id}/cover`
- `GET /api/i18n/export?entity=cosers&locale=zh-CN`
- `POST /api/i18n/import?entity=cosers&locale=zh-CN`

## 重要运维说明

- 扫描器只会读取每个二级套图目录中的直接图片文件
- 原始图片文件不会被修改
- 推荐将图库目录以只读方式挂载
- 这个仓库不包含你的 NAS 数据，必须通过挂载卷注入容器
- 如果部署环境无法访问图库挂载路径或 MySQL 主机，应用虽然能启动，但扫描会失败，直到连通性恢复
