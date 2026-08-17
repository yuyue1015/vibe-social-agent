\# Publish Readiness Spec



\## 1. 目的



Vibe Social 不能只回答：



> “这个开发事件有没有故事价值？”



还需要回答：



> “这个故事现在适不适合公开？”



Story Ranking 与 Publish Readiness 必须分开。



\- Story Ranking：判断故事价值

\- Publish Readiness：判断当前发布时机



高故事价值不等于应该立即发布。





\## 2. 目标



降低开发者判断成本。



用户不应该自己逐个猜：



\- 哪个故事该发

\- 哪个故事先放着

\- 哪个故事不值得发



Skill 应在生成 Social Commit 前，自动给候选增加发布建议。





\## 3. 流程位置



当前流程：



开发记录

→ Story Detect

→ Story Ranking

→ Social Commit

→ Draft

→ Approve

→ Publish



调整为：



开发记录

→ Story Detect

→ Story Ranking

→ Publish Readiness

→ Social Commit

→ Draft

→ Approve

→ Publish





\## 4. 核心原则



\### 4.1 故事价值和发布时机分离



例如：



Unity 资源解析实验：



\- Story Score：9/10

\- Publish Readiness：HOLD



原因：



技术探索有故事价值，但结果尚未形成稳定能力。





\### 4.2 不要求所有故事必须“完成”



微博适合开发过程公开。



因此未完成 ≠ 不能发。



但必须区分：



\- 已形成明确阶段结果

\- 已验证但仍在继续

\- 仍处于不稳定探索

\- 尚无可公开结论





\### 4.3 不把“最新”当成“最应该发”



最新开发事件只是候选来源之一。



应同时考虑：



\- 是否已有结果

\- 是否适合当前系列阶段

\- 是否重复

\- 是否有读者价值

\- 是否容易造成误解





\## 5. Publish Status



只使用三个状态。



\### READY



适合当前进入 Social Commit。



典型情况：



\- 第一次形成可用版本

\- 功能已经完成并验证

\- Bug 修复有明确前后对比

\- 阶段性实验已经得到可靠结论

\- 已发布版本的重要变化

\- 与当前系列节奏匹配





\### HOLD



有故事价值，但暂时不建议作为下一篇发布。



典型情况：



\- 技术实验仍未形成稳定结果

\- 很适合后续阶段总结

\- 与刚发布内容高度重复

\- 当前系列还有更早、更基础的故事未讲

\- 重要结果仍可能发生明显变化





\### SKIP



当前不值得形成独立开发日志。



典型情况：



\- 单纯依赖升级

\- 格式整理

\- 无用户价值的内部重构

\- 无明显结果的 housekeeping

\- 重复事件

\- 缺少足够事实证据





\## 6. 判断维度



\### 6.1 Completion



判断当前事件达到什么程度。



允许：



\- `complete`

\- `validated`

\- `exploring`

\- `unknown`



说明：



\#### complete



已经形成明确结果。



例如：



\- 功能完成

\- 发布版本

\- Bug 修复完成

\- 用户流程可运行



\#### validated



已经得到可靠阶段结果，但仍未形成最终功能。



例如：



\- 算法验证成功

\- 实验得到稳定样本

\- 性能测试得到明确结论



\#### exploring



仍在尝试。



例如：



\- 路线未确定

\- 样本过少

\- 结果可能变化



\#### unknown



当前 evidence 无法判断完成度。





\## 7. Reader Value



判断外部读者是否容易理解为什么值得看。



重点优先：



\- 用户可感知变化

\- 具体问题与解决

\- 明确前后对比

\- 数字或测试结果

\- 方法转折

\- 失败与纠正

\- 阶段性成果



低优先：



\- 内部命名调整

\- 无结果重构

\- 目录整理

\- 纯配置变化





\## 8. Series Position



发布建议不能只按分数排序。



Skill 应考虑项目故事线。



典型 Story Journey：



1\. why / origin

2\. first\_solution

3\. first\_usable\_version

4\. refinement

5\. expansion

6\. validation

7\. milestone

8\. deeper\_exploration



如果当前项目从未讲过早期故事：



较早、已闭环的 first\_solution



可以优先于：



最新但未完成的 deeper\_exploration。





\## 9. Recency



Recency 只作为参考，不作为决定因素。



禁止：



最新事件 = 默认第一推荐



更合理的规则：



\- 最新 + 完成 + 有价值 → 高优先

\- 较早 + 从未讲过 + 是重要起点 → 可以优先

\- 最新 + exploring → 通常 HOLD

