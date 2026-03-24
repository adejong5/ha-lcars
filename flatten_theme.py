import yamlimport subprocessimport os
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
    """Sends CSS to Lightning CSS for flattening and minification."""
    try:
        process = subprocess.Popen(
            ['lightningcss', '--minify', '--nesting'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, stderr = process.communicate(input=css_text)
        return stdout.strip() if process.returncode == 0 else css_text
    except FileNotFoundError:
        return css_text
def process_node(node):
    """Recursively search for specific keys in the YAML structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            # Match specific card-mod keys OR any key ending in -yaml
            if key in CSS_KEYS or (isinstance(key, str) and key.endswith("-yaml")):
                if isinstance(value, str):
                    print(f"Processing CSS in key: {key}")
                    node[key] = flatten_with_lightning(value)
            else:
                process_node(value)
    elif isinstance(node, list):
        for item in node:
            process_node(item)
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
