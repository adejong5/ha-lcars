import yaml
import subprocess
import os
import tempfile
from pathlib import Path

# Set of keys known to contain CSS in card-mod themes
CSS_KEYS = {
    "card-mod-card", "card-mod-row", "card-mod-glance", "card-mod-badge",
    "card-mod-heading-badge", "card-mod-assist-chip", "card-mod-element",
    "card-mod-root", "card-mod-view", "card-mod-more-info", "card-mod-sidebar",
    "card-mod-config", "card-mod-panel-custom", "card-mod-top-app-bar-fixed",
    "card-mod-dialog"
}
class MyDumper(yaml.SafeDumper):
    def represent_scalar(self, tag, value, style=None):
        # Use "|" style for multi-line strings to keep YAML readable
        if "\n" in value: style = "|"
        return super().represent_scalar(tag, value, style)
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
                    node[key] = yaml.safe_dump(sub, sort_keys=False, default_flow_style=False)
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
            sub[key] = flatten_with_lightning(subsub)
            print(f"  output is: {sub[key]}")
    return sub
    
def main():
    input_file = 'lcars.yaml' # Replace with your theme file name
    output_file = 'themes/lcars_min.yaml'

    with open(input_file, 'r') as f:
        data = yaml.safe_load(f)

    process_node(data)

    with open(output_file, 'w') as f:
        yaml.dump(data, f, Dumper=MyDumper, sort_keys=False)
if __name__ == "__main__":
    main()
