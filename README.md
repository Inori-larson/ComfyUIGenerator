# ComfyUI Generator

使用**本地 Ollama 模型**理解自然语言，通过 **ComfyUI API** 生成单图或连续剧情分镜。
M1 桌面界面已可试用；M0 命令行核心保持可用。

- **单图模式**：一句描述 → Ollama 模型生成提示词 → 出 1 张图（可多张变体）
- **连续剧情**：一句剧情 → Ollama 模型分镜（beat + 分块续写）→ 批量出图
- **单图 → 分镜**：把单图结果作为第 1 镜，续写成完整剧情
- **实时预览**：每张图独立显示采样过程中的逐步预览（ComfyUI WebSocket）
- **托管服务**：自动探测/启动/重启本地 ComfyUI，退出时关闭自己启动的实例
- 角色 LoRA、风格 LoRA、身体部位 LoRA、参考图（IPAdapter）、ADetailer 重绘、高清修复、通配符、项目/设置存档
- 默认模板：WAI Illustrious v170 + **仪玄 V2**（0.9）+ 官方推荐参数（1024×1344、30 步、CFG 5、euler_ancestral/normal、高清 1.5× / 20 步 / 0.4、RealESRGAN Anime6B）

## 状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 核心库 + CLI + 单图/分镜/扩展 + 实时预览 + 72 单测 | ✅ |
| M1 | PySide6 界面：模式切换 / 单图提示词 / 分镜编辑 / 实时预览 / 队列 / 画廊 / 设置 | ✅ 第一版 |
| M2 | 项目打开保存、回收站、变体对比、失败重试、单镜改写、镜头锁定 | ✅ 第一版 |
| M3 | 安装器、双语、CI 发布 | 计划 |

设计规格见 [docs/spec.md](docs/spec.md)。

## 环境要求

