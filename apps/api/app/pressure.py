from datetime import datetime


def pressure_status(
    samples: list[tuple[datetime, float, float]],
) -> tuple[bool, bool]:
    """Return (baseline_ready, elevated).

    A spike counts only after 15 seconds and at least three baseline samples.
    """
    if len(samples) < 3:
        return False, False
    ordered = sorted(samples, key=lambda item: item[0])
    start = ordered[0][0]
    baseline = [item for item in ordered if (item[0] - start).total_seconds() <= 15]
    later = [item for item in ordered if (item[0] - start).total_seconds() > 15]
    if len(baseline) < 3 or not later:
        return False, False
    base_pulse = _median([item[1] for item in baseline])
    base_breath = _median([item[2] for item in baseline])
    pulse, breath = later[-1][1], later[-1][2]
    elevated = pulse > base_pulse * 1.15 or breath > base_breath * 1.2
    return True, elevated


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
