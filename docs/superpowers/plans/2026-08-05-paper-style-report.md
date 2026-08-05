# HiddenBench × MAF 论文式实验报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份围绕实验结论组织、符合老师指定五章结构、引用不少于 15 篇学术文献并经过逐页视觉验收的中文论文式 Word 文档。

**Architecture:** 使用现有 `hiddenbench-aug02-complete-summary.json` 作为实验事实源，新增论文证据锁定脚本、参考文献注册表、两幅可复现学术图和独立 Word 生成器。正文按研究问题组织，附录保存 Prompt、任务事实、运行 ID 和哈希；所有关键表述由自动测试锁定，避免在排版过程中改变统计边界。

**Tech Stack:** Python 3、python-docx、OOXML、matplotlib、JSON、pytest、Microsoft Word COM/Poppler（当 LibreOffice 不可用时的渲染替代）、Git/GitHub CLI。

## Global Constraints

- 保留 `reports/给彭老师的完整实验报告_2026-08-02至2026-08-04.docx` 及此前所有报告不变，论文版必须保存为新文件。
- 论文题目固定为“基于 MAF 的多智能体私有信息披露机制复现与对比研究”。
- 正文结构固定为：摘要、关键词、1 引言、2 相关研究、3 本文方法、4 实验结果及分析、5 总结与展望、参考文献、附录。
- 摘要必须为 6 至 7 句话，并包含背景、现有不足、方法、560 次运行、25,928 次模型请求、主要结果与结论边界。
- 中心结论不得改变：全局 Reveal-All 在三题各 10 次中均为 10/10；三个精确 McNemar p 值为 0.125、0.125、0.388；动态机制尚未显示统计显著优势。
- MAF 只写为 Agent/模型执行层；动态调度器写为拥有完整私有事实分配的外部集中式调度器。
- pair seed 只控制事实分配；generation seed 未传给 DeepSeek。
- Codex 144 项复核写为模型辅助复核，不得称为人工金标准。
- 2-2 结果写为 final tie，不得写为答案翻转。
- 至少 15 篇参考文献，每篇必须在正文中有一个按首次出现顺序排列的 `[n]` 引文。
- 采用 `narrative_proposal` 设计预设；首页使用 `proposal_centerpiece` 的学术化变体，不做独立封面。
- 页面为 US Letter 纵向、四边 1 英寸、内容宽 9360 DXA；正文 11 pt、两端对齐、1.333 倍行距；表格宽 9360 DXA、缩进 120 DXA。
- 最终输出：`reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`，并复制到桌面同名文件。

---

### Task 1: 建立论文参考文献注册表

**Files:**
- Create: `reports/data/hiddenbench-paper-references-20260805.json`
- Create: `tests/test_hiddenbench_paper_references.py`

**Interfaces:**
- Consumes: 官方论文页面、arXiv/会议论文原文和官方代码仓库关联的论文元数据。
- Produces: JSON 数组；每项包含 `key`、`authors`、`title`、`venue`、`year`、`identifier`、`url`、`used_in`，供论文生成器按首次出现顺序渲染。

- [ ] **Step 1: 写参考文献注册表的失败测试**

```python
def test_reference_registry_is_academic_and_complete():
    refs = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    assert len(refs) >= 15
    assert len({item["key"] for item in refs}) == len(refs)
    for item in refs:
        assert set(item) == {
            "key", "authors", "title", "venue", "year",
            "identifier", "url", "used_in",
        }
        assert item["used_in"]
        assert item["url"].startswith("https://")
```

- [ ] **Step 2: 运行测试并确认因注册表不存在而失败**

Run: `python -m pytest -q tests/test_hiddenbench_paper_references.py`

Expected: FAIL，指出 `hiddenbench-paper-references-20260805.json` 不存在。

- [ ] **Step 3: 只使用原始论文或官方会议页面核验文献**

至少覆盖以下实际使用主题：HiddenBench、MAST、MAF/执行框架、AutoGen、多智能体辩论、共识自由辩论、发散思维、失败归因、LLM 多智能体综述、AgentVerse、MetaGPT、ChatDev、动态 Agent 网络、信息不对称/共享信息偏差以及多智能体共识可靠性。记录准确作者、题名、年份、会议或 arXiv 标识，不引用搜索结果页。

