# ComfyUI Generator

使用**本地 Ollama 模型**理解自然语言，通过 **ComfyUI API** 生成单图或连续剧情分镜。
M1 桌面界面已可试用；M0 命令行核心保持可用。

- **单图模式**：一句描述 → Ollama 模型生成提示词 → 出 1 张图（可多张变体）
- **连续剧情**：一句剧情 → Ollama 模型分镜（beat + 分块续写）→ 批量出图
- **单图 → 分镜**：把单图结果作为第 1 镜，续写成完整剧情
- **实时预览**：每张图独立显示采样过程中的逐步预览（ComfyUI WebSocket）
- **托管服务**：自动探测/启动/重启本地 ComfyUI，退出时关闭自己启动的实例
- 角色 LoRA、参考图（IPAdapter）、ADetailer 重绘、高清修复、通配符、项目/设置存档
- 默认模板：WAI Illustrious v170 + **仪玄 V2**（0.9）+ 官方推荐参数（1024×1344、30 步、CFG 5、euler_ancestral/normal、高清 1.5× / 20 步 / 0.4、RealESRGAN Anime6B）

## 状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 核心库 + CLI + 单图/分镜/扩展 + 实时预览 + 43 单测 | ✅ |
| M1 | PySide6 界面：模式切换 / 单图提示词 / 分镜编辑 / 实时预览 / 队列 / 画廊 / 设置 | ✅ 第一版 |
| M2 | 完整交互、回收站、变体对比、错误恢复、单镜重写/锁定 | 计划 |
| M3 | 安装器、双语、CI 发布 | 计划 |

设计规格见 [docs/spec.md](docs/spec.md)。

## 环境要求

- Windows 10/11（当前只在 Windows 上验证）
- NVIDIA GPU（SDXL 建议 12GB+；生成分镜的本地 LLM 会短暂占用显存，14B 约 9GB）
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)（验证版本 0.42.0），通过 HTTP API 调用，**不打包、不修改**
- [Ollama](https://ollama.com) + 任意指令/对话模型（默认使用已安装的第一个，或在界面中选择；示例：`ollama pull qwen2.5:14b-instruct`）
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
- 右侧：模型 / 角色 / 画面 / 高清 / 重绘 / 提示词 / 参考图，全部可调
- 底部：队列、日志、画廊（双击打开图片）
- 所有下拉项（Ollama 模型 / 底模 / 采样器 / 调度器 / 分辨率 / 氛围 / 构图 / 放大模型等）都支持输入关键字搜索；模型与底模自动扫描，无需手填
- 鼠标点中下拉即展开完整列表，已选内容自动全选，直接输入就过滤，不需要先按删除键
- 设置中的「默认模型」也是扫描后的下拉，留空 = 自动使用第一个可用模型
- 设置：路径、端口、预览方式、默认模板；保存后可一键重启 ComfyUI
- 关闭应用时会关闭由它启动的 ComfyUI（可在设置中改为保留）

## 使用

### 单图

```powershell
cui image "晴天，仪玄在公园长椅上吃冰淇淋，微笑看镜头"
cui image "..." --no-hires --variants 2 --save-previews data\previews
cui image "..." --plan-only            # 只生成提示词和项目 JSON
```

### 连续剧情

```powershell
cui story "晴天，少女和猫在天台晒太阳" --shots 6 --mood bright
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
- [ ] M2 参考图/重绘/变体对比/回收站/错误恢复
- [ ] M3 安装器、中英双语、GitHub Actions 发布
- [ ] P1 单镜重写、镜头锁定、联系表导出
- [ ] P2 视频/幻灯片、ControlNet（有模型后）、标签补全

## 免责声明

本项目不附带模型、LoRA 或任何生成内容。请遵守模型许可与当地法律，自行承担生成内容的责任。

## License

MIT
