"""eportem.core.calendar and templates: every rule of resolve() and the order
between them, as tables of dates."""
import datetime
import unittest

from eportem.core.calendar import DayChange, LocationPattern, Period, UserCalendar, resolve, resolve_range
from eportem.core.templates import (
    BUILTIN_TEMPLATES,
    DayTimes,
    TemplateError,
    matching_builtin,
    parse_template,
    template_to_dict,
)

D = datetime.date
EUROPEAN = BUILTIN_TEMPLATES["european-9-18"]
SUMMER = BUILTIN_TEMPLATES["summer-8-15"]
# Mon 2026-11-16 .. Sun 2026-11-22; Wed home.
MON, TUE, WED, THU, FRI, SAT, SUN = (D(2026, 11, 16) + datetime.timedelta(days=i) for i in range(7))
HOME_WEDNESDAY = LocationPattern(({0: "office", 1: "office", 2: "home", 3: "office", 4: "office"},))


def fake_holidays(table):
    return lambda country, region, year: {d: n for d, n in table.items() if d.year == year}


def cal(**kw):
    kw.setdefault("default_template", EUROPEAN)
    kw.setdefault("location_pattern", HOME_WEDNESDAY)
    return UserCalendar(**kw)


class TestTemplates(unittest.TestCase):

    def test_builtins(self):
        self.assertEqual(EUROPEAN.day(0).actions(),
                         [("start_day", 540), ("lunch_break", 810), ("after_lunch", 870), ("stop_day", 1080)])
        spanish = BUILTIN_TEMPLATES["spanish-9-18"].day(2)
        self.assertEqual((spanish.lunch_out, spanish.lunch_back), (14 * 60 + 30, 15 * 60 + 30))
        short = BUILTIN_TEMPLATES["spanish-friday-short"]
        self.assertTrue(short.day(3).has_lunch)
        self.assertEqual(short.day(4).actions(), [("start_day", 480), ("stop_day", 900)])
        self.assertIsNone(EUROPEAN.day(5))
        for t in BUILTIN_TEMPLATES.values():
            for d in t.days.values():
                self.assertEqual(d.problems(), [], t.key)

    def test_round_trip_and_matching_builtin(self):
        data = template_to_dict(EUROPEAN)
        self.assertEqual(data["days"]["0"], {"start": "09:00", "stop": "18:00",
                                             "lunch_out": "13:30", "lunch_back": "14:30"})
        again = parse_template(data, key="mine", name="Mine")
        self.assertEqual(again.days, EUROPEAN.days)
        self.assertIs(matching_builtin(again), EUROPEAN)
        self.assertIsNone(matching_builtin(parse_template({"key": "k", "name": "n", "days": {
            "0": {"start": "9:00", "stop": "17:00"}}})))

    def test_validation_lists_every_problem(self):
        with self.assertRaises(TemplateError) as cm:
            parse_template({"key": "", "days": {
                "0": {"start": "9:00", "stop": "8:00"},
                "1": {"start": "9:00", "stop": "18:00", "lunch_out": "13:00"},
                "2": {"start": "25:00", "stop": "18:00"},
                "8": {"start": "9:00", "stop": "18:00"},
                "3": {"stop": "18:00", "nap": "1"},
            }})
        text = " | ".join(cm.exception.problems)
        for expected in ('days["0"]: times must be in order', 'days["1"]: a lunch break needs both',
                         'days["2"]["start"]: must be a time', 'days["8"]: weekday must be',
                         'days["3"]["start"]: required', "unknown keys ['nap']", '"key" is required',
                         '"name" is required'):
            self.assertIn(expected, text)

    def test_null_day_is_a_day_off(self):
        t = parse_template({"key": "k", "name": "n", "days": {"0": None, "1": {"start": "9:00", "stop": "17:00"}}})
        self.assertIsNone(t.day(0))
        self.assertEqual(t.day(1).describe(), "09:00–17:00, no lunch break")


