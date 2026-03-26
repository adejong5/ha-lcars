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

# For {% %} statements — valid anywhere in CSS including top level
_STATEMENT_PLACEHOLDER = "jinja-stmt-{index}{{--s:0}}"

# For {{ }} expressions — valid as a CSS value token
_EXPRESSION_PLACEHOLDER = "__JINJA_EXPR_{index}__"


def minify_with_jinja(css: str) -> str:
    if "{%" not in css and "{{" not in css and "{#" not in css:
        return flatten_with_lightning(css)

    # Step 1: lift entire {% if %}...{% endif %} blocks (including {% else %})
    # out wholesale as a single top-level-safe comment placeholder.
    block_tokens: list[str] = []

    def lift_block(match: re.Match) -> str:
        block_tokens.append(match.group(0))
        return _STATEMENT_PLACEHOLDER.format(index=len(block_tokens) - 1)

    stripped = _BLOCK_RE.sub(lift_block, css)
    print("After Block RE")
    print(stripped)

    # Step 2: replace remaining {{ }} expression tags with CSS-safe idents.
    inline_tokens: list[str] = []

    def lift_expression(match: re.Match) -> str:
        inline_tokens.append(match.group(0))
        return _EXPRESSION_PLACEHOLDER.format(index=len(inline_tokens) - 1)

    stripped = _JINJA_RE.sub(lift_expression, stripped)
    print("Asfter Jinja RE")
    print(stripped)

    # Step 3: minify the now-clean CSS.
    minified = flatten_with_lightning(stripped)

    # Step 4: restore {{ }} expressions.
    for i, token in enumerate(inline_tokens):
        placeholder = _EXPRESSION_PLACEHOLDER.format(index=i)
        minified = re.sub(rf"\s*{re.escape(placeholder)}", token, minified)

    # Step 5: restore {% if %}...{% endif %} blocks verbatim.
    for i, token in enumerate(block_tokens):
      minified = re.sub(
        rf"\s*jinja-stmt-{i}\s*\{{.*?\}}",
        token,
        minified,
        flags=re.DOTALL
      )
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
    for key, value in sub.items():
        if isinstance(value, dict):
            process_css_subdict(value)
        elif isinstance(value, str):
            print(f"  Minifying CSS under key: {key}")
            sub[key] = make_literal(minify_with_jinja(value))
    return sub

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
    for key, value in data[card_mod_css_key].items():
        #key is *-yaml:
        # value is string of a dict
        # Parse the CSS key's string value as its own YAML document
        inner_yaml = ruamel.yaml.YAML()
        inner_yaml.preserve_quotes = True
        sub = inner_yaml.load(value)

        process_css_subdict(sub)
        
        # Dump the sub-dict back to a YAML string using literal scalars
        stream = ruamel.yaml.compat.StringIO()
        inner_yaml.dump(sub, stream)
        data[card_mod_css_key][key] = make_literal(stream.getvalue())

    with open(output_file, 'wb') as f:
        yaml.dump(data, f)


if __name__ == "__main__":
    main()
