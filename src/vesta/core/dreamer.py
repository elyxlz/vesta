"""Memory loading and consolidation prompt building."""

import vesta.models as vm
from vesta import logger
from vesta.core.init import get_memory_path, load_memory_template


def load_memory(config: vm.VestaConfig) -> str:
    """Load main agent memory from disk or template."""
    memory_path = get_memory_path(config)
    if memory_path.exists():
        content = memory_path.read_text()
        logger.debug(f"Loaded main memory ({len(content)} chars)")
        return content
    logger.debug("Using template for main (file not found)")
    return load_memory_template("main")


def build_memory_consolidation_prompt(config: vm.VestaConfig) -> str:
    return config.dreamer_prompt.format(
        memory_path=get_memory_path(config),
        skills_dir=config.skills_dir,
        conversations_dir=config.conversations_dir,
    )
