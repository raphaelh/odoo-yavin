# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Version management services for Yavin payment terminal."""

from .provider import YavinVersionProvider

__all__ = [
    "YavinVersionProvider",
]
