"""静态页结构回归:容器标签配对必须平衡且中途不为负。

背景:2026-09-18 view-admin 区间多写了一个 </div>,浏览器解析时把
section/main/.app 外壳全部提前闭合,之后的「全库回看」「帮助与方案」
两个视图被挂到 body 下、渲染在应用外壳之外,主区域全白(本地因只查
className 未查父子关系而漏测)。此测试防再犯。
"""

import re
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"
TAGS = ("div", "section", "main", "nav", "aside")


def test_container_tags_balanced_and_never_negative():
    src = HTML.read_text(encoding="utf-8")
    lines = src.split("\n")
    for tag in TAGS:
        depth = 0
        for no, line in enumerate(lines, 1):
            # 去掉同行注释,避免 <!-- --> 里的示例标签干扰
            code = re.sub(r"<!--.*?-->", "", line)
            o = len(re.findall(r"<%s\b" % tag, code))
            c = len(re.findall(r"</%s>" % tag, code))
            depth += o - c
            assert depth >= 0, (
                f"第 {no} 行出现多余的 </{tag}>(深度变负),"
                f"浏览器会把后续视图逐出 main 导致整页空白"
            )
        assert depth == 0, f"<{tag}> 未闭合干净:最终深度 {depth}(应为 0)"


def test_all_views_inside_main():
    """7 个视图 section 都必须是 main 的直接子级(防结构漂移)。"""
    src = HTML.read_text(encoding="utf-8")
    depth_main = 0
    depth_section = 0
    view_depths = {}
    for no, line in enumerate(src.split("\n"), 1):
        code = re.sub(r"<!--.*?-->", "", line)
        for m in re.finditer(r"<main\b|</main>|<section\b[^>]*id=\"([^\"]+)\"|</section>", code):
            tok = m.group(0)
            if tok.startswith("<main"):
                depth_main += 1
            elif tok == "</main>":
                depth_main -= 1
            elif tok.startswith("<section"):
                depth_section += 1
                if m.group(1) and m.group(1).startswith("view-"):
                    view_depths[m.group(1)] = (depth_main, depth_section)
            else:
                depth_section -= 1
    expected = [f"view-{v}" for v in ("annotate", "progress", "review", "admin", "browse", "export", "help")]
    assert sorted(view_depths) == sorted(expected), f"视图缺失或多出:{sorted(view_depths)}"
    for vid, (dm, ds) in view_depths.items():
        assert (dm, ds) == (1, 1), (
            f"{vid} 的嵌套深度是 main={dm}, section={ds},应为 main=1, section=1"
            f"(直接位于 main 下);否则会被浏览器解析到应用外壳之外"
        )
