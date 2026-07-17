import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .platforms import is_youtube_url
from .text_utils import sanitize_filename, sanitize_path_component


DEFAULT_CATEGORIES = ["美食教程"]
DEFAULT_TAGS = ["美食", "教程"]

ANALYSIS_LEAK_PATTERNS = [
    "让我分析",
    "现在我需要",
    "我需要按照",
    "我会",
    "我将",
    "我注意到",
    "关于分类",
    "正文结构",
    "Front-matter:",
    "我倾向于",
    "我建议采用",
    "关键是要保持",
]


CUISINE_CATEGORY_MAP = {
    "川菜": ["中餐", "川菜"],
    "四川": ["中餐", "川菜"],
    "粤菜": ["中餐", "粤菜"],
    "广东": ["中餐", "粤菜"],
    "鲁菜": ["中餐", "鲁菜"],
    "湘菜": ["中餐", "湘菜"],
    "湖南": ["中餐", "湘菜"],
    "淮扬菜": ["中餐", "淮扬菜"],
    "东北菜": ["中餐", "东北菜"],
    "东北": ["中餐", "东北菜"],
    "西北菜": ["中餐", "西北菜"],
    "西北": ["中餐", "西北菜"],
}


CATEGORY_RULES = [
    (["面点", "面食", "面粉", "烙饼", "油饼", "葱花饼", "馅饼", "煎饼", "烧饼", "饼类"], ["面点烘焙", "饼类"]),
    (["包子", "馒头", "花卷", "发糕", "窝头"], ["面点烘焙", "包子馒头"]),
    (["蛋糕", "面包", "吐司", "饼干", "烘焙", "曲奇"], ["面点烘焙", "西式烘焙"]),
    (["汤", "羹", "粥", "煲"], ["中餐", "汤品粥羹"]),
    (["甜品", "糖水", "布丁", "奶冻", "冰粉", "蛋挞"], ["甜品饮品", "甜品"]),
    (["奶茶", "饮品", "果茶", "冰饮", "咖啡"], ["甜品饮品", "奶茶饮品"]),
    (["卤", "卤味", "卤水", "酱牛肉", "酱鸭", "熟食"], ["街头小吃", "卤味熟食"]),
    (["烧烤", "烤串", "炸串", "串串"], ["街头小吃", "炸串烧烤"]),
    (["凉拌", "凉菜", "冷盘", "拌菜"], ["街头小吃", "凉拌冷盘"]),
    (["早餐", "早点", "油条", "豆浆", "饭团"], ["街头小吃", "早餐早点"]),
    (["夜市", "摆摊", "小吃"], ["街头小吃", "夜市摊品"]),
    (["酱料", "蘸料", "料油", "辣椒油", "红油", "高汤", "底料"], ["基础技法", "酱料蘸料"]),
    (["腌制", "泡菜", "酸菜", "咸菜"], ["基础技法", "腌制处理"]),
    (["日韩", "韩式", "日式", "寿司", "泡菜锅"], ["异国料理", "日韩料理"]),
    (["泰式", "越南", "东南亚", "咖喱"], ["异国料理", "东南亚料理"]),
    (["西餐", "意面", "披萨", "牛排", "沙拉"], ["异国料理", "西餐"]),
]


def build_blog_prompt_input(
    transcript_text: str,
    title: str,
    platform: str,
    source: str,
    transcript_source: str,
    youtube_metadata: Optional[dict] = None,
) -> str:
    """Build a metadata-aware input block for blog-style prompts."""
    source_type = normalize_source_type(platform)
    lines = [
        "【文章上下文】",
        f"原始标题：{title}",
        f"来源类型：{source_type}",
        f"文本来源：{transcript_source}",
    ]

    if source_type == "youtube":
        metadata = youtube_metadata or {}
        lines.append(f"来源链接：{metadata.get('webpage_url') or source}")
        if metadata.get("thumbnail"):
            lines.append(f"封面图：{metadata['thumbnail']}")
        if metadata.get("channel"):
            lines.append(f"频道：{metadata['channel']}")
    elif source_type == "local":
        lines.append("来源说明：本地音频/视频文件。不要把本机文件路径写入博客正文或 front-matter。")
    else:
        lines.append(f"来源链接：{source}")

    lines.extend(
        [
            "",
            "【转写稿】",
            transcript_text,
        ]
    )
    return "\n".join(lines)


