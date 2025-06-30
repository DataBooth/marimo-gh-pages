import ast
import re

# --- Config handling ---
import tomllib
from pathlib import Path
from typing import List

from loguru import logger


def load_inline_config(config_path: Path):
    logger.info(f"Loading config from {config_path}")
    with open(config_path, "rb") as f:  # tomllib expects binary mode
        config = tomllib.load(f)
    inline_cfg = config.get("import_inline", {})
    whitelist = set(inline_cfg.get("whitelist", []))
    blacklist = set(inline_cfg.get("blacklist", []))
    logger.debug(f"Whitelist: {whitelist}")
    logger.debug(f"Blacklist: {blacklist}")
    return whitelist, blacklist


def get_decorated_filename(notebook_path: Path, suffix: str = ".inlined.py") -> Path:
    if notebook_path.suffix == ".py":
        return notebook_path.with_name(notebook_path.stem + suffix)
    else:
        return notebook_path.with_name(notebook_path.name + suffix)


def collect_notebook_imports(lines):
    """Return a set of all import statements (normalized) found in the notebook."""
    imports = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            # Normalize by removing extra spaces
            imports.add(" ".join(stripped.split()))
    return imports


# --- Standard library detection ---
def get_stdlib_modules():
    try:
        import sys

        logger.info("Using sys.stdlib_module_names for stdlib detection")
        return set(sys.stdlib_module_names)
    except AttributeError:
        logger.warning("Falling back to hardcoded stdlib module list")
        return {
            "os",
            "sys",
            "math",
            "re",
            "json",
            "time",
            "datetime",
            "itertools",
            "collections",
            "functools",
            "subprocess",
            "threading",
            "multiprocessing",
            "logging",
            "shutil",
            "pathlib",
            "copy",
            "types",
            "typing",
            "enum",
            "abc",
            "unittest",
            "doctest",
            "inspect",
        }


