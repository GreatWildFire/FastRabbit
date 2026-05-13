# FastRabbit — 短剧剧本与资产生成工具链

本仓库提供从中文短剧剧本出发，自动完成剧本拆解、角色与场景资产、镜头分镜提示与视频生成的完整工具链。支持 **CLI** 和 **Web API + 前端** 两种使用方式。

## 目录说明

| 路径 | 说明 |
|------|------|
| `app/` | FastAPI Web 后端 + 前端静态页面 |
| `app/routers/` | API 路由（项目管理、管线操作） |
| `app/utils/` | 公共工具函数（文本处理、IO） |
| `app/db.py` | SQLite 数据库模块（项目元数据管理） |
| `app/data/` | SQLite 数据库文件（自动生成，不提交） |
| `scripts/` | CLI 脚本（可独立运行，不依赖 Web 服务） |
| `prompts/` | 各步骤 LLM 系统提示词 |
| `API-Reference/` | 外部 API 参考文档（LLM、生图、视频） |
| `test-project/` | 示例短剧项目（已跑通完整管线） |
| `project-template/` | 项目模板参考 |

每个短剧项目的目录结构：

```
project-name/
├── script.txt               # 剧本文本
├── script_analysis/         # 分析结果（集/场/镜头 JSON）
│   ├── project_meta.json
│   └── ep_01/
│       ├── episodes_01.json
│       ├── scenes.json
│       └── scene_S01/
│           ├── shots.json
│           ├── scene_prompt.json
│           └── scene_source.txt
└── assets/                  # 生成资产
    ├── characters/base/     # 角色卡 JSON + 角色图 PNG
    ├── scenes/base/         # 场景图 PNG
    └── shots/{shot_id}/     # 镜头视频 MP4 + 提示词 JSON
```

## 环境准备

- Python 3.10+
- 在仓库根目录创建 `.env`（参考 `.env.example`），配置 API Key：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com

IMAGE_PROVIDER=nano-banana
IMAGE_MODEL=nano-banana-fast
IMAGE_API_KEY=sk-...
IMAGE_BASE_URL=https://grsai.dakka.com.cn/v1/draw/nano-banana

VIDEO_PROVIDER=ark
VIDEO_MODEL=doubao-seedance-2-0-250528
VIDEO_API_KEY=...
VIDEO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

安装依赖：

```bash
pip install -r requirements.txt
```

如需视频生成功能，额外安装 ARK SDK：

```bash
pip install "volcengine-python-sdk[ark]"
```

## Web 服务（推荐）

启动 FastAPI 服务：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：
- `http://localhost:8000` — 前端控制台
- `http://localhost:8000/docs` — Swagger API 文档

### 前端使用流程

1. 点击左侧 `+` 按钮创建新项目（可粘贴剧本文本）
2. 切换到「管线操作」Tab，先点击「加载剧本」→「保存剧本」
3. 按顺序点击步骤 1~8，执行日志实时显示
4. 视频步骤（步骤8）自动轮询进度

### API 端点概览

```
GET    /api/projects                              # 项目列表
POST   /api/projects                              # 创建项目
GET    /api/projects/{name}                       # 项目概览
DELETE /api/projects/{name}                       # 删除项目
POST   /api/projects/{name}/upload-script         # 上传剧本
GET    /api/projects/{name}/script                # 获取剧本
POST   /api/projects/{name}/sync                  # 文件系统 → DB 同步
GET    /api/projects/{name}/episodes              # 集列表
GET    /api/projects/{name}/episodes/{ep}/scenes  # 场景列表
GET    /api/projects/{name}/episodes/{ep}/scenes/{s}/shots  # 镜头列表

POST   /api/projects/{name}/pipeline/analyze-script      # 步骤1：剧本拆解
POST   /api/projects/{name}/pipeline/validate            # 步骤2：结构校验
POST   /api/projects/{name}/pipeline/scene-shots         # 步骤3：场次拆镜头
POST   /api/projects/{name}/pipeline/character-profiles   # 步骤4：角色卡
POST   /api/projects/{name}/pipeline/character-images     # 步骤5：角色图
POST   /api/projects/{name}/pipeline/scene-prompts        # 步骤6：场景提示词
POST   /api/projects/{name}/pipeline/scene-images         # 步骤7：场景图
POST   /api/projects/{name}/pipeline/shot-videos          # 步骤8：视频（异步）
GET    /api/projects/{name}/pipeline/video-status/{id}   # 视频任务轮询
```

## SQLite 数据库

项目元数据存储在 `app/data/fastrabbit.db`（SQLite），包含以下表：

| 表 | 内容 |
|----|------|
| `projects` | 项目名称、剧本、状态、时间戳 |
| `episodes` | 集编号、标题 |
| `scenes` | 场景地点、时间、角色、提示词、图片状态 |
| `shots` | 镜头类型、动作、角色、视频状态 |
| `characters` | 角色姓名、年龄、外貌描述、图片状态 |

管线步骤执行后自动同步到 DB。已有的文件系统项目（如 `test-project/`）首次访问时会自动同步，也可手动调用 `POST /api/projects/{name}/sync`。

## CLI 方式

以下命令在仓库根目录执行，`--project-root` 指向项目目录。

1. **剧本拆解**
   ```bash
   python3 scripts/generate_script_analysis.py --project-root test-project --input 测试剧本.txt
   ```

2. **检查分析结构**
   ```bash
   python3 scripts/check_script_analysis.py --project-root test-project
   ```

3. **场次拆镜头**
   ```bash
   python3 scripts/generate_scene_shots.py --project-root test-project --episode 1
   ```

4. **角色卡**
   ```bash
   python3 scripts/generate_character_profiles.py --project-root test-project --max-characters 4
   ```

5. **角色图**（二次元动漫风格，降低视频侧真人参考图风控风险）
   ```bash
   python3 scripts/generate_character_images.py --project-root test-project
   ```

6. **场景生图提示词**
   ```bash
   python3 scripts/generate_scene_prompts.py --project-root test-project --episode 1
   ```

7. **场景基础图**
   ```bash
   python3 scripts/generate_scene_images.py --project-root test-project --episode 1
   ```
   生图服务偶发超时可用 `--timeout-sec` 加大超时或 `--allow-partial-success` 后补跑失败场次。

8. **镜头视频**（ARK Seedance，需可用模型 ID）
   ```bash
   python3 scripts/list_ark_models.py --keyword seedance
   python3 scripts/generate_shot_videos.py \
     --project-root test-project --episode 1 --scene-id S01 --shot-id S01_SH01 \
     --video-model doubao-seedance-2-0-260128
   ```
   仅生成提示词不调用视频 API：`--dry-run`

## 常用参数速查

- 多数脚本/API 支持：`--project-root` / `--episode` / `--scene-id` / `--shot-id`
- 角色生图筛选：`--character-names "叶凡,夜不语"`
- 视频参考与衔接：`--max-character-refs`、`--disable-last-frame-chain`

## 注意事项

- **火山方舟视频模型**对输入参考图有真人/合规限制；角色与场景图已偏向**动漫风格**以降低拦截概率；若仍报错，可尝试减少或关闭角色参考图。
- 生图、视频接口均为网络调用，超时或限流时需重试或加大超时。
- `project_meta.json` 中的 `total_episodes` 与目录 `ep_XX` 应对齐；`check_script_analysis.py` 和 API `/validate` 会做一致性校验。
- `app/data/` 目录应加入 `.gitignore`，数据库文件不提交。

## 许可证与贡献

使用本工具时请遵守各云服务商 API 使用条款与内容安全规范。
