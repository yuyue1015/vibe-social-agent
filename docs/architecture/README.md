# 架构说明

本页面向需要理解项目内部边界的维护者。普通使用者只需要按照 [新手指南](../getting-started.md) 操作。

## 用户流程与内部层

用户看到的是：

```text
扫描开发记录 → 选择素材 → 生成微博草稿 → 修改 → Pull → Approve → Publish
```

内部实现会把扫描和编辑拆成多个阶段：

```text
开发记录
  → Story Detect
  → Story Ranking
  → Story Journey
  → Story Generate
  → Social Commit / Social PR
  → 人工审核
  → weibo-publish
```

这些阶段用于约束事实、公开安全性、分享节奏和草稿生成，不要求用户记忆内部名称或脚本命令。

## 职责边界

### vibe-social

负责本地项目中的内容发现、素材筛选、草稿生成、自然语言修改、Pull、Approve 和 Writing Memory。本 Skill 不执行微博外部写入。

### weibo-publish

消费已经 Approve 的本地草稿，进行发布前预览、用户确认、`weibo-cli` 预检、外部发布和发布结果回读。发布失败或回读不一致时，保持草稿为已审核状态。

## 状态边界

```text
素材候选 → Social Commit → 草稿 / Social PR → APPROVED → PUBLISHED
```

`APPROVED` 和 `PUBLISHED` 是两个不同的用户动作。任何性能记录都只能作为描述性参考，不能自动改写已批准内容或 Writing Memory。

## 数据边界

`.vibesocial/` 保存本地状态；原始源码、原始 diff、凭据和私人文件不应进入其中。公开内容只应来自经过筛选和人工确认的安全事实。