# --- Parse notebook for import statements ---
def find_import_statements(notebook_path: Path) -> List[dict]:
    logger.info(f"Parsing notebook for import statements: {notebook_path}")
    with open(notebook_path, "r") as f:
        lines = f.readlines()
    notebook_imports = collect_notebook_imports(lines)

    import_cells = []
    cell_starts = []
    for i, line in enumerate(lines):
        if line.strip().startswith("@app.cell"):
            cell_starts.append(i)
    cell_starts.append(len(lines))  # sentinel

    for idx in range(len(cell_starts) - 1):
        cell_lines = lines[cell_starts[idx] : cell_starts[idx + 1]]
        code = "".join(cell_lines)
        try:
            tree = ast.parse(code)
        except Exception as e:
            logger.warning(f"Skipping cell {idx} due to parse error: {e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                import_stmt = ast.get_source_segment(code, node)
                import_cells.append(
                    {
                        "cell_idx": idx,
                        "import_type": "from",
                        "stmt": import_stmt,
                        "module": node.module,
                        "names": [n.name for n in node.names],
                        "aliases": [n.asname for n in node.names],
                    }
                )
            elif isinstance(node, ast.Import):
                import_stmt = ast.get_source_segment(code, node)
                for alias in node.names:
                    import_cells.append(
                        {
                            "cell_idx": idx,
                            "import_type": "import",
                            "stmt": import_stmt,
                            "module": alias.name,
                            "names": [alias.name],
                            "aliases": [alias.asname],
                        }
                    )
    logger.info(f"Found {len(import_cells)} import statements")
    return import_cells, notebook_imports


# --- Infer module path and class from import statement ---
def parse_from_import(import_stmt: str) -> (Path, str):
    m = re.match(r"from\s+([\w\.]+)\s+import\s+(\w+)", import_stmt.strip())
    if not m:
        logger.error(f"Could not parse import: {import_stmt}")
        raise ValueError(f"Could not parse import: {import_stmt}")
    module_dotted, class_name = m.groups()
    module_path = Path(*module_dotted.split(".")).with_suffix(".py")
    logger.debug(f"Inferred module path: {module_path}, class: {class_name}")
    return module_path, class_name


# --- Inline class code from module ---
def extract_class_code(
    module_path: Path, class_name: str
) -> (List[str], str, List[str]):
    logger.info(f"Extracting class {class_name} from {module_path}")
    if not module_path.exists():
        logger.error(f"Module file not found: {module_path}")
        raise FileNotFoundError(f"Module file not found: {module_path}")
    with open(module_path, "r") as f:
        code = f.read()
    # Remove CLI/main code
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
        logger.error(f"Class {class_name} not found in {module_path}")
        raise ValueError(f"Class {class_name} not found in {module_path}")
    class_code = match.group(0)
    # Find which imports are needed as cell arguments (aliases)
    cell_args = []
    for imp in import_lines:
        m = re.match(r"import (\S+) as (\S+)", imp)
        if m:
            cell_args.append(m.group(2))
        m = re.match(r"from (\S+) import (\S+) as (\S+)", imp)
        if m:
            cell_args.append(m.group(3))
    logger.success(f"Extracted class {class_name} from {module_path}")
    return import_lines, class_code, cell_args


# --- Main replacement logic ---
def auto_inline_notebook(
    notebook_path: Path,
    config_path: Path,
    project_root: Path = Path("."),
    output_path: Path = None,
):
    logger.info(f"Starting auto-inlining for notebook: {notebook_path}")
    whitelist, blacklist = load_inline_config(config_path)
    stdlib = get_stdlib_modules()
    import_cells, notebook_imports = find_import_statements(notebook_path)

    with open(notebook_path, "r") as f:
        lines = f.readlines()
    cell_starts = [
        i for i, line in enumerate(lines) if line.strip().startswith("@app.cell")
    ]
    cell_starts.append(len(lines))

    replacements = {}
    for imp in import_cells:
        if imp["import_type"] != "from":
            continue
        module_root = imp["module"].split(".")[0]
        should_inline = module_root in blacklist or (
            module_root not in whitelist and module_root not in stdlib
        )
        logger.debug(
            f"Checking import '{imp['stmt']}' (root: {module_root}): should_inline={should_inline}"
        )
        if not should_inline:
            continue
        try:
            module_path, class_name = parse_from_import(imp["stmt"])
        except Exception as e:
            logger.warning(f"Skipping {imp['stmt']}: {e}")
            continue
        try:
            import_lines, class_code, cell_args = extract_class_code(
                project_root / module_path, class_name
            )
        except Exception as e:
            logger.error(f"Error extracting {class_name} from {module_path}: {e}")
            continue
        cell_args_str = ", ".join(cell_args)
        cell_lines = [
            "@app.cell",
            f"def _({cell_args_str}):" if cell_args_str else "def _():",
        ]
        unique_imports = [
            imp_line
            for imp_line in import_lines
            if " ".join(imp_line.split()) not in notebook_imports
        ]
        for imp_line in unique_imports:
            cell_lines.append(f"    {imp_line}")
        notebook_imports.update(
            [" ".join(imp_line.split()) for imp_line in unique_imports]
        )
        cell_lines.append("")

        class_code_indented = "\n".join(
            "    " + l if l.strip() else "" for l in class_code.splitlines()
        )
        cell_lines.append(class_code_indented)
        cell_lines.append(f"    return ({class_name},)\n")
        new_cell_code = "\n".join(cell_lines)
        replacements[imp["cell_idx"]] = new_cell_code
        logger.success(
            f"Prepared inlined cell for {class_name} (cell {imp['cell_idx']})"
        )

    # Apply replacements
    for idx, new_cell in replacements.items():
        logger.info(f"Replacing cell {idx} with inlined code")
        start = cell_starts[idx]
        end = cell_starts[idx + 1]
        lines[start:end] = [new_cell]

    # Determine output file
    if output_path is None:
        output_path = get_decorated_filename(notebook_path)
    logger.info(f"Writing inlined notebook to {output_path}")

    with open(output_path, "w") as f:
        f.writelines(lines)
    logger.success(f"Inlined {len(replacements)} cell(s) in {output_path}")


# --- Example usage ---
auto_inline_notebook(
    notebook_path=Path("notebooks/caternary.py"),
    config_path=Path("config/inline.toml"),
    project_root=Path("."),
)
