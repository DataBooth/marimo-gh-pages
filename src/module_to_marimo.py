import ast
import re
from pathlib import Path


def get_notebook_imports(notebook_path: Path) -> set[str]:
    """Parse the notebook .py file and return a set of imported names/aliases."""
    with open(notebook_path, "r") as f:
        tree = ast.parse(f.read(), filename=str(notebook_path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # add either the alias or the root module
                imports.add(alias.asname or alias.name.split(".")[0])
    return imports


def extract_imports_and_class(module_path: Path, class_name: str):
    """
    Extracts all import statements and the specified class code from a module.
    Returns (set of imports, class code as string).
    """
    with open(module_path, "r") as f:
        code = f.read()

    # Remove main and CLI code
    code = re.sub(
        r"if\s+__name__\s*==\s*[\"']__main__[\"']:\s*\n(?:\s+.+\n?)*",
        "",
        code,
        flags=re.MULTILINE,
    )
    code = re.sub(
        r"def\s+main\s*\([^)]*\):\s*\n(?:\s+.+\n?)*", "", code, flags=re.MULTILINE
    )

    # Find all import statements
    import_lines = []
    other_lines = []
    for line in code.splitlines():
        if line.strip().startswith("import ") or line.strip().startswith("from "):
            # Skip argparse and similar CLI-only imports
            if "argparse" in line:
                continue
            import_lines.append(line.strip())
        else:
            other_lines.append(line)

    # Extract the class code
    class_pattern = re.compile(
        rf"^class {class_name}\b.*?(?=^class |\Z)", re.DOTALL | re.MULTILINE
    )
    match = class_pattern.search("\n".join(other_lines))
    if not match:
        raise ValueError(f"Class {class_name} not found in {module_path}")
    class_code = match.group(0)

    # Parse import aliases for cell arguments
    cell_args = []
    for imp in import_lines:
        m = re.match(r"import (\S+) as (\S+)", imp)
        if m:
            cell_args.append(m.group(2))
        m = re.match(r"from (\S+) import (\S+) as (\S+)", imp)
        if m:
            cell_args.append(m.group(3))
    return import_lines, class_code, cell_args


def generate_marimo_cell(notebook_path: Path, module_path: Path, class_name: str):
    """
    Generates a Marimo cell string that inlines the specified class from the module,
    adds only missing imports, and sets up cell arguments for import aliases.
    """
    # 1. Get notebook's existing imports
    nb_imports = get_notebook_imports(notebook_path)

    # 2. Get module's imports, class code, and needed cell args
    mod_imports, class_code, cell_args = extract_imports_and_class(
        module_path, class_name
    )

    # 3. Only add imports not already present in the notebook
    imports_to_add = []
    for imp in mod_imports:
        # crude check for root module
        root = re.split(
            r"[ .]", imp.replace("import ", "").replace("from ", ""), maxsplit=1
        )[0]
        if root not in nb_imports and "argparse" not in imp:
            imports_to_add.append(imp)

    # 4. Build the cell function
    cell_args_str = ", ".join(cell_args)
    cell_lines = [
        "@app.cell",
        f"def _({cell_args_str}):" if cell_args_str else "def _():",
    ]
    for imp in imports_to_add:
        cell_lines.append(f"    {imp}")
    cell_lines.append("")
    # Indent class code
    class_code_indented = "\n".join(
        "    " + l if l.strip() else "" for l in class_code.splitlines()
    )
    cell_lines.append(class_code_indented)
    cell_lines.append(f"    return ({class_name},)")
    return "\n".join(cell_lines)


# --- Example usage ---
cell_code = generate_marimo_cell(
    notebook_path=Path("notebooks/caternary.py"),
    module_path=Path("local_module/caternary_py/bubble_cosh.py"),
    class_name="Catenary",
)
print(cell_code)
