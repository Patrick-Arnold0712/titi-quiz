from app.seeds.military_theory import seed_military_theory
from app.seeds.primary_chinese import seed_primary_chinese


def seed_all(db) -> None:
    """启动时同步所有学科。每个 seed 自己保证幂等。"""

    seed_military_theory(db)
    seed_primary_chinese(db)


__all__ = ["seed_all", "seed_military_theory", "seed_primary_chinese"]
