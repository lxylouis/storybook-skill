---
name: storybook-skill
description: >
  Create illustrated children's picture books from a one-line idea — outline,
  style-consistent per-page illustrations, bilingual (zh/en) narration, and a
  self-contained HTML flipbook with read-aloud. 用于制作儿童绘本/图画书/睡前
  故事书:一句话点子生成大纲、逐页插画与中英双语旁白,导出可分享的翻页 HTML 成品。
compatibility: Requires python3 (>=3.9) on PATH. Network only needed for the
  bundled fallback image generator (scripts/gen_image.py).
metadata:
  version: "0.1.0"
---

# Storybook — AI 绘本工坊(通用 skill)

把用户的一句话故事创意变成 5–12 页的插画绘本:大纲 + 封面经用户确认后,自动逐页
配图,最终交付**自包含 HTML 翻页绘本**(双击即开、中英切换、浏览器朗读、打印即
PDF)。

**一本书 = 一个目录**(`book.json` + `images/` + `<slug>.html`)。状态机、守卫和
校验全部在 `scripts/storybook.py` 里——**所有状态变更必须经它,绝不手改
book.json**。命令出错会返回 `{"error","hint","current_phase"}`(退出码 2):
**读 hint 自纠,不要死磕**。

## 命令速查

```
python3 <skill>/scripts/storybook.py <command> --dir <book-dir>
```

| 命令 | 作用 |
|---|---|
| `status` | 相位/进度/下一步(**每次会话开始、续作、不确定时必先跑**) |
| `init --idea ... [--slug --audience --style --author] --dir <父目录>` | 建书(仅 init 的 --dir 是父目录) |
| `save-outline --file outline.json` | 保存大纲(5-12 页,pages[0]=封面) |
| `amend-outline` | 回到 outlining 重写大纲 |
| `confirm-outline` | 用户确认后进入配图(要求封面已有图) |
| `compose-prompt --page <id> [--characters 名1,名2]` | 拼好该页的完整出图 prompt |
| `save-image --page <id> --file <图片路径>` | 登记生成的图(png/jpg/jpeg/webp) |
| `next` | 游标到下一页;all_done 时提示 finalize |
| `amend-page --page <id> --json '{...}'` | 改某页文字/标题/image_prompt |
| `regenerate --page <id>` | 清图待重出(自动记失败次数) |
| `skip --page <id> [--reason ...]` | 跳过反复失败的页 |
| `finalize` | 校验全书 → delivered → 自动导出 HTML |
| `export [--link-images]` | (重新)导出 HTML;交付前(`awaiting_outline_confirm`/`illustrating`)也可随时跑来**预览**。大图(2K 以上)建议加 `--link-images` 避免单文件几十 MB |
| `doctor` | 环境自检(python/出图配置/模板) |

## 流程总图

```
用户给点子 → init → [创作大纲+双语旁白+bibles] → save-outline
  → 出封面(compose-prompt --page cover → 出图 → save-image --page cover)
  → 给用户看大纲+封面 → 【硬等待用户确认】
  → confirm-outline → 自动整本循环(每页: compose-prompt → 出图 → save-image → next)
  → finalize → 把 HTML 路径交给用户 → 返修(amend-page/regenerate → export)
```

## 出图协议(双轨)

每页出图前**必须**先 `compose-prompt --page <id> --characters <本页出场角色名>`
拿拼好的 prompt(工具自动注入 style/character bible 并截断到 ≤500 字符,**不要
自己拼、不要改动返回的 prompt**)。然后:

1. **轨道 A(优先)**:你的环境里若有图像生成工具(内建能力、MCP 图像服务等),
   用它生成**竖版约 2:3** 的图,落成本地文件。
2. **轨道 B(兜底)**:没有图像工具时,
   `python3 <skill>/scripts/gen_image.py --prompt-file - --out <tmp>.png`
   (stdin 喂 prompt;需要环境变量 `STORYBOOK_IMAGE_API_KEY`,可选
   `_BASE_URL/_MODEL/_SIZE`,OpenAI images 兼容)。**用户的 key 是阿里云百炼
   (DashScope)时改用 `scripts/gen_image_dashscope.py`**(参数与环境变量同款,
   原生 multimodal-generation 格式,默认 wan2.7-image)。`doctor` 可查配置是否
   就绪;两者都没有时如实告诉用户需要配置哪一样,不要假装出图。

两轨殊途同归:`save-image --page <id> --file <生成的图>`。

## 创作节奏(硬规则)

- **大纲与封面必须经用户明确确认**(「确认」「可以」「continue」等)才能
  `confirm-outline`。**绝不在 save-outline 的同一口气里 confirm**。
- 确认后是**自动整本**:逐页 compose → 出图 → save-image → next,**中途不停顿
  等确认**,每页只向用户报一行进度(如「第 3/9 页画好了」)。用户中途喊停或要求
  逐页过,就自然切换成逐页等确认的节奏——无需任何配置。
- 出图失败:`regenerate --page <id>` 记一次失败并清图,然后重试;**同一页失败
  3 次**(看返回的 failed_attempts)就建议用户 `skip`,别无限重试。
- `finalize` 之后把 HTML **绝对路径**给用户:双击打开;浏览器打印 = PDF。
  若文件过大(2K 图较多时可能几十 MB),建议 `export --link-images` 用外部引用替代内嵌。
- 返修:只改文字 → `amend-page` 后直接 `export`(图复用);改了 image_prompt →
  `amend-page` → `regenerate` → 重出图 → `save-image` → `export`;只是图不满意
  → `regenerate` → 重出 → `save-image` → `export`。
- 换画风 = 回炉:`amend-outline` 回 outlining,重写 style_bible 并重新
  save-outline,封面和所有页全部重出(改文不改图、改图才改图)。
- **续作**:任何时候(新会话、断线后)先 `status`——它会告诉你当前相位和下一步。
- 内容安全:prompt 禁止真实人物/名人/品牌 logo/暴力血腥;面向儿童。

## 大纲创作要领(写 outline.json 之前必读)

读 [references/prompts.md](references/prompts.md) —— style_bible /
character_bible 的写法、image_prompt 的「只写场景动作构图、禁画风词角色长相、
≤200 字符」铁律、画面与文字互补原则,全部在那里,**照着写**。
outline.json 的字段形状见 [references/book-schema.md](references/book-schema.md);
完整流程细则与边角案例见 [references/workflow.md](references/workflow.md)。

大纲质量底线(save-outline 会校验,但校验只能拦格式,拦不了平庸):5-12 页含
封面;每页双语旁白要有拟声词、口语节奏、各自地道(不是逐字互译);page_title
中文 2-15 字、串起来能看出故事弧;story_note 写清教育主题。
