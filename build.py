import os
import subprocess
import tomllib
from pathlib import Path
from typing import Dict, List, Optional

import jinja2
from dotenv import load_dotenv
from loguru import logger
import httpx

# Load environment variables from .env
load_dotenv()


class ConfigLoader:
    """Loads and validates configuration from TOML file"""

    def __init__(self, config_path: Path = Path("config.toml")):
        self.config = self._load_config(config_path)
        self._validate_config()

    def _load_config(self, config_path: Path) -> dict:
        """Load config from TOML or return defaults"""
        if config_path.exists():
            with open(config_path, "rb") as f:
                return tomllib.load(f)
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
                "zola": {"enabled": False, "dir": "_site/zola", "zola_content_dir": ""},
                "huggingface": {
                    "enabled": False,
                    "dir": "_site/huggingface",
                    "repo_id": "",
                },
                "posit_connect": {
                    "enabled": False,
                    "dir": "_site/posit_connect",
                    "connect_url": "",
                },
            },
        }

    def _validate_config(self) -> None:
        """Ensure required paths exist and create directories"""
        # Create global output directory
        output_dir = Path(self.get("global", "output_dir", "_site"))
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create target directories
        for target, config in self.config.get("targets", {}).items():
            if config.get("enabled", False):
                target_dir = Path(config["dir"])
                target_dir.mkdir(parents=True, exist_ok=True)

                # Create target subdirectories
                (target_dir / "notebooks").mkdir(exist_ok=True)
                (target_dir / "apps").mkdir(exist_ok=True)
                (target_dir / "assets").mkdir(exist_ok=True)

                # Optional README
                if not (target_dir / "README.md").exists():
                    (target_dir / "README.md").write_text(
                        f"# {target.replace('_', ' ').title()} Target\n"
                    )

    def get(self, section: str, key: str = None, default: Optional[any] = None) -> any:
        """Get config value with fallback."""
        section_data = self.config.get(section, {})
        if key is None:
            return section_data
        return section_data.get(key, default)


class NotebookExporter:
    """Handles exporting marimo notebooks to HTML/WASM"""

    def __init__(self, config: ConfigLoader):
        self.config = config

    def export_notebook(
        self, notebook_path: Path, output_dir: Path, as_app: bool
    ) -> Optional[Path]:
        """Export single notebook to HTML/WASM"""
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
        """Export all notebooks in a folder for a target"""
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
                    }
                )
        return results


class IndexGenerator:
    """Generates index.html using Jinja templates"""

    def __init__(self, template_path: Path):
        self.template_path = template_path

    def generate(
        self, output_dir: Path, notebooks: List[dict], apps: List[dict]
    ) -> Path:
        """Generate index.html in target directory"""
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_path.parent),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )
        template = env.get_template(self.template_path.name)
        index_file = output_dir / "index.html"
        index_file.write_text(template.render(notebooks=notebooks, apps=apps))
        logger.info(f"Generated index at {index_file}")
        return index_file


class Publisher:
    """Base publisher class"""

    def publish(self, target_dir: Path) -> bool:
        raise NotImplementedError


class GitHubPagesPublisher(Publisher):
    """Handled by CI - just validate structure"""

    def publish(self, target_dir: Path) -> bool:
        if not (target_dir / ".nojekyll").exists():
            (target_dir / ".nojekyll").touch()
        logger.info("GitHub Pages publishing handled by CI workflow")
        return True


class ZolaPublisher(Publisher):
    """Copies files to Zola content directory"""

    def __init__(self, config: dict):
        self.zola_dir = Path(config.get("zola_content_dir", ""))

    def publish(self, target_dir: Path) -> bool:
        if not self.zola_dir.exists():
            logger.error(f"Zola directory not found: {self.zola_dir}")
            return False

        for item in target_dir.iterdir():
            if item.is_file():
                target = self.zola_dir / item.name
                target.write_text(item.read_text())
        logger.success(f"Copied files to Zola at {self.zola_dir}")
        return True


class HuggingFacePublisher(Publisher):
    """Publishes to Hugging Face Spaces using huggingface_hub"""

    def __init__(self, config: dict):
        self.repo_id = config.get("repo_id", "")

    def publish(self, target_dir: Path) -> bool:
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=os.getenv("HF_TOKEN"))
            api.upload_folder(
                repo_id=self.repo_id,
                folder_path=target_dir,
                path_in_repo="",
                repo_type="space",
            )
            logger.success(f"Published to Hugging Face: {self.repo_id}")
            return True
        except ImportError:
            logger.error(
                "huggingface_hub not installed. Install with `uv add (pip install) huggingface_hub`"
            )
        except Exception as e:
            logger.error(f"Hugging Face upload failed: {str(e)}")
        return False