- [ ] **Step 4: 写入不少于 15 篇的注册表并按正文首次出现顺序排序**

```python
registry = sorted(verified_records, key=lambda item: first_citation_order[item["key"]])
REFERENCE_PATH.write_text(
    json.dumps(registry, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

`verified_records` 的每个字段必须从 Step 3 打开的原始论文页面抄录元数据，`used_in` 只登记实际写入正文的章节号。

- [ ] **Step 5: 运行注册表测试**

Run: `python -m pytest -q tests/test_hiddenbench_paper_references.py`

Expected: PASS，文献数不少于 15、键唯一、每篇都有正文使用位置。

- [ ] **Step 6: 提交参考文献证据**

```powershell
git add reports/data/hiddenbench-paper-references-20260805.json tests/test_hiddenbench_paper_references.py
git commit -m "data: add verified references for paper-style report"
```

### Task 2: 构建论文证据锁定快照

**Files:**
- Create: `reports/build_paper_evidence.py`
- Create: `reports/data/hiddenbench-paper-evidence-20260805.json`
- Create: `tests/test_build_paper_evidence.py`

**Interfaces:**
- Consumes: `reports/data/hiddenbench-aug02-complete-summary.json` 与 Task 1 参考文献注册表。
- Produces: `build_paper_evidence(root: Path, output: Path) -> dict[str, Any]`；返回研究问题、摘要事实、方法边界、结果矩阵、案例索引、引用映射和源文件哈希。

- [ ] **Step 1: 写锁定关键结论的失败测试**

```python
def test_paper_evidence_locks_headline_results(tmp_path: Path):
    output = tmp_path / "paper-evidence.json"
    evidence = build_paper_evidence(ROOT, output)
    assert evidence["totals"] == {
        "local_runs": 560,
        "discussion_vote_requests": 25531,
        "audit_requests": 397,
        "model_requests": 25928,
    }
    assert evidence["official_global_reveal"] == {
        "ID1": "10/10", "ID2": "10/10", "ID3": "10/10"
    }
    assert evidence["mcnemar_p_values"] == [0.125, 0.125, 0.388]
    assert evidence["early_stop_exception"] == "2-2 final tie"
```

- [ ] **Step 2: 运行测试并确认模块不存在而失败**

Run: `python -m pytest -q tests/test_build_paper_evidence.py`

Expected: FAIL，`reports.build_paper_evidence` 无法导入。

- [ ] **Step 3: 实现证据构建与硬性断言**

```python
def build_paper_evidence(root: Path, output: Path) -> dict[str, Any]:
    summary = json.loads((root / "reports/data/hiddenbench-aug02-complete-summary.json").read_text(encoding="utf-8"))
    evidence = {
        "paper_title": "基于 MAF 的多智能体私有信息披露机制复现与对比研究",
        "research_questions": ["RQ1", "RQ2", "RQ3"],
        "totals": summary["totals"],
        "official_global_reveal": summary["official_global_reveal"]["local_success_counts"],
        "mcnemar_p_values": summary["statistics"]["paired_exact_mcnemar_p_values"],
        "early_stop_exception": "2-2 final tie",
        "source_hashes": summary["source_hashes"],
    }
    _validate_locked_claims(evidence)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence
