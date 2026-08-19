# 统一交互状态规范

所有用户可见的流程节点都必须同时说明三件事：

1. 当前状态
2. 已完成动作
3. 下一步选择

不能只返回“已完成”，也不能只显示内部状态而不给用户操作入口。所有等待用户输入的位置，都必须给出明确选项；需要修改内容时，选项后立即收集自然语言修改意见。

## 候选发布建议

扫描完成后，默认按发布时机展示候选，而不是只展示最高 Story Value：

```text
推荐下一篇：
[1] 已形成明确结果的候选
    Story Value：8/10
    状态：READY
    原因：已验证并符合当前系列位置。

稍后更适合：
[2] 有价值但仍在探索的候选
    Story Value：9/10
    状态：HOLD
    原因：结果仍可能变化。

不建议单独发布：
[3] 内部整理
    状态：SKIP
    原因：缺少独立读者价值。
```

下一步：

```text
[1] 采用推荐选题
[2] 查看其他 READY / HOLD 候选
[3] 重新指定时间范围
[4] 暂不处理
```

`Story Value` 与 `Publish Readiness` 独立；高分候选不自动进入 READY。`HOLD` 或 `SKIP` 只有在用户明确坚持时，才允许带 override 创建 Social Commit。

## 草稿（DRAFT）

```text
当前状态：草稿已生成（DRAFT）。

已完成：已根据你选择的开发素材生成内容草稿。

下一步：
[1] 修改内容
[2] 审核通过并存入草稿箱（Approve）
[3] 换一个选题
[4] 暂不处理
```

## 提交修改（Pull 动作）

普通 DRAFT 修改只能使用 `vibe_state.py draft-edit`。Agent 不需要查找 `spr` ID、读取源码、调用 `--help`、创建 feedback 文件或手动同步标题和正文。只调用一次命令：

```text
python .agents/skills/vibe-social/scripts/vibe_state.py \
  --root <project-root> \
  draft-edit \
  --replace-old "<old>" \
  --replace-new "<new>"
```

`draft-edit` 会自动找到唯一当前 DRAFT，读取完整 `title`/`body`，执行精确替换；如果替换文本同时出现在标题和正文标题行，会同步更新两处。成功后只允许消费返回 JSON 的：

```text
full_draft.title
full_draft.body
current_state
next
```

普通编辑只能调用一次 `draft-edit`；禁止调用 `revise-pr`、`--help`、扫描、Story、Ranking 或 Publish Readiness。禁止只展示修改句、diff、修改摘要或“其他内容未修改”，也不得省略 `next` 菜单。

```text
已修改，当前完整草稿：

【完整标题】

完整正文……

当前状态：DRAFT

[1] 提交以上修改（Pull）
[2] 继续修改
[3] 放弃这些修改
```

普通措辞编辑走轻量路径：读取当前 DRAFT → 应用标题或正文修改 → 保存 revision → 展示完整草稿。此路径不重新执行项目扫描、Git 扫描、Story Detect、Story Ranking、Publish Readiness 或全量事实检索。

普通编辑不得调用 `scan_guard.py`、`story_detect.py`、`story_generate.py`、`story_aggregate.py`、`performance.py`，也不得重新执行 Story Ranking、Publish Readiness 或项目/Git 全量扫描。

只有用户明确要求核实事实、重新扫描、查源码，或修改导致正文中的数字发生变化时，才进入事实核验路径；没有证据前不得直接保存该事实修改。

Pull 是用户动作，不是持久化状态。修改后的 Social PR 仍保存为 `SOCIAL_PR`；任何 JSON 的 `status` 都不能写入 `PULL`。选择 `[2] 继续修改` 后立即收集下一条自然语言修改意见，并再次使用同一条 `draft-edit` 路径。

## 审核通过（APPROVED）

```text
当前状态：已审核通过并保存为草稿（APPROVED）。

已完成：已保存当前版本；学习偏好不会影响审核结果。

下一步：
[1] 发布到微博
[2] 手动发布其他平台
[3] 仅保存
[4] 继续修改
```

如果需要修改已经 `APPROVED` 的内容，必须先创建新版本。旧版本保持不变，新版本回到草稿流程：

```text
当前状态：已创建新的修改版本（DRAFT）。

已完成：已复制当前 APPROVED 内容；原版本保持不变。

下一步：
[1] 修改内容
[2] 审核通过并存入草稿箱（Approve）
[3] 暂不处理
```

“发布到微博”进入独立的 `weibo-publish` Skill；“手动发布其他平台”要求用户先自行完成外部动作，再提供平台名称，由本地状态记录完成结果，不代表本项目集成了其他平台。选择“仅保存”不产生外部写入。

## 已分发（PUBLISHED）

```text
当前状态：内容已分发（PUBLISHED）。

已完成：已记录分发平台、时间和结果。

下一步：
[1] 查看分发记录
[2] 开始处理下一篇
[3] 暂停
```

微博只有在 CLI 写入成功且完整正文回读一致后，才可进入 `PUBLISHED`。

## 发布失败或结果待核对

发布动作的用户可见结果必须与发布状态一致；Social Commit 仍保持 `APPROVED`，不能把失败标记为 `PUBLISHED`。

- `FAILED_RETRYABLE`：已确认最终微博写入命令没有执行，明确未发布，可以安全重试。
- `PUBLISHING`：发布结果尚未确认，不允许直接重试，先执行 reconcile。
- `UNKNOWN_REQUIRES_RECONCILIATION`：远端结果未知，必须先执行 reconcile，禁止重新发布。
- `PUBLISHED`：已确认发布，禁止重复发布。

下一步：

[1] 按当前状态重新检查或执行 reconcile
[2] 返回修改
[3] 仅保存并暂停

只有 `FAILED_RETRYABLE` 可以直接回到发布预览并重试；`PUBLISHING` 和 `UNKNOWN_REQUIRES_RECONCILIATION` 必须先 reconcile。

## 示例流程结束

示例不应以“结束”作为最后输出。示例完成后必须返回项目状态选择：

```text
示例体验完成。

请选择：

[1] 新项目第一次接入
[2] 已有开发中的项目
[3] 再看一次示例
[4] 退出
```