class TestResolve(unittest.TestCase):

    def test_ordinary_week(self):
        plans = resolve_range(cal(), MON, 7)
        self.assertEqual([p.works for p in plans], [True] * 5 + [False] * 2)
        self.assertEqual([p.location for p in plans[:5]], ["office", "office", "home", "office", "office"])
        self.assertEqual(plans[5].reason, "Saturday is not a working day in European day, 9–18")
        self.assertEqual(plans[0].template_key, "european-9-18")

    def test_paused_and_inactive_beat_everything(self):
        work = DayChange("times", MON, MON, times=DayTimes(600, 700))
        self.assertEqual(resolve(cal(paused=True, changes=(work,)), MON).reason, "paused")
        self.assertEqual(resolve(cal(active=False), MON).reason, "account not active")

    def test_time_off_beats_holiday_work_and_times(self):
        changes = (DayChange("time_off", MON, FRI, note="Lanzarote"),
                   DayChange("times", TUE, TUE, times=DayTimes(600, 700)),
                   DayChange("work_on_holiday", TUE, TUE))
        plan = resolve(cal(changes=changes), TUE)
        self.assertFalse(plan.works)
        self.assertTrue(plan.on_time_off)
        self.assertEqual(plan.reason, "time off: Lanzarote")

    def test_public_holidays_regional_and_local(self):
        c = cal(holiday_country="ES", holiday_region="MD",
                holiday_lookup=fake_holidays({TUE: "Fiesta regional"}), local_holidays={THU: "San Isidro"})
        self.assertEqual(resolve(c, TUE).reason, "public holiday: Fiesta regional")
        self.assertEqual(resolve(c, THU).reason, "public holiday: San Isidro")
        self.assertTrue(resolve(c, WED).works)

    def test_working_on_a_holiday(self):
        base = dict(holiday_country="ES", holiday_lookup=fake_holidays({TUE: "Fiesta"}))
        plan = resolve(cal(changes=(DayChange("work_on_holiday", TUE, TUE),), **base), TUE)
        self.assertTrue(plan.works)
        self.assertEqual(plan.times, EUROPEAN.day(1))
        plan = resolve(cal(changes=(DayChange("times", TUE, TUE, times=DayTimes(600, 720)),), **base), TUE)
        self.assertEqual(plan.times, DayTimes(600, 720))

    def test_real_holiday_package_for_madrid(self):
        c = cal(holiday_country="ES", holiday_region="MD")
        self.assertIn("Comunidad de Madrid", resolve(c, D(2026, 5, 2)).reason)  # a Saturday, still a holiday
        self.assertFalse(resolve(c, D(2026, 12, 25)).works)

    def test_times_change_beats_period_beats_default(self):
        summer = Period(SUMMER, D(2026, 11, 18), D(2026, 11, 19), label="test summer")
        changes = (DayChange("times", THU, THU, times=DayTimes(7 * 60, 13 * 60)),)
        c = cal(periods=(summer,), changes=changes)
        self.assertEqual(resolve(c, TUE).times, EUROPEAN.day(1))
        self.assertEqual(resolve(c, WED).times, SUMMER.day(2))
        self.assertEqual(resolve(c, WED).reason, "Summer hours (jornada intensiva) (test summer)")
        self.assertEqual(resolve(c, THU).times, DayTimes(420, 780))
        self.assertEqual(resolve(c, THU).reason, "changed times for this day")

    def test_times_change_makes_a_weekend_day_work(self):
        c = cal(changes=(DayChange("times", SAT, SAT, times=DayTimes(600, 720)),))
        self.assertTrue(resolve(c, SAT).works)

    def test_yearly_periods_including_across_new_year(self):
        july_august = Period(SUMMER, D(2000, 7, 1), D(2000, 8, 31), yearly=True)
        self.assertTrue(july_august.covers(D(2027, 7, 1)))
        self.assertTrue(july_august.covers(D(2031, 8, 31)))
        self.assertFalse(july_august.covers(D(2027, 9, 1)))
        winter = Period(SUMMER, D(2000, 12, 15), D(2001, 1, 10), yearly=True)
        self.assertTrue(winter.covers(D(2026, 12, 20)))
        self.assertTrue(winter.covers(D(2027, 1, 5)))
        self.assertFalse(winter.covers(D(2027, 1, 11)))

    def test_later_period_wins_when_two_overlap(self):
        a = Period(SUMMER, MON, FRI)
        b = Period(BUILTIN_TEMPLATES["part-time-morning"], WED, WED)
        self.assertEqual(resolve(cal(periods=(a, b)), WED).template_key, "part-time-morning")

    def test_location_order(self):
        changes = (DayChange("business_trip", MON, FRI, location="office"),
                   DayChange("location", WED, WED, location="home"),
                   DayChange("location", THU, THU, location="home"),
                   DayChange("location", THU, THU, location="office"))  # the later one wins
        c = cal(changes=changes)
        self.assertEqual((resolve(c, TUE).location, resolve(c, TUE).location_source), ("office", "business trip"))
        self.assertEqual((resolve(c, WED).location, resolve(c, WED).location_source), ("home", "changed for this day"))
        self.assertEqual(resolve(c, THU).location, "office")
        self.assertEqual(resolve(c, TUE).business_trip_end, FRI)

    def test_business_trip_without_location_keeps_the_pattern(self):
        c = cal(changes=(DayChange("business_trip", MON, FRI),))
        self.assertEqual(resolve(c, WED).location, "home")
        self.assertEqual(resolve(c, WED).business_trip_end, FRI)

    def test_no_pattern_means_office(self):
        plan = resolve(cal(location_pattern=LocationPattern()), MON)
        self.assertEqual((plan.location, plan.location_source), ("office", "default"))

    def test_alternating_weeks(self):
        pattern = LocationPattern(({0: "home"}, {0: "office"}), anchor=WED)  # week of 16 Nov is A
        self.assertEqual(pattern.location_for(MON), "home")
        self.assertEqual(pattern.location_for(MON + datetime.timedelta(days=7)), "office")
        self.assertEqual(pattern.location_for(MON + datetime.timedelta(days=14)), "home")
        self.assertEqual(pattern.location_for(MON - datetime.timedelta(days=7)), "office")

    def test_day_plan_actions(self):
        self.assertEqual([a for a, _ in resolve(cal(), MON).actions()],
                         ["start_day", "lunch_break", "after_lunch", "stop_day"])
        self.assertEqual(resolve(cal(), SAT).actions(), [])


if __name__ == "__main__":
    unittest.main()
