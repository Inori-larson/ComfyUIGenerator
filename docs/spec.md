# ComfyUI Generator · 设计规格（冻结版）

> 本地 Ollama 模型理解自然语言 → 生成提示词/连续分镜 → 通过 ComfyUI API 出图。
> 双模式：**单图** 与 **连续剧情**。Windows 桌面应用（PySide6 起步，core 可复用到 Tauri/Web）。

---

## 1. 产品定义

| 模式 | 输入 | 模型的作用 | 输出 |
|---|---|---|---|
| 单图 | 一句自然语言 + 角色/LoRA/参考图 | 生成 1 条可编辑的 Danbooru 提示词 | 1 镜 × N 变体 |
| 连续剧情 | 一句剧情 + 镜数 | beat 大纲 → 分块生成 N 镜 | N 镜 × 每镜 N 变体 |

两种模式共用：模型/LoRA/角色标签、参考图（IPAdapter）、采样参数、高清修复、ADetailer、通配符、预览、队列、画廊、项目存档。

跨模式：
- 单图 → 扩写为 N 镜（第 1 镜保持原提示词）
- 分镜某镜 → 单独重画/导出单图项目
- 单图成品 → 设为角色参考图
- 锁定分镜后重写其余镜头（P1）

---

## 2. 已确认的决策

