"""Indexed temporal queries shared by phrase optimization and multimodal fusion."""
from bisect import bisect_left, bisect_right
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class TemporalIndex(Generic[T]):
    def __init__(self, values: list[T], timestamp: Callable[[T], float]):
        self.values = sorted(values, key=timestamp)
        self.times = [timestamp(value) for value in self.values]

    def around(self, time: float, radius: float = 0.15) -> list[T]:
        return self.values[bisect_left(self.times, time-radius):bisect_right(self.times, time+radius)]