```

实现时按真实摘要字段映射，禁止为满足测试而复制数值；若字段名不同，读取并转换到上述稳定接口。

- [ ] **Step 4: 运行证据测试并生成正式 JSON**

Run: `python reports/build_paper_evidence.py --root . --output reports/data/hiddenbench-paper-evidence-20260805.json`

Run: `python -m pytest -q tests/test_build_paper_evidence.py`

Expected: PASS，正式 JSON 存在且包含原始来源哈希。

- [ ] **Step 5: 提交证据快照**

```powershell
git add reports/build_paper_evidence.py reports/data/hiddenbench-paper-evidence-20260805.json tests/test_build_paper_evidence.py
git commit -m "data: lock evidence for paper-style report"
```

### Task 3: 生成两幅学术图

**Files:**
- Create: `reports/build_paper_figures.py`
- Create: `reports/figures/maf-governance-architecture.png`
- Create: `reports/figures/hiddenbench-experiment-flow.png`
- Create: `tests/test_build_paper_figures.py`

**Interfaces:**
- Consumes: Task 2 的证据 JSON。
- Produces: `build_figures(root: Path, output_dir: Path) -> list[Path]`，生成 1600×900 以上的 PNG，供 Word 生成器嵌入。

- [ ] **Step 1: 写图文件尺寸和标签测试**

```python
def test_paper_figures_are_large_and_reproducible(tmp_path: Path):
    paths = build_figures(ROOT, tmp_path)
    assert {p.name for p in paths} == {
        "maf-governance-architecture.png",
        "hiddenbench-experiment-flow.png",
    }
    for path in paths:
        with Image.open(path) as image:
            assert image.width >= 1600
            assert image.height >= 900
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest -q tests/test_build_paper_figures.py`

Expected: FAIL，图生成模块不存在。

- [ ] **Step 3: 实现系统结构图和实验流程图**

系统结构图固定包含：HiddenBench 任务、私有事实分配、MAF Agent/模型执行、固定/动态调度、公开讨论、投票、披露审计、统计分析；动态调度框标注“外部集中式”。实验流程图固定包含：任务锁定、成对事实分配、讨论条件、同预算运行、投票、AI/规则披露审计、配对统计、案例编码。

```python
def build_figures(root: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture = output_dir / "maf-governance-architecture.png"
    flow = output_dir / "hiddenbench-experiment-flow.png"
    _draw_architecture(architecture, dpi=200)
    _draw_experiment_flow(flow, dpi=200)
    return [architecture, flow]
```

- [ ] **Step 4: 生成正式图并运行测试**

Run: `python reports/build_paper_figures.py --root . --output-dir reports/figures`

Run: `python -m pytest -q tests/test_build_paper_figures.py`

Expected: PASS，两幅 PNG 尺寸和名称正确。

- [ ] **Step 5: 逐图查看并修正文字遮挡**

使用本地图片查看工具以原始尺寸检查两幅图；若存在裁切、文字重叠或中文缺字，修改绘图代码并重新运行 Task 3 测试。

- [ ] **Step 6: 提交图表生成器**

```powershell
git add reports/build_paper_figures.py reports/figures tests/test_build_paper_figures.py
git commit -m "docs: add reproducible figures for paper-style report"
```

### Task 4: 建立论文式 Word 生成器与结构测试

**Files:**
- Create: `reports/build_paper_style_report.py`
- Create: `tests/test_build_paper_style_report.py`
- Create: `reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

**Interfaces:**
- Consumes: Task 1 参考文献、Task 2 证据、Task 3 图文件、现有完整摘要和原始运行数据。
- Produces: `build_report(root: Path, output: Path, desktop_output: Path | None) -> Path`。

- [ ] **Step 1: 写论文结构、摘要句数和原文件保护测试**

```python
def test_paper_report_has_required_structure_and_locked_claims(tmp_path: Path):
    output = tmp_path / "paper.docx"
    build_report(ROOT, output, None)
    doc = Document(output)
    text = "\n".join(p.text for p in doc.paragraphs)
    for heading in [
        "摘要", "1 引言", "2 相关研究", "3 基于 MAF 的信息披露治理方法",
        "4 实验结果及分析", "5 总结与展望", "参考文献", "附录",
    ]:
        assert heading in text
    assert "560 次本地运行" in text
    assert "25,928 次模型请求" in text
    assert "10/10" in text
    assert "0.125" in text and "0.388" in text
    assert "未达到统计显著优势" in text
```

- [ ] **Step 2: 运行测试并确认生成器不存在而失败**

Run: `python -m pytest -q tests/test_build_paper_style_report.py`

Expected: FAIL，`reports.build_paper_style_report` 无法导入。

- [ ] **Step 3: 实现 `narrative_proposal` 样式和学术首页**

```python
STYLE_TOKENS = {
    "page": {"width": 12240, "height": 15840, "margin": 1440, "content": 9360},
    "body": {"font_cn": "Microsoft YaHei", "font_en": "Calibri", "size": 11, "after": 8, "line": 1.333},
    "h1": {"size": 16, "before": 18, "after": 10, "color": "2E74B5"},
    "h2": {"size": 13, "before": 12, "after": 6, "color": "2E74B5"},
    "h3": {"size": 12, "before": 8, "after": 4, "color": "1F4D78"},
    "table": {"width_dxa": 9360, "indent_dxa": 120},
}
```

首页包含居中题目、作者/单位占位、日期、6 至 7 句摘要和关键词，不创建空白封面页。

- [ ] **Step 4: 实现五章正文骨架和真实编号标题**

生成函数拆分为 `_abstract`、`_introduction`、`_related_work`、`_method`、`_experiments`、`_conclusion`、`_references`、`_appendices`；所有编号标题使用 Word Heading 样式，不用手工加粗模拟标题。

- [ ] **Step 5: 运行结构测试**

Run: `python -m pytest -q tests/test_build_paper_style_report.py`

Expected: PASS，标题结构、核心数值和原报告保护断言通过。

- [ ] **Step 6: 提交 Word 生成器骨架**

```powershell
git add reports/build_paper_style_report.py tests/test_build_paper_style_report.py
git commit -m "docs: scaffold paper-style HiddenBench report"
```

### Task 5: 写入论文论证、表格、引用和附录

**Files:**
- Modify: `reports/build_paper_style_report.py`
- Modify: `tests/test_build_paper_style_report.py`
- Create: `reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

**Interfaces:**
- Consumes: Task 4 生成器接口。
- Produces: 完整论文正文、按出现顺序编号的引用、结果表和复现附录。

- [ ] **Step 1: 增加引用闭环和禁用表述测试**

```python
def test_every_reference_is_cited_and_claims_are_bounded(tmp_path: Path):
    output = tmp_path / "paper.docx"
    build_report(ROOT, output, None)
    doc = Document(output)
    text = "\n".join(p.text for p in doc.paragraphs)
    refs = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    for index in range(1, len(refs) + 1):
        assert text.count(f"[{index}]") >= 2  # 正文一次，参考文献一次
    for forbidden in ["答案翻转", "人工金标准已完成", "证明了普遍有效", "显著提升动态发言"]:
        assert forbidden not in text
```

- [ ] **Step 2: 运行新增测试并确认正文尚不完整而失败**

Run: `python -m pytest -q tests/test_build_paper_style_report.py`

Expected: FAIL，缺少正文引用或参考文献条目。

- [ ] **Step 3: 完成摘要、引言和相关研究**

摘要严格写成 7 句。引言提出 RQ1 至 RQ3。相关研究按 2.1 至 2.5 组织，所有专业词第一次出现时给出中文解释和 `[n]` 引用，不复制论文原句。

- [ ] **Step 4: 完成方法章节并嵌入公式和两幅图**

披露率公式写为：

`D = m / n × 100%`

其中 `n` 为任务私有原子事实总数，`m` 为审计判定已在公共讨论中表达的事实数。配对比较说明采用精确 McNemar 检验；Wilson 区间用于小样本二项比例的不确定性表达。

- [ ] **Step 5: 完成实验章节和结果表**

至少包含：任务与官方结果表、实验条件表、累计运行规模表、同预算对照表、官方兼容 Reveal-All 表、配对统计表、典型案例表。每张表提供样本量、分母、表题和表下注释；官方 GPT-4.1 与本地 DeepSeek 分列显示。

- [ ] **Step 6: 完成总结与展望**

结论按以下逻辑写：完整披露在三题上表现稳定；动态调度没有显著优势；共识不等于正确；贡献是复现、对照和识别研究边界；下一步扩大任务、人工盲审、2×2 因子实验和跨模型复验。

- [ ] **Step 7: 完成参考文献与附录**

附录加入三题完整事实、讨论/投票/审计 Prompt、75% 披露实例、典型运行 ID、官方与本地代码来源、commit、PR 和证据哈希。正文只保留短 Prompt 片段，完整 Prompt 放附录。

- [ ] **Step 8: 生成仓库版和桌面版 Word**

Run: `python reports/build_paper_style_report.py --root . --output reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx --desktop-output C:/Users/liuli/Desktop/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

- [ ] **Step 9: 运行论文专项测试**

Run: `python -m pytest -q tests/test_hiddenbench_paper_references.py tests/test_build_paper_evidence.py tests/test_build_paper_figures.py tests/test_build_paper_style_report.py`

Expected: PASS，结构、数据、引用、禁用表述、图表和原报告保护全部通过。

- [ ] **Step 10: 提交完整论文文档**

```powershell
git add reports/build_paper_style_report.py reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx tests/test_build_paper_style_report.py
git commit -m "docs: add paper-style HiddenBench experiment report"
```

### Task 6: 渲染、逐页检查并修正排版

**Files:**
- Modify if needed: `reports/build_paper_style_report.py`
- Modify if needed: `tests/test_build_paper_style_report.py`
- Regenerate: `reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

**Interfaces:**
- Consumes: Task 5 完整 DOCX。
- Produces: 通过所有页面视觉检查的最终 DOCX；渲染 PNG/PDF 只保存在 `.tmp/paper-style-report-render/`，不作为交付物。

- [ ] **Step 1: 尝试规范 DOCX 渲染器**

Run: `python C:/Users/liuli/.codex/plugins/cache/openai-primary-runtime/documents/26.802.11031/skills/documents/render_docx.py reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx --output_dir .tmp/paper-style-report-render --emit_pdf`

Expected: 生成 `page-<N>.png`；若仅因 `soffice` 不存在而失败，使用 Microsoft Word COM 导出 PDF，再用 Poppler 转为 PNG。

- [ ] **Step 2: 逐页以原始尺寸检查所有 PNG**

检查标题、摘要、公式、图题、跨页表头、参考文献、代码块、页眉页脚、中文字体和孤立标题。任何一页出现截断、重叠、乱码、异常空白或图中文字过小都必须回到生成器修复并重新渲染全部页面。

- [ ] **Step 3: 增加对应回归测试后修正排版问题**

例如，若出现不必要空白页，先增加页分隔数量测试：

```python
page_breaks = document._element.xpath("//w:br[@w:type='page']")
assert len(page_breaks) <= 2
```

再修改生成器并重跑专项测试。

- [ ] **Step 4: 运行样式和表格几何审计**

确认 Letter 页面、1 英寸边距、正文和标题样式、真实编号列表、所有全宽表格 `tblW=9360`、`tblInd=120`、列宽总和 9360 DXA；确认没有用表格包装普通段落。

- [ ] **Step 5: 提交视觉修正**

```powershell
git add reports/build_paper_style_report.py reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx tests/test_build_paper_style_report.py
git commit -m "fix: polish paper report layout"
```

若无需修改，不创建空提交。

### Task 7: 全套验证、推送和交付

**Files:**
- Verify: all changed files
- Copy: `C:/Users/liuli/Desktop/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

**Interfaces:**
- Consumes: Tasks 1 至 6 的最终提交。
- Produces: 测试通过、工作区干净、远端 PR 更新且本地/桌面 DOCX 哈希一致的交付状态。

- [ ] **Step 1: 运行论文专项测试和全套测试**

Run: `python -m pytest -q tests/test_hiddenbench_paper_references.py tests/test_build_paper_evidence.py tests/test_build_paper_figures.py tests/test_build_paper_style_report.py`

Run: `python -m pytest -q`

Expected: 两组均为 PASS。

- [ ] **Step 2: 检查差异、凭据和文件一致性**

Run: `git diff --check`

Run: `git status --short`

Run: `Get-FileHash -Algorithm SHA256 reports/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx, C:/Users/liuli/Desktop/基于MAF的多智能体私有信息披露机制复现与对比研究_2026-08-05.docx`

扫描改动文件，确认不存在 API key、访问令牌或模型密钥。

- [ ] **Step 3: 使用分支收尾流程**

调用 `superpowers:verification-before-completion` 和 `superpowers:finishing-a-development-branch`。本任务沿用用户已选择的“推送分支并更新 Pull Request”方式，不本地合并 master，也不删除工作树。

- [ ] **Step 4: 推送并更新 PR #5**

Run: `git push origin codex/budget-matched-dynamic`

用 `gh pr edit 5` 补充论文式报告、参考文献数量、总页数、测试结果和最终 SHA-256；若 TLS 握手失败，仅用 `git -c http.version=HTTP/1.1 push` 重试，不强推。

- [ ] **Step 5: 最终交付**

最终回复只引用桌面论文式 DOCX 一次，简要报告页数、参考文献数量、测试结果、视觉检查和 PR URL；不交付内部 PNG/PDF。
