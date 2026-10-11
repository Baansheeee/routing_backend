"""Unit tests for pure risk classification rules."""

from django.test import SimpleTestCase

from routing.services.risk import (
    RiskLevel,
    apply_load_rules,
    assess_checkpoint,
    classify_rain,
    classify_snow,
    classify_wind,
)


class WindThresholdTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_wind(24.9), RiskLevel.LOW)
        self.assertEqual(classify_wind(25), RiskLevel.MODERATE)
        self.assertEqual(classify_wind(34.9), RiskLevel.MODERATE)
        self.assertEqual(classify_wind(35), RiskLevel.HIGH)
        self.assertEqual(classify_wind(44.9), RiskLevel.HIGH)
        self.assertEqual(classify_wind(45), RiskLevel.SEVERE)
        self.assertEqual(classify_wind(54.9), RiskLevel.SEVERE)
        self.assertEqual(classify_wind(55), RiskLevel.NO_TRAVEL)


class RainThresholdTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_rain(0.099), RiskLevel.LOW)
        self.assertEqual(classify_rain(0.10), RiskLevel.MODERATE)
        self.assertEqual(classify_rain(0.25), RiskLevel.MODERATE)
        self.assertEqual(classify_rain(0.2501), RiskLevel.HIGH)
        self.assertEqual(classify_rain(0.50), RiskLevel.HIGH)
        self.assertEqual(classify_rain(0.5001), RiskLevel.SEVERE)
        self.assertEqual(classify_rain(1.00), RiskLevel.SEVERE)
        self.assertEqual(classify_rain(1.01), RiskLevel.NO_TRAVEL)


class SnowThresholdTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_snow(0.499), RiskLevel.LOW)
        self.assertEqual(classify_snow(0.5), RiskLevel.MODERATE)
        self.assertEqual(classify_snow(1.0), RiskLevel.MODERATE)
        self.assertEqual(classify_snow(1.0001), RiskLevel.HIGH)
        self.assertEqual(classify_snow(2.0), RiskLevel.HIGH)
        self.assertEqual(classify_snow(2.0001), RiskLevel.SEVERE)
        self.assertEqual(classify_snow(3.0), RiskLevel.SEVERE)
        self.assertEqual(classify_snow(3.1), RiskLevel.NO_TRAVEL)


class LoadRuleTests(SimpleTestCase):
    def test_wind_55_any_load(self):
        level = apply_load_rules(55, 100, RiskLevel.LOW)
        self.assertEqual(level, RiskLevel.NO_TRAVEL)

    def test_wind_45_54_load_boundary(self):
        self.assertEqual(
            apply_load_rules(50, 30_000, RiskLevel.SEVERE), RiskLevel.SEVERE
        )
        self.assertEqual(
            apply_load_rules(50, 30_001, RiskLevel.SEVERE), RiskLevel.NO_TRAVEL
        )

    def test_wind_35_44_load_boundary(self):
        self.assertEqual(
            apply_load_rules(40, 40_000, RiskLevel.HIGH), RiskLevel.HIGH
        )
        self.assertEqual(
            apply_load_rules(40, 40_001, RiskLevel.HIGH), RiskLevel.SEVERE
        )

    def test_load_rule_never_lowers(self):
        result = assess_checkpoint(
            wind_mph=40,
            rain_in_hr=0.0,
            snow_in_hr=3.1,
            load_lb=50_000,
        )
        self.assertEqual(result["final_level"], RiskLevel.NO_TRAVEL)
        self.assertEqual(result["base_level"], RiskLevel.NO_TRAVEL)


class CombinationTests(SimpleTestCase):
    def test_worst_of_three(self):
        result = assess_checkpoint(
            wind_mph=20,  # LOW
            rain_in_hr=0.4,  # HIGH
            snow_in_hr=0.2,  # LOW
            load_lb=10_000,
        )
        self.assertEqual(result["base_level"], RiskLevel.HIGH)
        self.assertEqual(result["final_level"], RiskLevel.HIGH)
        self.assertTrue(any("Rain" in d for d in result["drivers"]))
