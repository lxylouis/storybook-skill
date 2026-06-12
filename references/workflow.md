# 流程细则与边角案例

## 0. 任何会话的第一步

`status --dir <book-dir>`。它输出 phase、逐页进度(done/skipped/失败次数)和
next_action。**别凭记忆行动**——上个会话可能停在任何地方。
用户没给出书目录时:新书 → init;找旧书 → 在工作区 `ls` 找含 book.json 的目录。

## 1. intake(还没有 book.json)

收集:一句话故事创意(必需)、目标年龄、画风偏好、署名(可选;不要逼问,缺省
即可)。`init --idea ... --dir <父目录>` → 返回 book_dir,后续命令全部
`--dir <book_dir>`。用户给了参考材料(文档/长文)就先读完提炼主题、角色、
情节要点再设计。

## 2. outlining → save-outline

按 references/prompts.md 创作:title{zh,en}、author、story_note、style_bible、
character_bible、pages[](pages[0] 为封面,page_no=0,无 page_title;正文
page_no 1..N,page_title.zh 2-15 字)。每页 narration 双语各自地道,有拟声词
(嗖——、扑通、哗啦)、短句节奏、口语感。写成 outline.json 后:
`save-outline --file outline.json --dir <book_dir>`。
校验失败 → 读 error/hint 修正重交,**不要绕过校验**。

## 3. 封面 + 用户确认(awaiting_outline_confirm)

1. `compose-prompt --page cover --characters <封面出场角色>`
2. 出图(双轨,见 SKILL.md)→ `save-image --page cover --file <img>`
3. 向用户展示:书名(双语)、每页一句话梗概或页标题列表、封面图路径/图片
4. **硬等待**。用户说改 → `amend-outline` 回 outlining 重写再 save-outline:
   - 只改文字/页序:新 outline.json 里**带回原 image_file**(从 status 拿),
     封面复用不重出
   - 改画风/封面 image_prompt:对应页 image_file 留空,重出封面再展示
5. 用户明确确认 → `confirm-outline`(若封面没图会被拦,先补图)

## 4. illustrating:自动整本循环

confirm-outline 的返回就是第一个正文页。对每页:

```
compose-prompt --page page-N --characters <本页角色名>
→ 出图(轨道 A 或 B)→ save-image --page page-N --file <img>
→ 向用户报一行进度(「第 N/总 页画好了」)
→ next   # 返回下一页数据;all_done=true 则 finalize
```

- **不停顿**:中途不要问用户"要继续吗"。
- 失败路径:出图失败 → `regenerate --page page-N`(记失败次数)→ 重试;
  failed_attempts ≥ 3 → 停下来问用户改 prompt(amend-page)还是 `skip`。
- 用户中途插话改某页 → amend-page / regenerate 处理完该页,继续循环。
- 用户要求"一页页给我看" → 切换为每页后停下等确认(next 前等用户点头)。

## 5. delivered:交付与返修

finalize 自动导出 HTML 并返回绝对路径。告诉用户:双击打开、可发微信、浏览器
打印 = PDF。整本超大(几十 MB)不便传输时,`export --link-images` 出小文件版
(需连同 images/ 目录一起拷走)。

| 用户说 | 动作 |
|---|---|
| 改第 N 页文字 | `amend-page --page page-N --json '{"narration": {...}}'` → `export` |
| 改第 N 页画面 | `amend-page --json '{"image_prompt": "..."}'` → `regenerate` → 出图 → `save-image` → `export` |
| 第 N 页图重画 | `regenerate` → 出图 → `save-image` → `export` |
| 换画风 | `amend-outline` 回炉(全书重出),向用户确认后执行 |
| 再来一本 | 新目录 `init`(旧书目录原样保留) |

## 6. 数据安全

- book.json 只能经 CLI 写;每次写入自动留 book.json.bak。
- 损坏恢复:`cp book.json.bak book.json` 后 `status` 核对。
- CLI 没有任何删除整书的命令;用户要删书 = 删目录,**先口头确认再动手**。
