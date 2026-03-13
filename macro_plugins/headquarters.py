import cv2
import numpy

from util.utils import Region, Utils


SUPPLY_VALUES = [1000, 2000, 3000, 5000, 10000, 20000]
SUPPLY_WHITEOUT_THRESHOLD = 120
START_FEED_THRESHOLD = 0.5
STOP_FEED_THRESHOLD = 0.9
TOTAL_CAPACITY = 44000
EMPTY_LOW = numpy.array([0, 0, 0], dtype=numpy.uint8)
EMPTY_HIGH = numpy.array([255, 130, 220], dtype=numpy.uint8)


def refill_dorm(runner, context, payload):
    regions = context.regions

    Utils.script_sleep(payload.get("initial_sleep", 5))

    while True:
        Utils.wait_update_screen(payload.get("poll_seconds", 1))

        if Utils.find("headquarters/dorm_summary_confirm_button"):
            Utils.touch_randomly(regions["confirm_dorm_summary"])
            continue

        if Utils.find("headquarters/give_food_button"):
            Utils.touch_randomly(regions["ignore_give_food_button"])
            continue

        fill_ratio = _estimate_dorm_fill_ratio(runner, context, payload)
        if fill_ratio < float(payload.get("start_feed_threshold", START_FEED_THRESHOLD)):
            _feed_snacks(runner, context, payload, fill_ratio)
            return True

        return False


def feed_snacks(runner, context, payload):
    fill_ratio = _estimate_dorm_fill_ratio(runner, context, payload)
    _feed_snacks(runner, context, payload, fill_ratio)
    return True


def _feed_snacks(runner, context, payload, current_fill_ratio=None):
    regions = context.regions
    total_capacity = int(payload.get("total_capacity", TOTAL_CAPACITY))
    stop_threshold = float(payload.get("stop_feed_threshold", STOP_FEED_THRESHOLD))
    target_value = total_capacity * stop_threshold

    Utils.touch_randomly(regions["supplies_bar"])
    Utils.script_sleep(payload.get("menu_sleep", 1))
    Utils.update_screen()

    alert_found = Utils.find("menu/alert_close")
    retry_counter = 0
    max_retries = int(payload.get("max_retries", 40))

    while retry_counter < max_retries and not alert_found:
        retry_counter += 1
        if current_fill_ratio is None:
            current_fill_ratio = _estimate_dorm_fill_ratio(runner, context, payload)

        current_value = current_fill_ratio * total_capacity
        remaining_value = target_value - current_value
        if remaining_value <= 0:
            break

        selected = _pick_supply_greedy(runner, context, remaining_value)
        runner._emit_event(
            "plugin_probe",
            plugin="headquarters.feed_snacks",
            probe="fill_plan",
            found=selected is not None,
            region=runner._region_to_dict(selected["region"]) if selected else None,
            color=list(selected["color"]) if selected else None,
            frame=runner._capture_frame(context),
            fill_ratio=round(current_fill_ratio, 4),
            current_value=int(current_value),
            remaining_value=int(max(0, remaining_value)),
            target_value=int(target_value),
            selected_supply=selected["value"] if selected else None
        )

        if selected is None:
            break

        Utils.touch_randomly(selected["region"])
        Utils.wait_update_screen(payload.get("retry_wait", 0.5))
        alert_found = Utils.find("menu/alert_close")
        current_fill_ratio = _estimate_dorm_fill_ratio(runner, context, payload)

    if alert_found:
        Utils.touch_randomly(alert_found)
        Utils.wait_update_screen(1)

    Utils.touch_randomly(regions["exit_snacks_menu"])