def format_snack_recipe_article(
    text: str,
    title: str,
    source: str,
    platform: str,
    transcript_source: str,
    youtube_metadata: Optional[dict] = None,
) -> str:
    """Return a Hexo/AnZhiYu-ready Markdown article for food tutorial notes."""
    text = strip_markdown_code_fence(text)
    parsed_frontmatter, body = split_frontmatter(text)
    body = clean_blog_body(body, title, platform)
    body = ensure_nutrition_notice(body, parsed_frontmatter, title)

    frontmatter = build_hexo_frontmatter(
        parsed_frontmatter=parsed_frontmatter,
        title=title,
        source=source,
        platform=platform,
        transcript_source=transcript_source,
        youtube_metadata=youtube_metadata,
    )
    return frontmatter + "\n\n" + body.strip() + "\n"


def validate_snack_recipe_article(text: str) -> list[str]:
    """Return publish-blocking problems for generated snack recipe articles."""
    problems: list[str] = []
    stripped = strip_markdown_code_fence(text)
    parsed_frontmatter, body = split_frontmatter(stripped)

    if not parsed_frontmatter.get("title"):
        problems.append("缺少 front-matter title")

    required_markers = [
        "## 做法速览",
        "## 食材与配方",
        "## 制作流程",
        "{% timeline 制作流程,green %}",
    ]
    for marker in required_markers:
        if marker not in body:
            problems.append(f"缺少必要结构: {marker}")

    leaked = [pattern for pattern in ANALYSIS_LEAK_PATTERNS if pattern in body]
    if leaked:
        problems.append("疑似泄露模型分析过程: " + "、".join(leaked[:5]))

    if len(stripped) > 30000:
        problems.append(f"文章长度异常: {len(stripped)} 字符")

    return problems


def extract_frontmatter_title(text: str, fallback: str = "") -> str:
    """Return the publishable title from a generated Markdown article."""
    text = strip_markdown_code_fence(text)
    parsed_frontmatter, _ = split_frontmatter(text)
    return first_text(parsed_frontmatter.get("title"), fallback)


def replace_frontmatter_field(text: str, key: str, value: Any) -> str:
    """Replace or append a simple front-matter field."""
    stripped = strip_markdown_code_fence(text)
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return stripped

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return stripped

    field_line = format_yaml_field(key, value)[0]
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    replaced = False
    for index in range(1, end_index):
        if pattern.match(lines[index]):
            lines[index] = field_line
            replaced = True
            break

    if not replaced:
        lines.insert(end_index, field_line)

    return "\n".join(lines).rstrip() + "\n"


def make_article_markdown_filename(title: str, fallback: str = "article") -> str:
    """Create a Markdown filename from the article title."""
    stem = sanitize_path_component(first_text(title, fallback))
    return f"{stem[:80].rstrip('. ')}.md"


