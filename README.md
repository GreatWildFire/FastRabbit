# FastRabbit — 短剧剧本与资产生成工具链

本仓库提供一套**通用脚本**：从剧本文本出发，完成剧本拆解、角色与场景资产、镜头分镜提示与（可选）视频生成。业务数据（每个短剧项目）与代码分离，便于日后封装为后端服务。

## 目录说明

| 路径 | 说明 |
|------|------|
| `scripts/` | 可执行脚本（从仓库根目录运行） |
| `prompts/` | 各步骤 LLM 系统提示词 |
| `API-Reference/` | 外部 API 参考文档（LLM、生图、视频等） |
| `test-project/` | 示例短剧项目目录（可替换为任意项目根） |
| `project-template/` | 项目模板参考 |

每个短剧项目建议包含：

- `script_analysis/`：`project_meta.json`、按集 `ep_XX/`、每场 `scene_SXX/` 下的 `scenes.json`、`shots.json`、`scene_prompt.json` 等
- `assets/characters/base/`：角色卡 JSON 与同名角色图
- `assets/scenes/base/`：场景基础图，命名如 `EP01_S01.png`
- `assets/shots/{shot_id}/`：镜头级 `video_prompt.json`、`asset_plan.json`、生成的 MP4 等

## 环境准备

- Python 3.10+（建议）
- 在仓库根目录创建 `.env`（勿提交真实密钥），示例字段：

```env
DEEPSEEK_API_KEY=...
NANO_BANANA_API_KEY=...
ARK_API_KEY=...
```

依赖安装（按实际用到的能力安装）：

```bash
pip install openai
pip install "volcengine-python-sdk[ark]"
```

## 推荐执行顺序（单项目）

以下命令均在**仓库根目录**执行，`--project-root` 指向短剧项目目录（示例为 `test-project`）。

1. **剧本拆解（集 / 场）**  
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

4. **角色卡（LLM）**  
   ```bash
   python3 scripts/generate_character_profiles.py --project-root test-project --max-characters 4
   ```

5. **角色图（LLM + 生图）**  
   当前提示词约束为**二次元动漫风格**，降低视频侧真人参考图风控风险。  
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
   生图服务偶发超时时可加大 `--timeout-sec` 或使用 `--allow-partial-success` 后补跑失败场次。

8. **镜头视频（ARK Seedance，需可用模型 ID）**  
   先列出当前账号可用模型：  
   ```bash
   python3 scripts/list_ark_models.py --keyword seedance
   ```  
   单镜头试跑示例：  
   ```bash
   python3 scripts/generate_shot_videos.py \
     --project-root test-project \
     --episode 1 \
     --scene-id S01 \
     --shot-id S01_SH01 \
     --video-model doubao-seedance-2-0-260128
   ```  
   仅生成提示词与资产计划、不调用视频 API：  
   ```bash
   python3 scripts/generate_shot_videos.py --project-root test-project --episode 1 --dry-run
   ```

## 常用参数速查

- 多数脚本支持：`--project-root`、`--episode`、`--scene-id`、`--scene-id` / `--shot-id`（视频脚本）
- 角色生图筛选：`--character-names "叶凡,夜不语"`
- 视频参考与衔接：见 `scripts/generate_shot_videos.py` 内 `--max-character-refs`、`--disable-last-frame-chain` 等

## 注意事项

- **火山方舟视频模型**对输入参考图有真人/合规限制；角色与场景图已偏向**动漫风格**以降低拦截概率；若仍报错，可尝试减少或关闭角色参考图再试。
- 生图、视频接口均为网络调用，超时或限流时需重试或拉长 `--timeout-sec`。
- `project_meta.json` 中的 `total_episodes` 与目录 `ep_XX` 应对齐；`check_script_analysis.py` 会做一致性校验。

## 许可证与贡献

视仓库策略而定；使用本工具时请遵守各云服务商 API 使用条款与内容安全规范。
