import ruamel.yaml
import re
import subprocess
import os
import tempfile
from pathlib import Path
import math

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
    """
    Full round-trip: extract Jinja → minify CSS → restore Jinja.
    If the string contains no Jinja tags, it is minified directly.
 
    Two strategies are used depending on tag type:
 
    - {% block tags %} and {# comments #}: split on these as boundaries and
      minify each CSS segment independently, since they wrap whole blocks/rules.
 
    - {{ value tags }}: substitute with a safe CSS ident before minifying the
      whole string, so surrounding value tokens (e.g. 'px !important') are
      preserved by the minifier.
    """
    if "{%" not in css and "{{" not in css and "{#" not in css:
        return flatten_with_lightning(css)
 
    stripped, tokens = extract_jinja(css)
 
    # Partition placeholders into block-level (split boundaries) vs
    # inline (ident substitution) based on the original tag type.
    block_placeholders: set[str] = set()
    ident_map: dict[str, str] = {}  # ident -> placeholder
 
    for i, token in enumerate(tokens):
        placeholder = _PLACEHOLDER.format(index=i)
        if token.startswith("{%") or token.startswith("{#"):
            block_placeholders.add(placeholder)
        else:
            # {{ }} inline value tag — swap to a CSS-safe ident
            ident = f"JINJATPL{i}VALUE"
            ident_map[ident] = placeholder
            stripped = stripped.replace(placeholder, ident)
 
    # Restore idents → placeholders after minification (done per-segment below)
    def restore_idents(s: str) -> str:
        for ident, placeholder in ident_map.items():
            s = s.replace(ident, placeholder)
        return s
 
    # Split on block-level placeholders and minify each CSS segment.
    # The regex keeps the delimiters in the result list via a capture group.
    split_pattern = "(" + "|".join(re.escape(p) for p in block_placeholders) + ")"
    parts = re.split(split_pattern, stripped) if block_placeholders else [stripped]
 
    minified_parts = []
    for part in parts:
        if part in block_placeholders:
            minified_parts.append(part)       # keep block placeholder verbatim
        elif part.strip():
            minified_parts.append(flatten_with_lightning(part))  # minify real CSS segment
        else:
            minified_parts.append("")         # drop pure-whitespace gaps
 
    rejoined = restore_idents("".join(minified_parts))
    return restore_jinja(rejoined, tokens)
        
def flatten_with_lightning(css_text):
    with tempfile.NamedTemporaryFile(suffix=".css", mode="w", delete=False) as tmp:
        tmp.write(css_text)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["lightningcss", "--error-recovery", "--minify", "--targets", "Safari >=14", tmp_path],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() if result.returncode == 0 else result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)

def process_node(node):
    """Recursively search for specific keys in the YAML structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            # Match specific card-mod keys OR any key ending in -yaml
            if key in CSS_KEYS or (isinstance(key, str) and key.endswith("-yaml")):
                if isinstance(value, str):
                    sub = yaml.safe_load(value)
                    sub = process_subdicts(sub)
                    node[key] = yaml.dump(sub)
            else:
                process_node(value)
    elif isinstance(node, list):
        for item in node:
            process_node(item)
            
def process_subdicts(sub):
    for key, subsub in sub.items():
        if isinstance(subsub,dict):
            print(f"Processing dict: {key}")
            sub[key] = process_subdicts(subsub)
        else:
            print(f"Processing CSS in: {key}")
            print(f"  input is: {subsub}")
            sub[key] = minify_with_jinja(subsub)
            print(f"  output is: {sub[key]}")
    return sub
    
def main():
    input_file = 'lcars.yaml' # Replace with your theme file name
    output_file = 'themes/lcars_min.yaml'

    
    yaml = ruamel.yaml.YAML()
    
    with open(input_file, 'r') as f:
        data = yaml.load(f)

    process_node(data)

    with open(output_file, 'w') as f:
        yaml.dump(data, f)
if __name__ == "__main__":
    main()
