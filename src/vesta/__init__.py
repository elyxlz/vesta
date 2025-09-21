import vesta.main as main_module

main = main_module.main
run_vesta = main_module.run_vesta

__all__ = ["main", "run_vesta"]

# Alias for backwards compatibility
run = run_vesta
