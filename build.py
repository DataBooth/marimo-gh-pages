import os
import subprocess
import tomllib
from pathlib import Path
from typing import Dict, List, Optional
import jinja2
from dotenv import load_dotenv
from loguru import logger
import shutil

# import httpx
import fire

# Load environment variables from .env
load_dotenv()

import ast
from pathlib import Path


def find_local_imports(
    notebook_path: Path, base_package: str = "local_module"
) -> list[Path]:
    """
    Parse a notebook .py file and return a list of Paths to local modules it imports.
    Only imports starting with `base_package` are considered.
    """
    with open(notebook_path, "r") as f:
        tree = ast.parse(f.read(), filename=str(notebook_path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(base_package):
                # e.g. from local_module.caternary_py.bubble_cosh import Catenary
                module_path = Path(
                    *node.module.split(".")
                )  # local_module/caternary_py/bubble_cosh
                imports.append(module_path.with_suffix(".py"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(base_package):
                    # e.g. import local_module.caternary_py.bubble_cosh
                    module_path = Path(*alias.name.split("."))
                    imports.append(module_path.with_suffix(".py"))
    return imports


# --- Config Loader ---


class ConfigLoader:
    """Loads and validates configuration from TOML file"""

    def __init__(self, config_path: Path = Path("config.toml")):
        self.config = self._load_config(config_path)
        self._validate_config()

    def _load_config(self, config_path: Path) -> dict:
        if config_path.exists():
            with open(config_path, "rb") as f:
                return tomllib.load(f)
        # Default config if file not found
        return {
            "global": {
                "output_dir": "_site",
                "template": "templates/tailwind.html.j2",
                "notebooks_dir": "notebooks",
                "apps_dir": "apps",
                "assets_dir": "public",
            },
            "targets": {
                "github_pages": {"enabled": True, "dir": "_site/github_pages"},
                "static_site": {
                    "enabled": False,
                    "dir": "_site/static_site",
                    "static_site_dir": "",
                },
                "huggingface": {
                    "enabled": False,
                    "dir": "_site/huggingface",
                    "repo_id": "",
                },
                "local": {"enabled": True, "dir": "_site/local"},
                "posit_connect": {
                    "enabled": False,
                    "dir": "_site/posit_connect",
                    "connect_url": "",
                },
            },
        }

    def _validate_config(self) -> None:
        output_dir = Path(self.get("global", "output_dir", "_site"))
        output_dir.mkdir(parents=True, exist_ok=True)
        for target, config in self.config.get("targets", {}).items():
            if config.get("enabled", False):
                target_dir = Path(config["dir"])
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "notebooks").mkdir(exist_ok=True)
                (target_dir / "apps").mkdir(exist_ok=True)
                (target_dir / "assets").mkdir(exist_ok=True)
                if not (target_dir / "README.md").exists():
                    (target_dir / "README.md").write_text(
                        f"# {target.replace('_', ' ').title()} Target\n"
                    )

    def get(self, section: str, key: str = None, default: Optional[any] = None) -> any:
        section_data = self.config.get(section, None)
        print(f"Config section: {section}, key: {key}, default: {default}")
        if section_data is None:
            return default
        if key is None:
            return section_data
        if not isinstance(key, str):
            raise TypeError(f"Config key must be a string, got {type(key)}")
        return section_data.get(key, default)


# --- Notebook Exporter ---


class NotebookExporter:
    """Handles exporting marimo notebooks to HTML/WASM"""

    def __init__(self, config: ConfigLoader):
        self.config = config

    def export_notebook(
        self, notebook_path: Path, output_dir: Path, as_app: bool
    ) -> Optional[Path]:
        output_file = output_dir / notebook_path.with_suffix(".html").name
        cmd = [
            "uvx",
            "marimo",
            "export",
            "html-wasm",
            "--sandbox",
            "--mode",
            "run" if as_app else "edit",
        ]
        if as_app:
            cmd.append("--no-show-code")
        cmd += [str(notebook_path), "-o", str(output_file)]
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.success(f"Exported {notebook_path.name} to {output_file}")
            return output_file
        except subprocess.CalledProcessError as e:
            logger.error(f"Export failed for {notebook_path}: {e.stderr}")
            return None

    def export_folder(
        self, folder_name: str, target_dir: Path, as_app: bool
    ) -> List[Dict[str, str]]:
        base_dir = Path(self.config.get("global", folder_name, folder_name))
        if not base_dir.exists():
            logger.warning(f"Directory not found: {base_dir}")
            return []
        results = []
        for notebook in base_dir.rglob("*.py"):
            output_path = self.export_notebook(
                notebook, target_dir / ("apps" if as_app else "notebooks"), as_app
            )
            if output_path:
                results.append(
                    {
                        "display_name": notebook.stem.replace("_", " ").title(),
                        "html_path": output_path.relative_to(target_dir).as_posix(),
                        "source_path": str(notebook),
                    }
                )
        return results


# --- Index Generator ---


class IndexGenerator:
    """Generates index.html using Jinja templates"""

    def __init__(self, template_path: Path):
        self.template_path = template_path

    def generate(
        self, output_dir: Path, notebooks: List[dict], apps: List[dict]
    ) -> Path:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_path.parent),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )
        template = env.get_template(self.template_path.name)
        index_file = output_dir / "index.html"
        index_file.write_text(template.render(notebooks=notebooks, apps=apps))
        logger.info(f"Generated index at {index_file}")
        return index_file


# --- Publisher Abstract Base and Implementations ---

from abc import ABC, abstractmethod


class Publisher(ABC):
    """Abstract base class for all publishers."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def publish(self, target_dir: Path) -> bool:
        pass

    def log_start(self, target_name: str):
        logger.info(f"Starting publish for {target_name}")

    def log_success(self, target_name: str):
        logger.success(f"Publish for {target_name} completed successfully")


class GitHubPagesPublisher(Publisher):
    """Handled by CI - just validate structure"""

    def publish(self, target_dir: Path) -> bool:
        self.log_start("GitHub Pages")
        if not (target_dir / ".nojekyll").exists():
            (target_dir / ".nojekyll").touch()
        logger.info("GitHub Pages publishing handled by CI workflow")
        self.log_success("GitHub Pages")
        return True


class StaticSitePublisher(Publisher):
    """Copies files to a static site directory (e.g. for Zola, Hugo, etc.)"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.static_site_dir = Path(config.get("static_site_dir", ""))

    def publish(self, target_dir: Path) -> bool:
        self.log_start("Static Site")
        if not self.static_site_dir.exists():
            logger.error(f"Static site directory not found: {self.static_site_dir}")
            return False
        for item in target_dir.iterdir():
            if item.is_file():
                target = self.static_site_dir / item.name
                shutil.copy2(item, target)
        self.log_success("Static Site")
        return True


class HuggingFacePublisher(Publisher):
    """Publishes to Hugging Face Spaces using huggingface_hub"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.repo_id = config.get("repo_id", "")

    def publish(self, target_dir: Path) -> bool:
        self.log_start("Hugging Face")
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=os.getenv("HF_TOKEN"))
            api.upload_folder(
                repo_id=self.repo_id,
                folder_path=target_dir,
                path_in_repo="",
                repo_type="space",
                commit_message="Update static Marimo site",
            )
            self.log_success("Hugging Face")
            return True
        except ImportError:
            logger.error(
                "huggingface_hub not installed. Install with `pip install huggingface_hub`"
            )
        except Exception as e:
            logger.error(f"Hugging Face upload failed: {str(e)}")
        return False


class LocalMachinePublisher(Publisher):
    """Publisher for local/testing targets. Does nothing except log success."""

    def publish(self, target_dir: Path) -> bool:
        self.log_start("Local Machine")
        logger.info(
            f"Site built at {target_dir}. You can open index.html or serve this directory locally."
        )
        self.log_success("Local Machine")
        return True


class PositConnectPublisher(Publisher):
    """Warns that Marimo HTML/WASM is not supported on Posit Connect."""

    def publish(self, target_dir: Path) -> bool:
        logger.warning(
            "Posit Connect does not support static HTML/WASM Marimo exports. "
            "See: https://docs.posit.co/connect-cloud/user/#github-deployment-workflow"
        )
        return False


# --- Asset Manager ---


class AssetManager:
    """Handles asset copying for targets"""

    def __init__(self, config: ConfigLoader):
        self.assets_dir = Path(config.get("global", "assets_dir", "public"))

    def copy_assets(self, target_dir: Path) -> None:
        assets_target = target_dir / "assets"
        if self.assets_dir.exists():
            for asset in self.assets_dir.iterdir():
                if asset.is_file():
                    target = assets_target / asset.name
                    target.write_bytes(asset.read_bytes())
            logger.info(f"Copied assets to {assets_target}")


# --- Build Manager ---


class BuildManager:
    """Orchestrates build and publish process"""

    def __init__(self, config: ConfigLoader):
        self.config = config
        self.exporter = NotebookExporter(config)
        self.asset_manager = AssetManager(config)
        self.template_path = Path(
            config.get("global", "template", "templates/tailwind.html.j2")
        )

    def build_target(self, target_name: str, target_config: dict) -> bool:
        target_dir = Path(target_config["dir"])
        notebooks = self.exporter.export_folder(
            self.config.get("global", "notebooks_dir", "notebooks"),
            target_dir,
            as_app=False,
        )
        apps = self.exporter.export_folder(
            self.config.get("global", "apps_dir", "apps"), target_dir, as_app=True
        )
        # Automatically detect and copy local imports for notebooks and apps
        self.copy_local_imports_for_notebooks(
            notebooks + apps, target_dir, base_package="local_module"
        )
        # Generate index if we have content
        if notebooks or apps:
            IndexGenerator(self.template_path).generate(target_dir, notebooks, apps)
        self.asset_manager.copy_assets(target_dir)
        publisher = self._get_publisher(target_name, target_config)
        return publisher.publish(target_dir) if publisher else False

    def copy_local_imports_for_notebooks(
        self,
        notebooks: list[dict],
        target_dir: Path,
        base_package: str = "local_module",
    ):
        """
        For each notebook, detect local imports and copy the corresponding files to the target directory.
        """
        for nb in notebooks:
            nb_path = Path(nb.get("source_path"))
            if not nb_path.exists():
                continue
            local_imports = find_local_imports(nb_path, base_package=base_package)
            for module_path in local_imports:
                src = Path(module_path)
                if not src.exists():
                    logger.warning(
                        f"Local import '{src}' required by '{nb_path}' not found."
                    )
                    continue
                dest = target_dir / src.parent
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / src.name)
                logger.info(f"Copied local module {src} to {dest / src.name}")

    def _get_publisher(self, target_name: str, config: dict) -> Optional[Publisher]:
        if target_name == "github_pages":
            return GitHubPagesPublisher(config)
        elif target_name == "static_site":
            return StaticSitePublisher(config)
        elif target_name == "huggingface":
            return HuggingFacePublisher(config)
        elif target_name == "posit_connect":
            return PositConnectPublisher(config)
        elif target_name in {"testing", "local", "local_machine"}:
            return LocalMachinePublisher(config)
        logger.warning(f"No publisher for target: {target_name}")
        return None

    def build_all(self) -> None:
        targets = self.config.get("targets", default={})
        if not targets:
            logger.warning("No targets enabled in config")
            return
        for target_name, target_config in targets.items():
            if target_config.get("enabled", False):
                logger.info(f"Building target: {target_name}")
                self.build_target(target_name, target_config)


# --- Main Entrypoint ---


def main(
    target: str = None,
    output_dir: str = "_site",
    template: str = "templates/tailwind.html.j2",
    config_path: str = "config/config.toml",
) -> None:
    logger.info("Starting marimo build process")
    config = ConfigLoader(Path(config_path))
    build_manager = BuildManager(config)
    targets = config.get("targets")
    if not targets:
        logger.error("No targets found in config.toml")
        return
    if target:
        if target in targets and targets[target].get("enabled", False):
            logger.info(f"Building only target: {target}")
            build_manager.build_target(target, targets[target])
        else:
            logger.error(f"Target '{target}' not found or not enabled in config.toml.")
            return
    else:
        build_manager.build_all()
    logger.success("All builds completed.")


if __name__ == "__main__":
    fire.Fire(main)
