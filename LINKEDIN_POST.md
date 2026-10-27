# LinkedIn post

Most of a university's carbon story sits in its utility bills, not its strategy documents.

Coming from energy markets, I wanted to show I can do sustainability reporting end to end, so I built Campus Carbon Tracker: a Scope 1, 2 and 3 emissions inventory and Net Zero dashboard for a fictional Victorian campus (six buildings, 25,000 students, synthetic activity data, real NGA Factors 2026).

Three things the numbers showed:

- Emissions fell 33% from the baseline, but almost all of that came from buying renewable electricity. Counted at the grid average, the drop is under 3%.
- Swapping gas heating for heat pumps would add 1,691 t on its own while Victoria's grid sits at 0.74 kg CO2-e per kWh. Electrification needs renewable supply alongside it.
- The aquatic centre emits 3.8 times more per square metre than the library.

I also planted four data problems (missing gas bills, a duplicated meter day, a Wh/kWh mix-up and a late contractor report) to test the quality checks. All four were flagged, with no false alarms.

Skills on show: GHG Protocol, Scope 1-3, location- vs market-based Scope 2, NGA Factors, data governance, Python, and a pipeline built to take AEMO half-hourly grid data.

Live dashboard: https://vivekarya05.github.io/campus-carbon-tracker/

#Sustainability #NetZero #CarbonAccounting #DataAnalytics #EnergyTransition

---

**Suggested image:** the dashboard screenshot, `docs/assets/screenshot.png` (KPI cards and the monthly scope chart).

**First comment:**

Code, methodology and every assumption are on GitHub: https://github.com/Vivekarya05/campus-carbon-tracker
