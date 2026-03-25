import ruamel.yaml
import re
import subprocess
import tempfile
from pathlib import Path
from ruamel.yaml.constructor import RoundTripConstructor

# Set of keys known to contain CSS in card-mod themes
CSS_KEYS = {
    "card-mod-card", "card-mod-row", "card-mod-glance", "card-mod-badge",
    "card-mod-heading-badge", "card-mod-assist-chip", "card-mod-element",
    "card-mod-root", "card-mod-view", "card-mod-more-info", "card-mod-sidebar",
    "card-mod-config", "card-mod-panel-custom", "card-mod-top-app-bar-fixed",
    "card-mod-dialog"
}

# Matches all three Jinja tag styles:  {% ... %}  {{ ... }}  {# ... #}
# Uses a non-greedy match and DOTALL so multi-line tags are handled too.
_JINJA_RE = re.compile(r"(\{(?:%|-|#|\{).*?(?:%|-|#|\})\})", re.DOTALL)
# Matches a CSS string value containing a {{ }} expression, e.g. content:"...{{ }}..."
_STRING_WITH_EXPR_RE = re.compile(r'("(?:[^"\\]|\\.)*\{\{.*?\}\}(?:[^"\\]|\\.)*")', re.DOTALL)

# Matches entire {% if %} ... {% endif %} blocks, including all content inside.
_BLOCK_RE = re.compile(r"(\{%-?\s*if\b.*?-?%\}.*?\{%-?\s*endif\s*-?%\})", re.DOTALL)

# Placeholder format — unlikely to appear in real CSS.
_PLACEHOLDER = "__JINJA_{index}__"


def extract_jinja(css: str) -> tuple[str, list[str]]:
    """
    Replace every Jinja tag in *css* with a numbered placeholder.

    Returns:
        stripped   – CSS string safe to pass to a minifier
        tokens     – ordered list of the original Jinja tag strings
    """
    tokens: list[str] = []

    def replacer(match: re.Match) -> str:
        tokens.append(match.group(0))
        return _PLACEHOLDER.format(index=len(tokens) - 1)

    stripped = _JINJA_RE.sub(replacer, css)
    return stripped, tokens


def restore_jinja(css: str, tokens: list[str]) -> str:
    """
    Substitute placeholders back with their original Jinja tags.
    Strips leading whitespace the minifier may have added before a placeholder,
    but leaves trailing characters (e.g. 'px') untouched.
    """
    for index, token in enumerate(tokens):
        placeholder = _PLACEHOLDER.format(index=index)
        # \s* on the left only — don't consume characters after the placeholder
        # (e.g. 'px' in '--lcars-border: __JINJA_0__px')
        css = re.sub(rf"\s*{re.escape(placeholder)}", token, css)
    return css

def minify_with_jinja(css: str) -> str:
    if "{%" not in css and "{{" not in css and "{#" not in css:
        return flatten_with_lightning(css)

    # Step 1: lift {% if %}...{% endif %} blocks out wholesale.
    block_tokens: list[str] = []

    def lift_block(match: re.Match) -> str:
        block_tokens.append(match.group(0))
        return _PLACEHOLDER.format(index=len(block_tokens) - 1)

    stripped = _BLOCK_RE.sub(lift_block, css)
    print("input is")
    print({stripped})

    # Step 2: lift entire CSS string values containing {{ }} out wholesale,
    # so lightningcss never sees the Jinja expression inside a string literal.
    string_tokens: list[str] = []

    def lift_string(match: re.Match) -> str:
        string_tokens.append(match.group(0))
        return f"JINJASTR{len(string_tokens) - 1}VALUE"

    stripped = _STRING_WITH_EXPR_RE.sub(lift_string, stripped)

    # Step 3: replace remaining {{ }} inline value tags with CSS-safe idents.
    stripped, inline_tokens = extract_jinja(stripped)
    ident_map: dict[str, str] = {}

    for i, token in enumerate(inline_tokens):
        placeholder = _PLACEHOLDER.format(index=i)
        ident = f"JINJATPL{i}VALUE"
        ident_map[ident] = placeholder
        stripped = stripped.replace(placeholder, ident)

    # Step 4: minify the now-clean CSS.
    minified = flatten_with_lightning(stripped)

    # Step 5: restore {{ }} idents back to tokens.
    for ident, placeholder in ident_map.items():
        minified = minified.replace(ident, placeholder)
    minified = restore_jinja(minified, inline_tokens)

    # Step 6: restore string values containing {{ }} verbatim.
    for i, string_val in enumerate(string_tokens):
        minified = minified.replace(f"JINJASTR{i}VALUE", string_val)

    # Step 7: restore {% if %}...{% endif %} blocks verbatim.
    for i, block in enumerate(block_tokens):
        minified = minified.replace(_PLACEHOLDER.format(index=i), block)

    return minified
    
def flatten_with_lightning(css_text):
    with tempfile.NamedTemporaryFile(suffix=".css", mode="w", delete=False) as tmp:
        tmp.write(css_text)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["lightningcss", "--targets", "Safari >=14", tmp_path],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() if result.returncode == 0 else result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def make_literal(s: str) -> ruamel.yaml.scalarstring.LiteralScalarString:
    """Wrap a string as a ruamel literal block scalar (the | style)."""
    return ruamel.yaml.scalarstring.LiteralScalarString(s)


def process_css_subdict(sub: dict) -> dict:
    """
    Recursively walk the sub-dict parsed from a CSS_KEY's string value.
    Every leaf string is treated as CSS and minified.
    Every value is re-tagged as a literal block scalar after processing.
    """
    for key in sub:
        value = sub[key]
        if isinstance(value, dict):
            process_css_subdict(value)
        elif isinstance(value, str):
            print(f"  Minifying CSS under key: {key}")
            sub[key] = make_literal(minify_with_jinja(value))
    return sub


def process_node(node):
    """
    Recursively walk the outer YAML structure looking for CSS_KEY matches.
    Only CSS_KEY-matched (or -yaml-suffixed) string values are touched;
    everything else is left completely unchanged.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            is_css_key = key in CSS_KEYS or (isinstance(key, str) and key.endswith("-yaml"))
            if is_css_key and isinstance(value, str):
                # Parse the CSS key's string value as its own YAML document
                inner_yaml = ruamel.yaml.YAML()
                inner_yaml.preserve_quotes = True
                sub = inner_yaml.load(value)
                if isinstance(sub, dict):
                    process_css_subdict(sub)
                    # Dump the sub-dict back to a YAML string using literal scalars
                    stream = ruamel.yaml.compat.StringIO()
                    inner_yaml.dump(sub, stream)
                    node[key] = make_literal(stream.getvalue())
            elif not is_css_key:
                # Not a CSS key — recurse to find CSS keys deeper in the tree
                process_node(value)
    elif isinstance(node, list):
        for item in node:
            process_node(item)


def main():
    input_file = 'lcars.yaml'
    output_file = 'themes/lcars_min.yaml'

    RoundTripConstructor.flatten_mapping = lambda self, node: None

    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    with open(input_file, 'r') as f:
        data = yaml.load(f)

    # Find the card-mod CSS key directly — it's the only place CSS lives.
    card_mod_css_key = next(k for k in data if 'card-mod CSS' in k)
    process_node(data[card_mod_css_key])

    with open(output_file, 'wb') as f:
        yaml.dump(data, f)


if __name__ == "__main__":
    main()
