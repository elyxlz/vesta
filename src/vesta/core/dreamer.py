"""Dreamer prompt building."""

import vesta.models as vm
from vesta.core.init import get_memory_path, load_prompt


def build_dreamer_prompt(config: vm.VestaConfig) -> str:
    content = load_prompt("dreamer", config) or ""
    return content.format(
        memory_path=get_memory_path(config),
        skills_dir=config.skills_dir,
        prompts_dir=config.prompts_dir,
        conversations_dir=config.conversations_dir,
        dreamer_dir=config.dreamer_dir,
        install_root=config.install_root,
    )