def _pick_supply_greedy(runner, context, remaining_value):
    candidates = []
    for supply_value, supply_index in _get_available_supply_order(context):
        region = context.regions.get("snack_{}".format(supply_index + 1))
        if region is None:
            continue
        color = Utils.get_region_color_average(region)
        is_available = color[2] > SUPPLY_WHITEOUT_THRESHOLD
        runner._emit_event(
            "plugin_probe",
            plugin="headquarters.feed_snacks",
            probe="supply_state",
            found=is_available,
            region=runner._region_to_dict(region),
            color=list(color),
            frame=runner._capture_frame(context),
            supply_value=supply_value
        )
        if is_available and supply_value <= remaining_value:
            candidates.append({
                "value": supply_value,
                "index": supply_index,
                "region": region,
                "color": color,
            })
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["value"], reverse=True)
    return candidates[0]


def _get_available_supply_order(context):
    configured = getattr(context.config, "dorm", {}).get("AvailableSupplies", [])
    values = list(configured) if configured else list(reversed(SUPPLY_VALUES))
    order = []
    for value in values:
        if value in SUPPLY_VALUES:
            order.append((value, SUPPLY_VALUES.index(value)))
    return order


def _estimate_dorm_fill_ratio(runner, context, payload):
    region = _get_dorm_fill_scan_region(payload)
    hsv = cv2.cvtColor(Utils.color_screen, cv2.COLOR_BGR2HSV)
    crop = hsv[region.y:region.y + region.h, region.x:region.x + region.w]
    if crop.size == 0:
        return 0.0
    empty_mask = numpy.all((EMPTY_LOW <= crop) & (crop <= EMPTY_HIGH), axis=2)
    filled_columns = ~numpy.all(empty_mask, axis=0)
    ratio = float(numpy.count_nonzero(filled_columns)) / float(max(1, filled_columns.shape[0]))
    sample_color = Utils.get_region_color_average(_get_dorm_bar_region(ratio, False))
    runner._emit_event(
        "plugin_probe",
        plugin="headquarters.refill_dorm",
        probe="fill_ratio",
        found=ratio > 0,
        region=runner._region_to_dict(region),
        color=list(sample_color),
        frame=runner._capture_frame(context),
        fill_ratio=round(ratio, 4),
        current_value=int(ratio * int(payload.get("total_capacity", TOTAL_CAPACITY)))
    )
    return ratio


def _get_dorm_bar_empty(runner, context, percentage, corner_bar=False):
    region = _get_dorm_bar_region(percentage, corner_bar)
    color = Utils.get_region_color_average(region)
    result = bool(numpy.all((EMPTY_LOW <= color) & (color <= EMPTY_HIGH)))
    runner._emit_event(
        "plugin_probe",
        plugin="headquarters.refill_dorm",
        probe="dorm_bar",
        found=result,
        region=runner._region_to_dict(region),
        color=list(color),
        frame=runner._capture_frame(context)
    )
    return result


def _get_dorm_fill_scan_region(payload=None):
    payload = payload or {}
    x1 = int(payload.get("fill_scan_x1", 595))
    x2 = int(payload.get("fill_scan_x2", 1470))
    y = int(payload.get("fill_scan_y", 460))
    h = int(payload.get("fill_scan_h", 3))
    return Region(x1, y, max(1, x2 - x1), max(1, h))


def _get_dorm_bar_region(percentage, corner_bar):
    if corner_bar:
        x_coord = 354 + int(205 * percentage)
        y_coord = 1031
    else:
        x_coord = 360 + int(890 * percentage)
        y_coord = 450
    return Region(x_coord, y_coord, 2, 2)


def get_validation_regions():
    return [
        _region_spec('dorm_bar_start', _get_dorm_bar_region(START_FEED_THRESHOLD, True)),
        _region_spec('dorm_bar_stop', _get_dorm_bar_region(STOP_FEED_THRESHOLD, False)),
        _region_spec('dorm_fill_scan', _get_dorm_fill_scan_region()),
    ]


def _region_spec(name, region):
    return {
        'name': name,
        'x': region.x,
        'y': region.y,
        'w': region.w,
        'h': region.h,
    }