| 项 | 决定 |
|---|---|
| UI 技术 | 方案 A：PySide6 + 纯 Python core；后续可换 Tauri/Web 壳 |
| 实时预览 | P0，每张图独立预览卡；ComfyUI 需 `--preview-method latent2rgb --preview-size 512` |
| ComfyUI 管理 | auto：探测 → 有则 attach，无则启动；仅关闭自己启动的进程 |
| 退出行为 | 由应用启动的 ComfyUI 一起关闭；用户已有实例不动 |
| 删除图片 | 移入 `%APPDATA%\ComfyUIGenerator\projects\<id>\trash\`，可恢复 |
| 数据目录 | `%APPDATA%\ComfyUIGenerator`（可用 `COMFYUI_GENERATOR_HOME` 覆盖） |
| 语言 | 中文默认，可切英文（v1 切换后重启生效） |
| 单图输入 | 默认必须经 Ollama 模型；生成后允许手动编辑提示词 |
| 单图→分镜 | P0 |
| 单镜重写 / 镜头锁定 | P1 |
| 下拉选择 | 所有下拉项统一为可搜索组件；Ollama 模型与 ComfyUI 资源自动扫描，不手填名称 |

---

## 3. 架构

```
src/comfyui_generator/
├─ core/                 # 纯 Python，无 UI
│  ├─ config.py          # 配置、路径探测、AppData 目录
│  ├─ comfy.py           # HTTP /prompt /history /view /upload /object_info + WebSocket
│  ├─ preview.py         # 二进制预览帧解析（事件 1/3/4）
│  ├─ ollama.py          # /api/tags /api/chat(schema) /api/ps /unload
│  ├─ storyboard.py      # 多镜：beat、分块、续写（initial_shots）
│  ├─ single.py          # 单图提示词（1 个 prompt + negative）
│  ├─ workflow.py        # 多 LoRA、hires、IPAdapter、ADetailer、通配符
│  ├─ jobs.py            # Task、队列、预览路由、取消/重试
│  ├─ services.py        # ComfyUI/Ollama 进程托管、健康检查、重启
│  ├─ assets.py          # /object_info 资源列表（兼容 0.4x COMBO 格式）
│  ├─ detailers.py       # 脸部/眼睛/嘴/表情/手 预设与回退
│  ├─ project.py         # 项目、profile、trash
│  └─ config.py
├─ cli.py                # CLI（story / image / expand / run / doctor）
├─ ui/                   # PySide6（M1）
│  ├─ main_window.py     # 三栏 + 底部队列/日志/画廊
│  ├─ workers.py         # 连接、LLM、渲染线程
│  ├─ settings_dialog.py
│  └─ app.py
└─ presets/              # 内置模板（仪玄 V1 / V2，默认 V2，官方推荐参数）
```

UI（M1）只订阅 core 事件：任务更新、预览帧、完成、错误；不直接解析 WebSocket。
队列中每个任务（每个变体）保存独立预览帧并显示缩略图，中间大图可跟随或手动选择。

### M1 界面结构

```
顶部：单图 / 连续剧情 | ComfyUI、Ollama 状态 | 重新连接 / 重启 / 设置 / 输出目录
左侧：单图（描述→提示词→出图）；剧情（剧情→分镜表→出图）
中间：实时预览 + 阶段/步数/seed + 进度 + 取消
右侧：模型 / 角色 / 风格 / 画面 / 高清 / 重绘 / 提示词 / 参考图
底部：队列（每任务缩略图）/ 日志 / 画廊（双击打开）
```

交互要点：
- 单图“生成图片”时若提示词为空，会先调用 Ollama 模型再自动出图
- 分镜表可编辑镜号/名称/提示词，支持增删、上下移动、只生成选中行
- 单图完成后可“扩写成分镜”，自动切换到剧情模式并保留第 1 镜
- 渲染期间冻结参数面板；取消会中断当前 ComfyUI 任务
- 所有下拉（模型、底模、采样器、调度器、分辨率、构图、放大模型、语言等）均可输入搜索，只能从扫描结果中选择
- 点击下拉即展开完整列表并全选当前文字，直接输入过滤，无需先删除原内容
- 右侧工具标签使用自动换行布局，宽度不够时换到下一行，不使用左右滚动箭头
- 重绘 pass 不写死：从 ComfyUI `/object_info` 或 `models/ultralytics` 动态扫描，所有检测模型都可勾选；支持手动重新扫描
- 勾选角色 LoRA：默认生成少量激活标签（触发词/标题；没有则取前 12 个，不做内容过滤）；safetensors 全部标签进入「参考标签」，可搜索勾选加入
- 「让模型挑选」：从参考列表中按场景需要选择（最多 200 个，强制子集校验），不做内容过滤，显示标签数与估算 tokens
- 自然语言转提示词（单图/分镜/单镜改写）把完整参考表交给模型挑选；每个 prompt 最多 200 个标签并去重，避免整表复读
- 无内置元数据时：可从 LoRA 伴随文件 / 链接中解析模型 ID，访问 `civitai.red`（可配置）查询作者推荐触发词；优先 API，再解析页面 `__NEXT_DATA__` / Trigger Words；设置中可关闭
- 角色 / 风格 LoRA 分页：文件名含 style / screencap / hrf / aesthetic 等自动归入「风格」，风格 LoRA 不参与角色标签
- LoRA 数据源可配置：设置里分别指定角色 / 风格目录（递归扫描 `.safetensors/.pt/.ckpt`）；留空则用 ComfyUI LoRA 列表按文件名分类。自定义目录需在 ComfyUI 的 LoRA 搜索路径内，否则界面会提示未索引

### M2 交互

- 文件菜单：新建 / 打开 / 保存项目（Ctrl+S）；渲染时自动保存
- 画廊右键：移入项目回收站；工具菜单回收站支持还原 / 永久删除 / 清空
- 变体对比：队列右键或工具菜单，取消勾选的变体会移入回收站
- 失败重试：队列右键「同 seed / 换 seed」，只重跑该任务
- 单镜改写：选中分镜 → 输入要求 → 模型只重写该镜提示词
- 镜头锁定：分镜表第一列；重新生成分镜时按位置保留锁定行

---

## 4. 预览协议（已核实 ComfyUI 0.42）

```
二进制帧 = [4B 大端事件类型][载荷]

事件 1 PREVIEW_IMAGE:
    载荷 = [4B 图片格式 1=JPEG/2=PNG][图片字节]      # 无 prompt_id
事件 3 TEXT:
    载荷 = UTF-8 JSON（executing/progress/executed/execution_error）
事件 4 PREVIEW_IMAGE_WITH_METADATA:
    载荷 = [4B JSON 长度][JSON 元数据][图片字节]
    元数据含 prompt_id / node_id / image_type