- Windows 10/11（当前只在 Windows 上验证）
- NVIDIA GPU（SDXL 建议 12GB+；生成分镜的本地 LLM 会短暂占用显存，14B 约 9GB）
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)（验证版本 0.42.0），通过 HTTP API 调用，**不打包、不修改**
- [Ollama](https://ollama.com) + 任意指令/对话模型（默认使用已安装的第一个，或在界面中选择；示例：`ollama pull <模型名>`）
- ComfyUI 自定义节点（按需）：Impact Pack / Impact Subpack（ADetailer）、ComfyUI_IPAdapter_plus（参考图）

模型、LoRA、自定义节点由用户自行安装，本项目不附带任何模型。

## 安装（开发版）

```powershell
git clone https://github.com/Inori-larson/ComfyUIGenerator.git
cd ComfyUIGenerator
python -m venv .venv
.\.venv\Scripts\pip install -e ".[ui,dev]"
```

首次运行会在 `%APPDATA%\ComfyUIGenerator\config.json` 生成配置，并尝试探测
ComfyUI 的 `main.py`、Python 解释器与 base 目录。若探测失败，请手动填写。

```powershell
cui doctor
```

`doctor` 会显示 ComfyUI/Ollama 连接状态、模型/LoRA/重绘检测器清单、缺失节点。

## 图形界面

```powershell
cui-ui
# 或
python -m comfyui_generator.ui
```

- 顶部切换 **单图 / 连续剧情**，并显示 ComfyUI / Ollama 连接状态
- 左侧：单图为“描述 → 生成提示词 → 生成图片”；剧情为“剧情 → 生成分镜 → 表格编辑 → 生成”
- 中间：实时预览 + 阶段/步数/seed；队列行带实时缩略图（每个变体独立）
  （预览是 latent 近似图，偏糊属正常；成品以最终输出为准）
- 每次新的自然语言任务会自动创建 `output/anime_story/task_任务编号/` 文件夹保存本轮图片；同一任务继续抽卡沿用同一目录
- 右侧：模型 / 角色 / 风格 / 身体 / 画面 / 高清 / 重绘 / 提示词 / 参考图，全部可调
- 角色 LoRA、风格 LoRA、身体部位 LoRA 分页管理；风格和身体 LoRA 不影响角色标签，勾选后都会自动带入自身触发词
- 设置 → LoRA 数据源：可分别指定角色 / 风格 / 身体 LoRA 目录并递归扫描；留空则使用 ComfyUI 的 LoRA 列表并按文件名分类
- 底部：队列、日志、画廊（双击打开图片）
- 所有下拉项（Ollama 模型 / 底模 / 采样器 / 调度器 / 分辨率 / 构图 / 放大模型等）都支持输入关键字搜索；模型与底模自动扫描，也可直接输入列表外名称
- 设置里可通过「浏览」选择 Checkpoint / 放大模型目录；角色 / 风格 / 身体 LoRA 目录同样用浏览选择。Ollama、采样器、调度器由服务自动读取，也可在下拉框直接输入
- 鼠标点中下拉即展开完整列表，已选内容自动全选，直接输入就过滤，不需要先按删除键
- 设置中的「默认模型」也是扫描后的下拉，留空 = 自动使用第一个可用模型
- 右侧工具标签按宽度自动换行，不会出现左右滚动箭头
- 重绘列表来自 `models/ultralytics` 动态扫描，支持 `.pt`、`.onnx`、`.engine` 等检测模型；LoRA/embedding 类型的 `.safetensors` 会自动排除，避免生成失败
- 勾选角色 LoRA：只生成「参考标签」（safetensors 全部 tag，可搜索、勾选加入）；「激活标签」默认空，只由用户手动选择或「让模型挑选」写入
- 「让模型挑选」：以用户输入的自然语言/剧情为主要依据，从参考标签中挑选（最多 100 个，只允许参考列表内的 tag），不做内容过滤，并显示标签数与估算 tokens
- 自然语言转提示词（单图/分镜/单镜改写）会把**完整参考标签表**交给模型；勾选角色 LoRA 时，角色外观/服装/身份标签必须从参考表原样选择，场景/动作/表情等非角色标签再按描述补充。每个 prompt 最多 100 个标签并自动去重
- 单图/分镜、激活标签、工具页提示词只显示中文，可直接删改；手动输入英文会自动翻译为中文显示，出图时由本地 Ollama 模型映射回英文 Booru 标签，ComfyUI 始终使用英文。翻译结果会缓存
- 没有内置元数据时，可按设置用模型 ID 访问 `civitai.red` 查询作者推荐的触发词（API 优先，失败再解析模型页面；可在设置关闭或改地址）
- 设置：路径、端口、预览方式、默认模板；保存后可一键重启 ComfyUI
- 关闭应用时会关闭由它启动的 ComfyUI（可在设置中改为保留）
- 项目管理：新建 / 打开 / 保存（Ctrl+S），渲染时自动保存
- 回收站：画廊右键移入，工具菜单可还原 / 永久删除 / 清空
- 变体对比：队列右键或工具菜单，取消勾选即丢弃并移入回收站
- 失败重试：队列右键「同 seed / 换 seed」；单镜改写：选中分镜后输入要求
- 抽卡：种子模式为「递增」时，每次点生成图片都会自动换下一个种子并重新调用 ComfyUI；「固定」用于复现
- 镜头锁定：分镜表第一列勾选，重新生成分镜时保留该镜
- 分镜表支持一键全选、删除选中、删除全部，以及上下移动

## 使用

### 单图

```powershell
cui image "晴天，仪玄在公园长椅上吃冰淇淋，微笑看镜头"
cui image "..." --no-hires --variants 2 --save-previews data\previews
cui image "..." --plan-only            # 只生成提示词和项目 JSON
```

### 连续剧情

```powershell
cui story "晴天，少女和猫在天台晒太阳" --shots 6
cui story "..." --shots 8 --detailers face,hand --variants 2
```

### 单图 → 分镜

```powershell
# 生成单图项目后直接扩展
cui image "..." --expand 4

# 或对已有单图项目扩展
cui expand "%APPDATA%\ComfyUIGenerator\projects\<id>.json" --shots 5
```

### 重跑已有项目

```powershell
cui run "%APPDATA%\ComfyUIGenerator\projects\<id>.json" --shots 01,03 --variants 2
```

出图保存在 ComfyUI 的 output 目录，默认形如：
`output\anime_story\<name>\01_<shot>_00001_.png`

## 工作原理

```
自然语言
   │  Ollama /api/chat (JSON Schema)
   ▼
单图提示词 / 分镜列表（Prompt 层）
   │  参数、LoRA、参考图、重绘
   ▼
ComfyUI /prompt（API 格式工作流）
   │  WebSocket：executing / progress / 二进制预览帧 / executed
   ▼
图片 + 实时预览
```

- 提示词层：Ollama 模型输出结构化 JSON；单图 1 条，剧情 N 条
- 执行层：纯 Python 构建 ComfyUI 工作流（多 LoRA 链、hires、IPAdapter、ADetailer、通配符）
- 进程层：auto 模式探测/启动/重启 ComfyUI，仅管理自己启动的进程
- UI 层（M1）：只订阅 core 事件，不解析协议

## 开发

```powershell
.\.venv\Scripts\python -m pytest -q
cui doctor --restart-comfy   # 以启用实时预览的参数重启 ComfyUI
```

目录：

```
src/comfyui_generator/core/   纯 Python 核心（可复用到 Tauri/Web）
src/comfyui_generator/cli.py  M0 命令行
tests/                        单元测试（预览帧、工作流、分镜、单图、项目）
```

## 路线图

- [x] M0 核心库、CLI、单图/剧情、实时预览
- [ ] M1 PySide6 界面（单图/剧情切换、独立预览卡、队列、画廊）
- [x] M2 项目 / 回收站 / 变体对比 / 失败重试 / 单镜改写 / 镜头锁定
- [ ] M3 安装器、中英双语、GitHub Actions 发布
- [ ] P1 单镜重写、镜头锁定、联系表导出
- [ ] P2 视频/幻灯片、ControlNet（有模型后）、标签补全

## 免责声明

本项目不附带模型、LoRA 或任何生成内容。请遵守模型许可与当地法律，自行承担生成内容的责任。

## License

MIT