def strip_markdown_code_fence(text: str) -> str:
    """Remove an enclosing Markdown code fence if the model returned one."""
    stripped = text.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a small useful subset of YAML front-matter."""
    lines = text.lstrip().splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}, text

    raw_frontmatter = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    return parse_simple_yaml(raw_frontmatter), body


def parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse simple scalar and dash-list front-matter fields."""
    data: dict[str, Any] = {}
    current_key: Optional[str] = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        list_match = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if list_match and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(unquote_yaml_value(list_match.group(1)))
            continue

        key_match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if not key_match:
            current_key = None
            continue

        key, value = key_match.groups()
        current_key = key
        if value == "":
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            try:
                data[key] = json.loads(value.replace("'", '"'))
            except json.JSONDecodeError:
                data[key] = [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
        else:
            data[key] = unquote_yaml_value(value)

    return data


def unquote_yaml_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def clean_blog_body(body: str, title: str, platform: str = "") -> str:
    """Remove internal processing notes and sections that should not be published."""
    lines = []
    skipped_first_h1 = False
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if re.match(r"^\*\*(视频链接|提示词|文本来源)\*\*\s*:", stripped):
            continue
        if stripped in {"---", "## 视频转写内容"}:
            continue
        if not skipped_first_h1 and stripped.startswith("# "):
            skipped_first_h1 = True
            continue
        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = remove_section(cleaned, lambda heading, section: "需要人工复核" in heading)
    if normalize_source_type(platform) == "local":
        cleaned = remove_section(cleaned, lambda heading, section: "参考来源" in heading or "来源" in heading)
    cleaned = remove_section(cleaned, should_drop_cost_section)
    cleaned = remove_local_paths(cleaned)
    cleaned = remove_lonely_unmentioned_lines(cleaned)
    cleaned = normalize_markdown_tables(cleaned)
    cleaned = normalize_timeline_blocks(cleaned)
    cleaned = normalize_tab_blocks(cleaned)
    cleaned = normalize_anzhiyu_block_tags(cleaned)
    return collapse_blank_lines(cleaned)


def remove_section(text: str, should_remove) -> str:
    """Remove Markdown sections selected by a predicate."""
    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        heading_match = re.match(r"^(#{2,6})\s+(.+?)\s*$", lines[index])
        if not heading_match:
            result.append(lines[index])
            index += 1
            continue

        start = index
        level = len(heading_match.group(1))
        index += 1
        while index < len(lines):
            next_heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", lines[index])
            if next_heading and len(next_heading.group(1)) <= level:
                break
            index += 1

        section = "\n".join(lines[start:index])
        if not should_remove(heading_match.group(2), section):
            result.extend(lines[start:index])

    return "\n".join(result)


def should_drop_cost_section(heading: str, section: str) -> bool:
    if "成本" not in heading and "定价" not in heading:
        return False
    has_value = bool(re.search(r"(￥|\d+\s*(元|块|毛|斤|克|份|份量|人份|%))", section))
    return "未提及" in section and not has_value


def remove_lonely_unmentioned_lines(text: str) -> str:
    """Drop filler lines that only say information was not mentioned."""
    result = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {"未提及", "- 未提及", "- 暂无", "暂无"}:
            continue
        result.append(line)
    return "\n".join(result)


def remove_local_paths(text: str) -> str:
    """Remove accidental Windows local paths from publishable article text."""
    text = re.sub(r"[A-Za-z]:\\[^\s`，。；；、)）\]}]+", "", text)
    return text


def collapse_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text


def normalize_markdown_tables(text: str) -> str:
    """Normalize simple pipe tables so Markdown renderers can parse them."""
    lines = text.splitlines()
    result: list[str] = []
    index = 0

    while index < len(lines):
        if index + 1 < len(lines) and is_pipe_table_header(lines[index], lines[index + 1]):
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and is_pipe_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            result.extend(normalize_pipe_table(table_lines))
            continue

        result.append(lines[index])
        index += 1

    return "\n".join(result)


def is_pipe_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def split_pipe_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def is_table_separator_cell(cell: str) -> bool:
    return bool(re.fullmatch(r":?-{3,}:?|:?-{2,}:?", cell.strip()))


def is_pipe_table_header(header_line: str, separator_line: str) -> bool:
    if not is_pipe_table_row(header_line) or not is_pipe_table_row(separator_line):
        return False
    header_cells = split_pipe_table_row(header_line)
    separator_cells = split_pipe_table_row(separator_line)
    if not header_cells or not separator_cells:
        return False
    separator_like_count = sum(1 for cell in separator_cells if is_table_separator_cell(cell))
    return separator_like_count >= max(1, len(separator_cells) - 1)


def normalize_pipe_table_row(line: str, column_count: int) -> str:
    cells = split_pipe_table_row(line)
    if len(cells) < column_count:
        cells.extend([""] * (column_count - len(cells)))
    elif len(cells) > column_count:
        cells = cells[: column_count - 1] + [" | ".join(cells[column_count - 1 :])]
    return "| " + " | ".join(cells) + " |"


def normalize_pipe_table(table_lines: list[str]) -> list[str]:
    header_cells = split_pipe_table_row(table_lines[0])
    separator_cells = split_pipe_table_row(table_lines[1])
    data_rows = [split_pipe_table_row(line) for line in table_lines[2:]]
    column_count = max(
        len(header_cells),
        len(separator_cells),
        *(len(row) for row in data_rows),
    )

    normalized = [normalize_pipe_table_row(table_lines[0], column_count)]
    normalized.append("| " + " | ".join([":--"] * column_count) + " |")
    normalized.extend(normalize_pipe_table_row(line, column_count) for line in table_lines[2:])
    return normalized


def normalize_timeline_blocks(text: str) -> str:
    """Ensure AnZhiYu timeline child comments are properly closed."""
    lines = text.splitlines()
    result: list[str] = []
    in_timeline = False
    child_open = False

    for line in lines:
        stripped = line.strip()
        is_timeline_start = stripped.startswith("{% timeline ")
        is_timeline_end = stripped == "{% endtimeline %}"
        is_child_start = re.match(r"^<!--\s*timeline\s+.+?\s*-->$", stripped)
        is_child_end = re.match(r"^<!--\s*endtimeline\s*-->$", stripped)

        if is_timeline_start:
            in_timeline = True
            child_open = False
            result.append(line)
            continue

        if in_timeline and is_child_start:
            if child_open:
                result.append("<!-- endtimeline -->")
                result.append("")
            child_open = True
            result.append(line)
            continue

        if in_timeline and is_child_end:
            if child_open:
                result.append(line)
                child_open = False
            continue

        if in_timeline and is_timeline_end:
            if child_open:
                result.append("<!-- endtimeline -->")
                result.append("")
                child_open = False
            result.append(line)
            in_timeline = False
            continue

        result.append(line)

    if in_timeline and child_open:
        result.append("<!-- endtimeline -->")
    if in_timeline:
        result.append("{% endtimeline %}")

    return "\n".join(result)


def normalize_tab_blocks(text: str) -> str:
    """Ensure AnZhiYu tabs child comments are properly closed."""
    return normalize_comment_child_blocks(
        text=text,
        outer_tags=("tabs", "subtabs", "subsubtabs"),
        child_name="tab",
        child_end="endtab",
    )


def normalize_comment_child_blocks(
    text: str,
    outer_tags: tuple[str, ...],
    child_name: str,
    child_end: str,
) -> str:
    """Close comment-delimited children inside AnZhiYu container tags."""
    lines = text.splitlines()
    result: list[str] = []
    open_outer_tag = ""
    child_open = False
    outer_start = re.compile(r"^\s*\{%\s*(" + "|".join(map(re.escape, outer_tags)) + r")\b.*%\}\s*$")
    outer_end = re.compile(r"^\s*\{%\s*end(" + "|".join(map(re.escape, outer_tags)) + r")\s*%\}\s*$")
    child_start = re.compile(r"^<!--\s*" + re.escape(child_name) + r"\s+.+?\s*-->$")
    child_close = re.compile(r"^<!--\s*" + re.escape(child_end) + r"\s*-->$")

    for line in lines:
        stripped = line.strip()
        start_match = outer_start.match(stripped)
        end_match = outer_end.match(stripped)
        is_child_start = bool(child_start.match(stripped))
        is_child_end = bool(child_close.match(stripped))

        if start_match:
            if open_outer_tag:
                if child_open:
                    result.append(f"<!-- {child_end} -->")
                    result.append("")
                    child_open = False
                result.append(f"{{% end{open_outer_tag} %}}")
                result.append("")
            open_outer_tag = start_match.group(1)
            child_open = False
            result.append(line)
            continue

        if open_outer_tag and is_child_start:
            if child_open:
                result.append(f"<!-- {child_end} -->")
                result.append("")
            child_open = True
            result.append(line)
            continue

        if open_outer_tag and is_child_end:
            if child_open:
                result.append(line)
                child_open = False
            continue

        if open_outer_tag and end_match:
            if child_open:
                result.append(f"<!-- {child_end} -->")
                result.append("")
                child_open = False
            result.append(line)
            open_outer_tag = ""
            continue

        result.append(line)

    if open_outer_tag:
        if child_open:
            result.append(f"<!-- {child_end} -->")
        result.append(f"{{% end{open_outer_tag} %}}")

    return "\n".join(result)


def normalize_anzhiyu_block_tags(text: str) -> str:
    """Close common Hexo/AnZhiYu block tags when the model omits end tags."""
    tag_pairs = {
        "note": "endnote",
        "subnote": "endsubnote",
        "folding": "endfolding",
        "timeline": "endtimeline",
        "tabs": "endtabs",
        "subtabs": "endsubtabs",
        "subsubtabs": "endsubsubtabs",
    }
    start_re = re.compile(r"^\s*\{%\s*(" + "|".join(map(re.escape, tag_pairs)) + r")\b.*%\}\s*$")
    end_re = re.compile(r"^\s*\{%\s*(end" + "|end".join(map(re.escape, tag_pairs)) + r")\s*%\}\s*$")
    heading_re = re.compile(r"^#{2,6}\s+\S")
    stack: list[str] = []
    result: list[str] = []

    def close_top() -> None:
        if stack:
            result.append(f"{{% {tag_pairs[stack.pop()]} %}}")

    for line in text.splitlines():
        stripped = line.strip()
        start_match = start_re.match(stripped)
        end_match = end_re.match(stripped)

        if stack and (heading_re.match(stripped) or start_match):
            while stack:
                close_top()
            if result and result[-1] != "":
                result.append("")

        if start_match:
            stack.append(start_match.group(1))
            result.append(line)
            continue

        if end_match:
            end_tag = end_match.group(1)
            expected_start = next((start for start, end in tag_pairs.items() if end == end_tag), "")
            if expected_start in stack:
                while stack and stack[-1] != expected_start:
                    close_top()
                result.append(line)
                stack.pop()
            else:
                result.append(line)
            continue

        result.append(line)

    while stack:
        close_top()

    return "\n".join(result)


def ensure_nutrition_notice(body: str, parsed_frontmatter: dict[str, Any], fallback_title: str) -> str:
    """Append a restrained nutrition/eating notice when the model omitted it."""
    if "营养与食用提醒" in body:
        return body

    title = first_text(parsed_frontmatter.get("title"), fallback_title)
    tags = normalize_list(parsed_frontmatter.get("tags"))
    dish_type = first_text(parsed_frontmatter.get("dish_type"))
    cooking_method = normalize_list(parsed_frontmatter.get("cooking_method"))
    text = " ".join([title, dish_type, " ".join(tags), " ".join(cooking_method), body[:1200]])
    rows = build_nutrition_notice_rows(text)
    notice = "\n".join(
        [
            "{% folding green, 营养与食用提醒 %}",
            "",
            "| 角度 | 提醒 |",
            "| :-- | :-- |",
            *[f"| {label} | {value} |" for label, value in rows],
            "",
            "{% endfolding %}",
        ]
    )

    insert_before = re.search(r"\n\{% folding yellow, 批量制作与出餐建议 %\}", body)
    if insert_before:
        return body[: insert_before.start()].rstrip() + "\n\n" + notice + "\n" + body[insert_before.start() :]
    return body.rstrip() + "\n\n" + notice


def build_nutrition_notice_rows(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    if any(keyword in text for keyword in ["面粉", "面点", "面食", "饼", "包子", "馒头", "米饭", "面条"]):
        rows.append(("营养特点", "这类做法以主食和碳水化合物为主，更适合作为一餐中的主食部分。"))
        rows.append(("需要留意的人群", "需要控制主食量的人建议按份量少量食用；对小麦或麸质敏感者不适合含面粉版本。"))
        rows.append(("搭配建议", "可以搭配鸡蛋、豆制品、牛奶或蔬菜，让一餐里的蛋白质和蔬菜更充足。"))
    elif any(keyword in text for keyword in ["甜品", "糖", "奶茶", "饮品", "糖水", "蛋糕", "饼干"]):
        rows.append(("营养特点", "这类做法通常更偏甜点或饮品，适合作为加餐或少量分享。"))
        rows.append(("控糖建议", "可以酌情减少糖量或选择低糖版本，需要控糖的人建议少量食用。"))
    elif any(keyword in text for keyword in ["肉", "鸡", "鸭", "牛", "羊", "猪", "鱼", "虾"]):
        rows.append(("营养特点", "这类菜通常能提供一定蛋白质，具体油脂高低取决于部位和烹调用油。"))
        rows.append(("搭配建议", "建议搭配蔬菜和主食，避免一餐只吃肉类或重口味配菜。"))
    else:
        rows.append(("营养特点", "这道菜的营养特点主要取决于主料、油盐用量和实际食用份量。"))

    if any(keyword in text for keyword in ["炸", "油炸", "煎", "烙", "红油", "料油", "油酥"]):
        rows.append(("控油建议", "想吃得清爽一些，可以减少油量，用少量多次刷油或控油的方式降低油腻感。"))
    if any(keyword in text for keyword in ["酱油", "盐", "豆瓣", "火锅底料", "卤", "腌", "咸"]):
        rows.append(("控盐建议", "调味料本身可能带盐，后续加盐要保守，需要控盐的人建议减少酱油、盐和复合调料。"))
    if any(keyword in text for keyword in ["田螺", "贝", "虾", "蟹", "海鲜", "鱼"]):
        rows.append(("食材风险", "水产、贝类或田螺类食材要充分清洗并彻底加热，对相关食材过敏者应避免食用。"))
    if any(keyword in text for keyword in ["鸡蛋", "蛋"]):
        rows.append(("过敏提醒", "含鸡蛋做法不适合对蛋类过敏的人。"))
    if any(keyword in text for keyword in ["牛奶", "奶油", "黄油", "芝士", "奶酪"]):
        rows.append(("过敏提醒", "含乳制品做法不适合对牛奶或乳制品过敏的人。"))

    deduped: list[tuple[str, str]] = []
    seen = set()
    for label, value in rows:
        key = (label, value)
        if key not in seen:
            deduped.append((label, value))
            seen.add(key)
    return deduped[:6]


def build_hexo_frontmatter(
    parsed_frontmatter: dict[str, Any],
    title: str,
    source: str,
    platform: str,
    transcript_source: str,
    youtube_metadata: Optional[dict] = None,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = youtube_metadata or {}
    source_type = normalize_source_type(platform)
    article_title = first_text(parsed_frontmatter.get("title"), title)
    tags = normalize_list(parsed_frontmatter.get("tags")) or DEFAULT_TAGS
    dish_type = first_text(parsed_frontmatter.get("dish_type"))
    cuisine = first_text(parsed_frontmatter.get("cuisine"))
    cooking_method = normalize_list(parsed_frontmatter.get("cooking_method"))
    scene = normalize_list(parsed_frontmatter.get("scene"))
    categories = refine_food_categories(
        categories=normalize_list(parsed_frontmatter.get("categories")) or DEFAULT_CATEGORIES,
        title=article_title,
        tags=tags,
        dish_type=dish_type,
        cuisine=cuisine,
        cooking_method=cooking_method,
        scene=scene,
    )
    cover = first_text(parsed_frontmatter.get("cover"), metadata.get("thumbnail"))

    fields: list[tuple[str, Any]] = [
        ("layout", "post"),
        ("title", article_title),
        ("date", parsed_frontmatter.get("date") or now),
        ("updated", now),
        ("categories", categories[:3]),
        ("tags", tags[:12]),
    ]

    if cover:
        fields.append(("cover", cover))

    fields.extend(
        [
            ("permalink", first_text(parsed_frontmatter.get("permalink"), make_permalink(article_title, source))),
            ("comments", parse_bool(parsed_frontmatter.get("comments"), True)),
            ("toc", parse_bool(parsed_frontmatter.get("toc"), True)),
            ("toc_number", parse_bool(parsed_frontmatter.get("toc_number"), True)),
            ("copyright", parse_bool(parsed_frontmatter.get("copyright"), True)),
        ]
    )

    for key, value in (
        ("cuisine", cuisine),
        ("dish_type", dish_type),
        ("difficulty", first_text(parsed_frontmatter.get("difficulty"))),
    ):
        if value:
            fields.append((key, value))

    for key, value in (
        ("cooking_method", cooking_method),
        ("scene", scene),
        ("ai", normalize_list(parsed_frontmatter.get("ai"))),
    ):
        if value:
            fields.append((key, value[:8]))

    fields.append(("source_type", source_type))
    if source_type != "local":
        fields.append(("source_url", metadata.get("webpage_url") or source))
    fields.append(("source_title", metadata.get("title") or title))
    fields.append(("transcript_source", transcript_source))

    lines = ["---"]
    for key, value in fields:
        lines.extend(format_yaml_field(key, value))
    lines.append("---")
    return "\n".join(lines)


def format_yaml_field(key: str, value: Any) -> list[str]:
    if isinstance(value, bool):
        return [f"{key}: {'true' if value else 'false'}"]
    if isinstance(value, list):
        lines = [f"{key}:"]
        for item in value:
            if item not in (None, ""):
                lines.append(f"  - {yaml_scalar(item)}")
        return lines if len(lines) > 1 else []
    if value in (None, ""):
        return []
    return [f"{key}: {yaml_scalar(value)}"]


def refine_food_categories(
    categories: list[str],
    title: str,
    tags: list[str],
    dish_type: str = "",
    cuisine: str = "",
    cooking_method: Optional[list[str]] = None,
    scene: Optional[list[str]] = None,
) -> list[str]:
    """Apply conservative food-category corrections for stable blog navigation."""
    cooking_method = cooking_method or []
    scene = scene or []
    text = " ".join(
        [
            title,
            dish_type,
            cuisine,
            " ".join(tags),
            " ".join(cooking_method),
            " ".join(scene),
            " ".join(categories),
        ]
    )

    cuisine_category = infer_cuisine_category(cuisine, text)
    if cuisine_category and not should_prefer_type_category(text):
        return cuisine_category

    for keywords, category in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category

    if cuisine_category:
        return cuisine_category

    if dish_type in {"家常菜", "热菜", "炒菜"}:
        return ["中餐", "家常菜"]

    return categories[:3] if categories else DEFAULT_CATEGORIES


def infer_cuisine_category(cuisine: str, text: str) -> Optional[list[str]]:
    for keyword, category in CUISINE_CATEGORY_MAP.items():
        if keyword in cuisine or keyword in text:
            return category
    return None


def should_prefer_type_category(text: str) -> bool:
    """Let strong dish-type categories override broad regional cuisine."""
    strong_type_keywords = [
        "面点",
        "面食",
        "饼",
        "包子",
        "馒头",
        "甜品",
        "饮品",
        "卤",
        "烧烤",
        "炸串",
        "酱料",
        "蘸料",
        "高汤",
        "底料",
    ]
    return any(keyword in text for keyword in strong_type_keywords)


def yaml_scalar(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def normalize_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value.strip()] if value.strip() else []
    return [str(value).strip()]


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            value = value[0] if value else ""
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "y"}:
            return True
        if lowered in {"false", "no", "0", "n"}:
            return False
    return default


def normalize_source_type(platform: str) -> str:
    lowered = platform.lower()
    if lowered == "youtube":
        return "youtube"
    if lowered == "local":
        return "local"
    if lowered == "bilibili":
        return "bilibili"
    return lowered or "unknown"


def make_permalink(title: str, source: str) -> str:
    video_id = extract_youtube_id(source)
    if video_id:
        return f"food/{video_id}/"

    source_hash = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:8]
    slug = sanitize_filename(Path(title).stem, 40).replace("_", "-").strip("-").lower()
    if not slug:
        slug = "recipe"
    return f"food/{slug}-{source_hash}/"


def extract_youtube_id(source: str) -> str:
    if not is_youtube_url(source):
        return ""
    parsed = urlparse(source)
    if parsed.hostname and "youtu.be" in parsed.hostname:
        return parsed.path.strip("/")
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    return query_id.strip()
