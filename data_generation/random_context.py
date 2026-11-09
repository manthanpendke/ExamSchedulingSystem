
import random

import numpy as np
from faker import Faker


DEFAULT_SEED = 20261022


class RandomContext:

    def __init__(self, seed: int = DEFAULT_SEED):
        self.seed = seed

        self.python = random.Random(seed)
        self.numpy = np.random.default_rng(seed)

        self.faker = Faker("en_IN")
        self.faker.seed_instance(seed)


if __name__ == "__main__":
    context = RandomContext()

    print("Seed:", context.seed)
    print("Random value:", context.python.randint(1, 100))
    print("Generated name:", context.faker.name())
