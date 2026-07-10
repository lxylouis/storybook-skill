# storybook-skill

AI 绘本工坊的通用 Agent Skill 版:一句话点子 → 大纲与双语旁白(中/英)→
风格一致的逐页插画 → **自包含 HTML 翻页绘本**(双击即开、中英切换、浏览器
朗读、打印即 PDF)。符合 [Agent Skills](https://agentskills.io) 开放规范,
可在 Claude Code、OpenClaw、Hermes Agent 等任意兼容宿主中使用。
Fork 自 FreeDeepAgents 平台的 storybook 活动,状态机与一致性出图策略
经过实机验证。当前版本吸收了参考活动的结构化资产/cast 机制:先锁角色、
道具和关键元素,再逐页按出场资产注入 prompt,比只靠角色名过滤更稳。

## 安装

skill 即本目录整体(SKILL.md + scripts/ + references/ + assets/)。

| 宿主 | 安装方式 |
|---|---|
| Claude Code | `git clone <repo-url> ~/.claude/skills/storybook-skill`(或放入项目 `.claude/skills/storybook-skill`) |
| OpenClaw | `openclaw skills install <repo-url>`,或解压到 `~/.openclaw/skills/storybook-skill`(全局)/ workspace `skills/storybook-skill` |
| Hermes Agent | 放入其 skills 目录(兼容 agentskills.io 标准;以官方文档为准) |

要求:`python3` ≥ 3.9 在 PATH 上(macOS 自带的 3.9.6 即可)。无三方依赖。

## 图像生成配置(二选一)

1. **宿主自带图像工具**(Hermes 内建、Claude Code/OpenClaw 的 MCP 图像服务
   等):无需任何配置,skill 会优先用它。
2. **兜底脚本**(按你的 key 二选一):OpenAI 兼容服务用 `scripts/gen_image.py`;
   阿里云百炼(DashScope)用 `scripts/gen_image_dashscope.py`(原生
   multimodal-generation 格式,默认 wan2.7-image)。环境变量两者同款:

```bash
export STORYBOOK_IMAGE_API_KEY=sk-...
# 可选(默认 OpenAI / gpt-image-1 / 1024x1536):
export STORYBOOK_IMAGE_BASE_URL=https://api.openai.com/v1
export STORYBOOK_IMAGE_MODEL=gpt-image-1
export STORYBOOK_IMAGE_SIZE=1024x1536
```

### 供应商尺寸对照(竖版约 2:3 优先)

| 供应商 | BASE_URL | MODEL 示例 | 建议 SIZE |
|---|---|---|---|
| OpenAI | https://api.openai.com/v1 | gpt-image-1 | 1024x1536 |
| OpenAI(旧) | https://api.openai.com/v1 | dall-e-3 | 1024x1792 |
| 阿里云百炼 DashScope(用 `gen_image_dashscope.py`) | https://dashscope.aliyuncs.com/api/v1(默认值,可不设) | wan2.7-image / wan2.7-image-pro | 1024x1536(脚本自动转 `1024×1536`;宽高须在 768–2048) |
| 其他 OpenAI 兼容服务(硅基流动、各大模型厂商等) | 以服务商文档为准 | 以服务商文档为准 | 选最接近 2:3 竖版的档位(如 960x1280、832x1216) |

> 1024x1536 不是行业标准,只是 OpenAI 方言的竖版档位;`STORYBOOK_IMAGE_SIZE`
> 按你的供应商支持档位覆盖即可,查看器对任意宽高比自适应。

配置自检:`python3 scripts/storybook.py doctor`

## 用法

对你的 agent 说:「给我做一本绘本,讲小狐狸找月亮的故事,水彩风,给 4 岁孩子」。
流程:大纲+封面 → 你确认 → 自动画完整本 → 得到 `<书目录>/<slug>.html`。
修改:「第 3 页文字改成…」「第 5 页重画」「换成剪纸风」。

手动驱动(不经 agent)也可以:

```bash
python3 scripts/storybook.py init --idea "小狐狸找月亮" --slug fox --dir .
python3 scripts/storybook.py save-outline --file outline.json --dir fox
python3 scripts/storybook.py save-assets --file assets.json --dir fox
python3 scripts/storybook.py save-cast --file cast.json --dir fox
python3 scripts/storybook.py status --dir fox   # 任何时候看下一步
```

> **大图提示**: `finalize` 默认输出 `.zip` 小包,里面是 link-images HTML +
> images/。要单个自包含 HTML 时用 `finalize --inline`;2K 图较多时可能达到
> 几十 MB。返修后用 `export --zip` 重新打包。

## 测试

```bash
/usr/bin/python3 -m unittest discover -s tests -v   # 3.9 兼容底线
python3.13 -m unittest discover -s tests -v          # 现代解释器
```

## 目录结构

```
SKILL.md                 # agent 路由表(宿主自动加载)
scripts/storybook.py     # 状态机 CLI(唯一写 book.json 的入口;含 assets/cast)
scripts/gen_image.py     # OpenAI 兼容出图兜底
assets/viewer.template.html
references/              # workflow / prompts / book-schema
tests/
```

## License

MIT