```

路由规则：
- `executing` 维护当前 `prompt_id` 与阶段（节点 9=base，13=hires，60–63=detail）
- `progress` 更新步数
- 预览帧按 `prompt_id` 归属 Task，10 fps 节流
- `executed` → `/view` 拉最终图，立即进入画廊

---

## 5. 任务模型

```
Project (mode=single|story)
 └─ Shot (id, name, prompt, negative?)
     └─ Task (variant, seed)   # 队列单位 = 一张图
```

Task 状态：`pending → submitted → running(stage) → done | failed | canceled`

- 队列串行（显存安全）
- 取消 = interrupt + 清空排队
- 单图重试：同 seed / 换 seed
- 种子模式：递增 / 固定 / 随机

---

## 6. 配置（`%APPDATA%\ComfyUIGenerator\config.json`）

关键字段：
```jsonc
{
  "comfy": {
    "mode": "auto", "host": "127.0.0.1", "port": 8000,
    "python": "...\\.venv\\Scripts\\python.exe",
    "main_py": "...\\ComfyUI\\main.py",
    "base_dir": "H:\\ComfyUIData",
    "preview_method": "latent2rgb", "preview_size": 512,
    "auto_start": true, "keep_running_on_exit": false
  },
  "ollama": { "host": "127.0.0.1", "port": 11434, "exe": "...", "default_model": "..." },
  "generation": { "template": "...", "variants": 1 },
  "lora": { "character_dir": "", "style_dir": "", "online_lookup": true, "civitai_base": "https://civitai.red" },
  "ui": { "language": "zh-CN" }
}
```

---

## 7. CLI（M0 已实现）

```powershell
cui doctor
cui image "晴天，仪玄在公园长椅上吃冰淇淋" --plan-only
cui image "..." --no-hires --variants 2 --save-previews data\previews
cui image "..." --expand 4          # 单图 → 直接扩成 4 镜并渲染
cui story "晴天，少女和猫在天台晒太阳" --shots 6
cui expand <single-project.json> --shots 5
cui run <project.json> --shots 02,03 --variants 2
```

所有命令支持 LoRA、参考图、重绘、参数覆盖；`--plan-only` 只写 JSON。

---

## 8. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | core 包、进程托管、预览解析、CLI、单图/分镜/扩展、72 单测 | ✅ 完成 |
| M1 | PySide6 UI：模式切换、分镜编辑、独立预览缩略图、参数面板、画廊、队列 | ✅ 第一版 |
| M2 | 项目打开保存、回收站、变体对比、失败重试、单镜改写、镜头锁定 | ✅ 第一版 |
| M3 | 首次启动向导、中英双语、CI 打包、安装器、README/截图 | 3–5 天 |

验收（M1）：
1. 不改 JSON 即可完成单图与 6 镜剧情；
2. 生成时每张图独立逐步预览，可取消；
3. 任意一镜失败可单张重试；
4. 关闭重开后项目与参数保留；
5. 应用启动/关闭时正确托管 ComfyUI。

---

## 9. 非目标（v1）

- 不打包 ComfyUI、不安装节点、不下载模型
- 不做远程鉴权/多用户
- 不做画布局部重绘、ControlNet（无模型）、Regional Condition
- 不做视频/TTS（P2 参考 vedGen/Pixelle-Video）
- 不做标签自动补全（P2）

---

## 10. 参考项目

- [SAA](https://github.com/mirabarukaso/character_select_stand_alone_app)：LoRA 槽位、ADetailer、profile、预览
- [vedGen](https://github.com/HarisUmer/vedGen)：分层库 API、plan-only、版本化 workflow、显存降级
- [AI Comic Factory](https://github.com/jbilcke-hf/ai-comic-factory)：LLM/渲染引擎解耦、分镜中心 UX
- [SwarmUI](https://github.com/mcmonkeyprojects/SwarmUI)：简单/高级参数分层、队列、画廊
- [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video)：中文端到端流水线
- [StabilityMatrix](https://github.com/LykosAI/StabilityMatrix)：安装/路径探测（AGPL，仅参考交互）

---

## 11. 许可

自有代码 MIT。未打包或修改 ComfyUI（GPL-3.0），仅通过 HTTP API 调用；用户自备模型与 LoRA。