class PositConnectPublisher(Publisher):
    """Publishes to Posit Connect using API"""

    def __init__(self, config: dict):
        self.connect_url = config.get("connect_url", "")


class PositConnectPublisher(Publisher):
    """Publishes to Posit Connect using the HTTP API and httpx."""

    def __init__(self, config: dict):
        self.connect_url = config.get("connect_url", "")

    def publish(self, target_dir: Path) -> bool:
        try:
            api_key = os.getenv("POSIT_API_KEY")
            if not api_key:
                logger.error("POSIT_API_KEY not found in environment.")
                return False

            headers = {"Authorization": f"Key {api_key}"}
            with httpx.Client() as client:
                for html_file in target_dir.rglob("*.html"):
                    with html_file.open("rb") as f:
                        files = {"file": (html_file.name, f, "text/html")}
                        response = client.post(
                            f"{self.connect_url}/__api__/v1/content",
                            files=files,
                            headers=headers,
                        )
                        if response.is_error:
                            logger.error(
                                f"Failed to upload {html_file.name}: {response.text}"
                            )
                            return False
            logger.success(f"Published to Posit Connect: {self.connect_url}")
            return True
        except ImportError:
            logger.error(
                "httpx not installed. Install with `uv add (pip install) httpx`"
            )
        except Exception as e:
            logger.error(f"Posit Connect upload failed: {str(e)}")
        return False


class AssetManager:
    """Handles asset copying for targets"""

    def __init__(self, config: ConfigLoader):
        self.assets_dir = Path(config.get("global", "assets_dir", "public"))

    def copy_assets(self, target_dir: Path) -> None:
        """Copy assets to target directory"""
        assets_target = target_dir / "assets"
        if self.assets_dir.exists():
            for asset in self.assets_dir.iterdir():
                if asset.is_file():
                    target = assets_target / asset.name
                    target.write_bytes(asset.read_bytes())
            logger.info(f"Copied assets to {assets_target}")


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
        """Build and publish a single target"""
        target_dir = Path(target_config["dir"])

        # Export notebooks and apps
        notebooks = self.exporter.export_folder(
            self.config.get("global", "notebooks_dir", "notebooks"),
            target_dir,
            as_app=False,
        )
        apps = self.exporter.export_folder(
            self.config.get("global", "apps_dir", "apps"), target_dir, as_app=True
        )

        # Generate index if we have content
        if notebooks or apps:
            IndexGenerator(self.template_path).generate(target_dir, notebooks, apps)

        # Copy assets
        self.asset_manager.copy_assets(target_dir)

        # Initialize and run publisher
        publisher = self._get_publisher(target_name, target_config)
        return publisher.publish(target_dir) if publisher else False

    def _get_publisher(self, target_name: str, config: dict) -> Optional[Publisher]:
        """Get publisher instance based on target"""
        if target_name == "github_pages":
            return GitHubPagesPublisher()
        elif target_name == "zola":
            return ZolaPublisher(config)
        elif target_name == "huggingface":
            return HuggingFacePublisher(config)
        elif target_name == "posit_connect":
            return PositConnectPublisher(config)
        logger.warning(f"No publisher for target: {target_name}")
        return None

    def build_all(self) -> None:
        """Build all enabled targets"""
        targets = self.config.get("targets", {})
        if not targets:
            logger.warning("No targets enabled in config")
            return

        for target_name, target_config in targets.items():
            if target_config.get("enabled", False):
                logger.info(f"Building target: {target_name}")
                self.build_target(target_name, target_config)


import fire


import fire
from pathlib import Path
from loguru import logger


def main(
    target: str = None,
    output_dir: str = "_site",
    template: str = "templates/tailwind.html.j2",
    config_path: str = "config.toml",
) -> None:
    """
    Main entry point for marimo build script.

    Args:
        target (str, optional): Name of the target to build (e.g., "testing", "github_pages"). If not provided, builds all enabled targets.
        output_dir (str, optional): Default output directory for exports (overridden by target config if present).
        template (str, optional): Path to the HTML template file.
        config_path (str, optional): Path to the config.toml file.
    """
    logger.info("Starting marimo build process")

    config = ConfigLoader(Path(config_path))
    build_manager = BuildManager(config)

    # If a specific target is requested, build only that target
    if target:
        targets = config.get("targets")
        if target in targets and targets[target].get("enabled", False):
            logger.info(f"Building only target: {target}")
            build_manager.build_target(target, targets[target])
        else:
            logger.error(f"Target '{target}' not found or not enabled in config.toml.")
            return
    else:
        # Build all enabled targets
        build_manager.build_all()

    logger.success("All builds completed.")


if __name__ == "__main__":
    fire.Fire(main)
