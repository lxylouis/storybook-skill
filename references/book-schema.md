# book.json 字段文档

一本书一个目录:`book.json`(唯一事实源,**只能经 storybook.py 读写**)+
`images/` + 导出的 `<slug>.html`(+ 每次写入自动备份的 `book.json.bak`)。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| version | int | 数据格式版本,当前 1 |
| phase | enum | `outlining` / `awaiting_outline_confirm` / `illustrating` / `delivered` |
| idea / audience / style / author | string | intake 信息(init 写入) |
| style_bible | string | 全局画风锚(见 prompts.md) |
| character_bible | string | 角色定妆锚,每角色一行「名字: 设定」 |
| assets | array | 结构化资产锚(角色/道具/元素),由 `save-assets` 写入 |
| title | {zh, en} | 书名 |
| story_note | string | 1-2 句教育主题 |
| cover | {image_prompt, image_file} | 封面投影(与 pages[0] 同步,由 CLI 维护) |
| pages | array | 见下;**pages[0] 即封面** |
| current_page_index | int | 自动整本循环的游标(pages 下标) |
| created_at | string | ISO 时间 |

## pages[] 元素

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | `cover` 或 `page-N`(CLI 分配,勿自造) |
| page_no | int | 等于下标:封面 0,正文 1..N 连续 |
| page_title | {zh, en} | 正文页必填(zh 2-15 字);封面留空 |
| narration | {zh, en} | 双语旁白,均非空,各自地道 |
| image_prompt | string | 本页场景/动作/构图,English,≤200 字符 |
| image_file | string | `images/` 内相对路径;`""`=未生成;`"skipped"`=跳过哨兵 |
| image_history | array | 被覆盖/清空前复制到 `images/history/` 的旧图路径 |
| cast | array | 本页出场的 asset id,由 `save-cast` 写入;compose-prompt 优先注入 |
| failed_attempts | int | 出图失败计数(regenerate 维护) |
| skip_reason | string | (可选)跳过原因 |

## save-outline 的输入(outline.json)

```json
{
  "title": {"zh": "小狐狸找月亮", "en": "Little Fox Seeks the Moon"},
  "author": "lxy",
  "story_note": "学会观察与坚持。",
  "style_bible": "Soft watercolor ...",
  "character_bible": "Little Fox: ...\nMoon Granny: ...",
  "pages": [
    {"page_no": 0, "narration": {"zh": "...", "en": "..."},
     "image_prompt": "cover composition ..."},
    {"page_no": 1, "page_title": {"zh": "神秘的街角小屋", "en": "The Corner Hut"},
     "narration": {"zh": "...", "en": "..."}, "image_prompt": "..."}
  ]
}
```

- id 不用传(CLI 分配);amend 重交时**可带 `image_file`** 保住已生成的图。
- 若重交 outline 时 page id 和 image_prompt 没变且 style_bible 没变,CLI 会自动
  继承旧 `image_file` / `cast` / `image_history`;不用手工回填。改了
  image_prompt 或整体 style_bible 时,旧图会进 `image_history` 并清空待重画。
- 5-12 页**含封面**;page_no 必须等于数组下标。
- `amend-page` 对 `narration` / `page_title` 是**按语言浅合并**:只传 `{"zh": ...}`
  会保留原有的 `en`(反之亦然),方便单语言改字;但合并后两种语言仍须都非空。

## assets.json / cast.json 输入

`save-assets --file assets.json`:

```json
{
  "assets": [
    {"id": "little-fox", "type": "character", "name": "Little Fox",
     "description": "small red fox kit with amber eyes and a white chest",
     "invariants": "white chest and amber eyes",
     "prohibitions": "no clothes",
     "usage": "main character"}
  ]
}
```

`save-cast --file cast.json`:

```json
[
  {"page_id": "cover", "assets": ["little-fox"]},
  {"page_id": "page-1", "assets": ["little-fox", "moon-lantern"]}
]
```

`assets` 可写 asset id 或 name;CLI 会规范化为 id 存入每页 `cast`。

## 校验红线(save-outline / amend-page 会拦)

双语字段两种语言都非空;正文 page_title.zh 2-15 字;image_prompt ≤200 字符且
只写场景(禁画风词/角色长相);页号连续。被拦 = 读 hint 修内容,不是改 CLI。
