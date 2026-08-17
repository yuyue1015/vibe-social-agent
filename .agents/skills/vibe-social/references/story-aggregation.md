# Story Aggregation

Story Aggregation is a side path for stage-based material aggregation and inspiration candidates. It does not rewrite individual Weibo stories, create a finished article, or enter the Weibo publishing flow.

The main flow remains:

真实开发 → Story Detect → Story Ranking → Story Journey → 微博生成 → 人工确认 → weibo-publish → Performance Learning

The side path is:

已积累 Story → 阶段性素材聚合 → 仅供未来内容灵感参考

## Sources

- Read approved or published Social Commit metadata from `.vibesocial/social-commits/`.
- An explicit story input file may provide real Story records for another project or an external import.
- Read only safe story metadata: IDs, titles, event types, stages, topics, summaries, evidence flags, and status.
- Never use `final_text`, raw source, raw diffs, credentials, or full private documents as aggregation material.

## Relatedness

Stories may be grouped when they share a topic, feature chain, series, or a meaningful common development stage. A shared generic word such as “开发” or “结果” is not enough. Unrelated stories must remain separate even when their count is high.

## Candidate threshold

A related group can become an aggregation candidate when at least one condition holds:

- four or more related stories;
- an explicitly completed feature stage;
- an origin → problem → adjustment → result arc;
- a clear rework or validation cycle has ended;
- enough before/after evidence and presentable screenshots exist.

Groups that are related but do not meet a condition may still be reported with a low readiness score so the workflow can say “继续积累素材”. They remain material candidates only.

## Readiness

`readiness_score` is 0–10 and measures whether the material is ready to be organized, not whether the software is technically important.

- `0–6`: continue accumulating material.
- `7–8`: the material has a usable phase-level content idea.
- `9–10`: can serve as a future Xiaohongshu topic-material candidate after separate human editorial work.

The output contains only a title direction, included IDs, stage summary, narrative arc, timing rationale, missing material, score, and recommendation. It is not a finished draft, and it does not trigger generation or publishing. Individual Weibo remains the single-Story format.
