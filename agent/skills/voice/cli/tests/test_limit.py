"""The cap on TTS syntheses at the same time: FIFO slots, and a cap that only goes down."""

import asyncio

from voice.providers import limit


def test_waiters_get_their_slot_in_the_order_they_asked() -> None:
    async def scenario() -> list[int]:
        limiter = limit.Limiter("fake", cap=2)
        order: list[int] = []
        running = 0
        peak = 0

        async def work(n: int) -> None:
            nonlocal running, peak
            await limiter.acquire()
            try:
                order.append(n)
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.01 * (6 - n))
                running -= 1
            finally:
                limiter.release()

        await asyncio.gather(*(work(n) for n in range(1, 7)))
        assert peak == 2
        return order

    assert asyncio.run(scenario()) == [1, 2, 3, 4, 5, 6]


def test_a_cancelled_waiter_gives_up_its_place() -> None:
    async def scenario() -> None:
        limiter = limit.Limiter("fake", cap=1)
        await limiter.acquire()
        waiting = asyncio.create_task(limiter.acquire())
        await asyncio.sleep(0)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        limiter.release()
        assert limiter.active == 0
        await asyncio.wait_for(limiter.acquire(), 1)

    asyncio.run(scenario())


def test_the_cap_goes_down_by_one_and_never_below_one() -> None:
    limiter = limit.Limiter("fake", cap=2)
    limiter.lower()
    assert limiter.cap == 1
    limiter.lower()
    assert limiter.cap == 1


def test_each_provider_class_has_one_limiter_with_the_default_cap() -> None:
    class One:
        pass

    assert limit.for_provider(One()) is limit.for_provider(One())
    assert limit.for_provider(One()).cap == limit.DEFAULT_TTS_CONCURRENCY == 2
