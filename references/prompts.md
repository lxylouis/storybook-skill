# 一致性 Prompt 拼装规则(防跨页角色漂移的核心杠杆)

每页出图 prompt 由 `compose-prompt` 自动按以下公式拼装,你只负责把各段**素材**
写好存进 book.json(经 save-outline / amend-page):

```
final_prompt = style_bible + "\n" + character_bible(按页过滤) + "\n"
             + page.image_prompt + "\n" + consistency_constraints(固定)
```

升级版公式(有结构化资产时优先):

```
final_prompt = style_bible + "\n" + assets(按 page.cast 重组) + "\n"
             + page.image_prompt + "\n" + consistency_constraints(固定)
```

`compose-prompt` 自动选择:页面有 `cast` 且 book.json 有 `assets` 时用 assets;
否则回退到 `character_bible` + `--characters` 名字过滤。

## 1. style_bible(全局画风锚,≤100 字符进 prompt)

描述媒介、配色、线条风格、光影、情绪氛围。示例:

```
Soft watercolor on textured cold-press paper. Warm earthy palette: burnt
sienna, ochre, olive green, cream. Loose, flowing brushstrokes with soft
edges. Gentle diffused moonlight. Dreamy, calm, storybook mood.
```

## 2. character_bible(角色定妆锚,≤120 字符进 prompt)

**每个角色一行(或分号分隔),以「角色名:」开头**——`compose-prompt` 按名字检索
条目。每个角色要有「表」(外表与第一印象)和「里」(真实内心或隐藏特质)两层,
这种"可被误解的特质"是故事反转的核心引擎;外貌部分写可见细节(供画图),性格
/弧线可短。示例:

```
Little Fox: young red fox kit, bright reddish-orange fur, white chest and
muzzle, large round amber eyes, small pointed ears, curious gentle expression,
small stature — about half the height of a lantern post.
```

调 `compose-prompt` 时把**本页出场角色的名字**传给 `--characters`(逗号分隔,
如 `--characters "小狐狸,月亮婆婆"`):工具自动注入对应角色的完整设定;**不要
自己粘贴设定文本——只传名字**。名字匹配不到或留空时自动回退全量
character_bible,角色锚永远在场。

## 2b. assets + cast(结构化资产锚,优先于 character_bible)

参考项目里更稳的做法是先把角色/道具/元素拆成结构化资产,再给每页记录出场
清单。独立 skill 用两个命令落库:

```
save-assets --file assets.json
save-cast --file cast.json
```

`assets.json` 形状:

```json
{
  "assets": [
    {
      "id": "little-fox",
      "type": "character",
      "name": "Little Fox",
      "description": "small red fox kit with amber eyes and a white chest",
      "invariants": "white chest, amber eyes, small stature",
      "prohibitions": "no clothes, no human hands",
      "usage": "main character"
    }
  ]
}
```

`cast.json` 形状:

```json
[
  {"page_id": "cover", "assets": ["little-fox"]},
  {"page_id": "page-1", "assets": ["little-fox", "moon-lantern"]}
]
```

资产写法:

- `type`: `character` / `prop` / `element`
- `description`: 可见形状/颜色/材质/结构,English,≤160 字符,不写画风词
- `invariants`: 必须不变的特征
- `prohibitions`: 常见错画/禁止项
- `usage`: 它在故事里的作用

一条合格资产答得出:一眼认出是什么、换角度还是同一个、哪些必须不变、哪些
不能出现、它在哪些页承担什么作用。

## 3. page.image_prompt(单页场景,保存上限 200 字符,拼装时截到 180)

**只写本页场景 + 动作 + 构图**(English)。**禁画风词**(medium / palette /
lighting / "anime style"…)、**禁角色长相**(hair / outfit / colors)——画风和
角色由两本 bible 自动前置,在这里重复 = 撑爆 500 字符预算 + 引发漂移。示例:

```
A little red fox walking through a dark forest at night, holding a glowing
lantern in its mouth, fireflies dancing around, tall shadowy trees on both
sides, a narrow dirt path leading forward.
```

### 画面与文字互补原则

image_prompt 不应重复 narration 已知的内容——narration 讲故事,画面揭示**没说
出来的细节**(第二叙事层)。

- 正确:narration「贝太太推开窗户大喊」→ image_prompt「贝太太站在窗边大声喊话,
  窗台上一个肉色助听器闪着红灯」(主角+动作在场,还埋了"她其实耳背")
- 错误(重复):「贝太太在窗户旁大喊」
- 错误(脱节):「窗台上一个肉色助听器闪着红灯」(丢了主角/场景)

每写一个 image_prompt 先自问:画面有主角和场景吗?有什么 narration 没说的细节?

### 封面(pages[0])特殊处理

同样公式,但 image_prompt 强调封面构图:标题氛围(暗示而非文字)、主角特写或
标志性场景、视觉重量放在上方 2/3(下方留给书名排版)。

## 4. consistency_constraints(固定,不可改)

```
Same character design and art style across all pages; coherent lighting and
palette; centered subject; no text or captions.
```

## 长度预算(铁律,compose-prompt 自动执行)

| 段 | 预算 |
|---|---|
| style_bible | ≤100 字符 |
| assets / character_bible | ≤220 字符(有 cast 用本页资产;无 cast 才用 --characters) |
| image_prompt | 保存 ≤200,拼装截 ≤180 |
| constraints | 固定 ~123 字符 |

总拼装 ≤500 字符,超出自动截尾。**直接把 compose-prompt 返回的 prompt 交给
出图工具,不要增删一个词。**
