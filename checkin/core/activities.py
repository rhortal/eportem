"""ePortem activity IDs: the `name` attribute of the clock buttons.

They are part of each company's ePortem set-up, not platform constants (the
owner's account has 1 = Trabajo, 1293 = Trabajo en Casa, 2 = Comida), so they
are given per account and found from the dashboard when an account is verified.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityIds:
    office: str        # work at the office (start / resume)
    home: str          # work from home (start / resume)
    lunch_pause: str   # the lunch pause

    def work(self, location):
        return self.home if location == "home" else self.office