\- 很旧 + 已经发布过 → SKIP / duplicate





\## 10. Evidence Requirement



Publish Readiness 不能降低现有事实安全要求。



必须继续遵守：



Strong evidence：

\- Git history

\- Git working-tree change

\- 明确 test report

\- changelog / dev note

\- 用户当前明确进度说明



Supporting evidence：

\- 源码

\- 测试代码

\- 文档



Insufficient：

\- README 功能描述

\- mtime

\- 文件存在

\- 旧 `.vibesocial` 已发布内容



Supporting evidence 不能单独证明：



“这是最近完成的功能。”





\## 11. Series History



`.vibesocial` 可以用于：



\- 判断是否已经讲过

\- 判断上一篇内容

\- 判断系列当前阶段

\- 判断重复



不能用于：



\- 作为新开发事实

\- 从旧文章反推当前开发状态





\## 12. 输出数据



每个 ranked candidate 增加：



```json

{

&#x20; "story\_score": 9,

&#x20; "publish\_readiness": {

&#x20;   "status": "ready",

&#x20;   "completion": "complete",

&#x20;   "reason": "已形成可用版本，属于项目最早的核心闭环，适合作为系列起点。"

&#x20; }

}
状态只能为：

ready
hold
skip
13. 用户可见输出

不要让用户自己逐个判断。

推荐输出：

发现 4 个值得关注的开发故事。


推荐下一篇：


[1] 第一次让房间模板真正导入游戏
    Story Value：8/10
    状态：READY
    原因：已形成第一个可用版本，也是项目最自然的故事起点。


稍后更适合：


[2] 从单游戏扩展到三款游戏
    Story Value：9/10
    状态：HOLD
    原因：价值很高，但更适合作为后续产品成长故事。


[3] Unity 资源属性解析
    Story Value：9/10
    状态：HOLD
    原因：技术探索有价值，但目前结果仍未接入产品。


不建议单独发布：


[4] 内部目录整理
    状态：SKIP

然后必须给下一步：

[1] 采用推荐选题
[2] 查看其他 READY / HOLD 候选
[3] 重新指定时间范围
[4] 暂不处理
14. Social Commit Gate

默认只有：

READY

候选进入 Social Commit。

HOLD：

用户可以明确选择继续，但系统必须提示当前为什么建议暂缓。

SKIP：

默认不提供创建 Social Commit 的主流程入口。

如果用户明确要求，允许人工覆盖，但应记录这是用户 override。

15. 不应发生的行为

禁止：

因为候选 Story Score 高就默认发布
因为事件最新就默认发布
把 exploring 写成 complete
把未接入产品的实验描述为现有功能
让用户自己猜整个候选池的发布顺序
为了“完整故事”编造用户反馈
把旧 .vibesocial 内容当新事实
16. 对 tph-roomtemplate 的参考判断

示例：

.tsav 首个导入工具 1.0.0
Story Value：8
Completion：complete
Readiness：READY
原因：
项目早期核心闭环
已形成发布版本
适合作为系列起点
三游戏统一助手 2.0.0
Story Value：9
Completion：complete
Readiness：HOLD / READY_LATER
实现中统一使用 HOLD
原因：
产品价值高
更适合作为后续成长篇
Unity 资源属性解析实验
Story Value：9
Completion：validated / exploring
Readiness：HOLD
原因：
技术价值高
尚未形成稳定产品能力
普通内部整理
Story Value：低
Readiness：SKIP
17. 第一版实现边界

第一版只做：

增加 Publish Readiness 判断
ready / hold / skip
增加 completion
参考 series state
用户可见推荐顺序
Social Commit 前 gate

第一版不做：

内容日历
自动发布时间
SaaS
数据库
多平台发布策略
AI 自动发布
复杂内容运营系统
长期预测模型
18. 验收标准

至少验证三个真实项目：

tph-roomtemplate

期望：

1.0.0 早期闭环应优先于未完成资源解析实验
2.0.0 三游戏扩展应保留为高价值后续故事
TPHhelper

期望：

已验证的核心功能优先
尚未完成的 UI / 实验不应自动顶到第一推荐
vibe-social-agent

期望：

已完成并通过验证的 Skill 演进可进入 READY
当前未来构想不得被写成已完成功能
19. 成功标准

用户说：

“看看最近有什么值得发的。”

Skill 应直接给：

推荐下一篇
为什么
哪些先放着
下一步按钮

而不是要求用户理解：

Story Candidate
Story Ranking
Journey
Social Commit ID
内部状态机

内部系统可以复杂。

用户操作必须简单。
