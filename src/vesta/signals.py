import types
import typing as tp

import vesta.models as vm
import vesta.effects as vfx

SignalHandler = tp.Callable[[int, types.FrameType | None], None]


def make_signal_handler(state: vm.State) -> SignalHandler:
    def handler(signum: int, frame: types.FrameType | None) -> None:
        # Note: += is not atomic, but signal handlers are serialized by the OS
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            vfx.exit_process(0)

    return handler
