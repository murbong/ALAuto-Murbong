import copy


class MacroSchemaError(Exception):
    """Raised when a macro cannot be normalized into canonical form."""


SUPPORTED_ACTIONS = {
    "log",
    "sleep",
    "update_screen",
    "wait_update_screen",
    "tap_region",
    "tap_image",
    "tap_found_image",
    "back",
    "swipe",
    "set",
    "increment",
    "stats_increment",
    "print_stats",
    "if",
    "while",
    "repeat",
    "wait_for",
    "call",
    "run_macro",
    "plugin",
    "break",
    "continue",
    "return",
}

COMPARE_KEYS = ("equals", "not_equals", "gt", "gte", "lt", "lte")


def normalize_macro(macro):
    if not isinstance(macro, dict):
        raise MacroSchemaError("Macro root must be an object.")
    normalized = copy.deepcopy(macro)
    if "regions" in normalized and isinstance(normalized["regions"], dict):
        normalized["regions"] = {
            name: normalize_region(region, "regions.{}".format(name))
            for name, region in normalized["regions"].items()
        }
    if "steps" in normalized:
        normalized["steps"] = normalize_steps(normalized["steps"], "steps")
    if "routines" in normalized and isinstance(normalized["routines"], dict):
        normalized["routines"] = {
            name: normalize_steps(steps, "routines.{}".format(name))
            for name, steps in normalized["routines"].items()
        }
    return normalized


def normalize_steps(steps, path):
    if not isinstance(steps, list):
        raise MacroSchemaError("{} must be a list.".format(path))
    return [normalize_step(step, "{}[{}]".format(path, index)) for index, step in enumerate(steps)]


def normalize_step(step, path):
    if not isinstance(step, dict):
        raise MacroSchemaError("{} must be an object.".format(path))
    normalized = copy.deepcopy(step)
    action = normalized.get("action")
    if action not in SUPPORTED_ACTIONS:
        raise MacroSchemaError("{} has unsupported action '{}'".format(path, action))

    if action in ("if", "while", "wait_for") and "condition" in normalized:
        normalized["condition"] = normalize_condition(normalized["condition"], path + ".condition")
    if "steps" in normalized:
        normalized["steps"] = normalize_steps(normalized["steps"], path + ".steps")
    if "else_steps" in normalized:
        normalized["else_steps"] = normalize_steps(normalized["else_steps"], path + ".else_steps")
    if "timeout_steps" in normalized:
        normalized["timeout_steps"] = normalize_steps(normalized["timeout_steps"], path + ".timeout_steps")

    if action == "swipe":
        normalized = normalize_swipe_step(normalized, path)
    elif action == "set":
        normalized["var"] = normalized.pop("var", normalized.pop("name", None))
        if not normalized.get("var"):
            raise MacroSchemaError("{} is missing 'var'.".format(path))
        if "value" in normalized:
            normalized["value"] = normalize_value(normalized["value"], path + ".value")
    elif action == "increment":
        normalized["var"] = normalized.pop("var", normalized.pop("name", None))
        if not normalized.get("var"):
            raise MacroSchemaError("{} is missing 'var'.".format(path))
        if "amount" not in normalized:
            normalized["amount"] = normalized.pop("value", 1)
    elif action == "return":
        if "value" in normalized:
            normalized["value"] = normalize_value(normalized["value"], path + ".value")
    elif action == "print_stats":
        oil_limit_config = normalized.pop("oil_limit_config", None)
        if "oil_limit" not in normalized and oil_limit_config:
            normalized["oil_limit"] = {"ref": "runtime", "key": oil_limit_config}
    elif action == "run_macro":
        if isinstance(normalized.get("variables"), dict):
            normalized["variables"] = {
                key: normalize_value(value, path + ".variables.{}".format(key))
                for key, value in normalized["variables"].items()
            }
    elif action == "plugin":
        plugin_name = normalized.get("plugin")
        if not plugin_name:
            raise MacroSchemaError("{} plugin action is missing 'plugin'.".format(path))

    return normalized


def normalize_swipe_step(step, path):
    normalized = copy.deepcopy(step)
    if "from" not in normalized and all(key in normalized for key in ("x1", "y1")):
        normalized["from"] = {"x": int(normalized.pop("x1")), "y": int(normalized.pop("y1"))}
    if "to" not in normalized and all(key in normalized for key in ("x2", "y2")):
        normalized["to"] = {"x": int(normalized.pop("x2")), "y": int(normalized.pop("y2"))}
    if "duration_ms" not in normalized and "ms" in normalized:
        normalized["duration_ms"] = int(normalized.pop("ms"))
    if "from" not in normalized or "to" not in normalized or "duration_ms" not in normalized:
        raise MacroSchemaError("{} must contain from/to/duration_ms.".format(path))
    normalized["from"] = normalize_point(normalized["from"], path + ".from")
    normalized["to"] = normalize_point(normalized["to"], path + ".to")
    normalized["duration_ms"] = int(normalized["duration_ms"])
    return normalized


def normalize_condition(condition, path):
    if not isinstance(condition, dict):
        return condition
    if "type" in condition:
        return normalize_canonical_condition(condition, path)
    if "all" in condition:
        return {"type": "all", "items": [normalize_condition(item, path + ".all") for item in condition["all"]]}
    if "any" in condition:
        return {"type": "any", "items": [normalize_condition(item, path + ".any") for item in condition["any"]]}
    if "not" in condition:
        return {"type": "not", "item": normalize_condition(condition["not"], path + ".not")}
    if "always" in condition:
        return {"type": "always", "value": bool(condition["always"])}
    if "image" in condition:
        normalized = {
            "type": "image",
            "image": condition["image"],
        }
        for key in ("similarity", "color", "interrupt_if_not_found", "use_mask", "x_between", "y_between"):
            if key in condition:
                normalized[key] = condition[key]
        return normalized
    for source_key in ("var", "runtime", "config", "feature"):
        if source_key in condition:
            return normalize_compare_condition(source_key, condition[source_key], condition, path)
    if "region_color" in condition:
        normalized = {
            "type": "region_color",
            "region": normalize_region(condition["region_color"], path + ".region_color")
        }
        if "low" in condition and "high" in condition:
            normalized["match"] = {
                "low": list(condition["low"]),
                "high": list(condition["high"]),
            }
        else:
            normalized["channel"] = int(condition.get("channel", 0))
            normalized["op"] = "gt" if "gt" in condition else "lt"
            normalized["value"] = condition.get("gt", condition.get("lt"))
        return normalized
    return copy.deepcopy(condition)


def normalize_canonical_condition(condition, path):
    normalized = copy.deepcopy(condition)
    condition_type = normalized.get("type")
    if condition_type in ("all", "any"):
        normalized["items"] = [normalize_condition(item, path + ".items") for item in normalized.get("items", [])]
        return normalized
    if condition_type == "not":
        normalized["item"] = normalize_condition(normalized.get("item"), path + ".item")
        return normalized
    if condition_type == "always":
        normalized["value"] = bool(normalized.get("value", True))
        return normalized
    if condition_type == "image":
        return normalized
    if condition_type == "compare":
        source = normalized.get("source")
        if source not in ("var", "runtime", "config", "feature"):
            raise MacroSchemaError("{} has invalid compare source.".format(path))
        if "key" not in normalized:
            raise MacroSchemaError("{} compare condition is missing key.".format(path))
        if source == "config":
            normalized["source"] = "runtime"
        elif source == "feature":
            normalized["source"] = "runtime"
            normalized["key"] = "{}.enabled".format(normalized["key"])
        normalized["op"] = normalized.get("op", "truthy")
        if "value" in normalized:
            normalized["value"] = normalize_value(normalized["value"], path + ".value")
        return normalized
    if condition_type == "region_color":
        normalized["region"] = normalize_region(normalized.get("region"), path + ".region")
        if "match" in normalized:
            normalized["match"] = {
                "low": list(normalized["match"]["low"]),
                "high": list(normalized["match"]["high"]),
            }
        else:
            normalized["channel"] = int(normalized.get("channel", 0))
            normalized["op"] = normalized.get("op", "gt")
        return normalized
    if condition_type == "plugin":
        plugin_name = normalized.get("plugin")
        if not plugin_name:
            raise MacroSchemaError("{} plugin condition is missing 'plugin'.".format(path))
        return normalized
    raise MacroSchemaError("{} has unsupported condition type '{}'".format(path, condition_type))


def normalize_compare_condition(source, key, condition, path):
    normalized_source = "runtime" if source in ("config", "feature") else source
    normalized_key = "{}.enabled".format(key) if source == "feature" else key
    normalized = {
        "type": "compare",
        "source": normalized_source,
        "key": normalized_key,
        "op": "truthy",
    }
    for operator in COMPARE_KEYS:
        if operator in condition:
            normalized["op"] = operator
            normalized["value"] = normalize_value(condition[operator], path + "." + operator)
            break
    return normalized


def normalize_value(value, path):
    if isinstance(value, dict):
        if "ref" in value:
            if value["ref"] not in ("var", "runtime", "config", "stats"):
                raise MacroSchemaError("{} has invalid ref '{}'".format(path, value["ref"]))
            if "key" not in value:
                raise MacroSchemaError("{} ref is missing key.".format(path))
            ref_name = "runtime" if value["ref"] == "config" else value["ref"]
            return {"ref": ref_name, "key": value["key"]}
        if "var" in value:
            return {"ref": "var", "key": value["var"]}
        if "config" in value:
            return {"ref": "runtime", "key": value["config"]}
        if "runtime" in value:
            return {"ref": "runtime", "key": value["runtime"]}
        if "stats" in value:
            return {"ref": "stats", "key": value["stats"]}
    return copy.deepcopy(value)


def normalize_region(region, path):
    if isinstance(region, list):
        if len(region) != 4:
            raise MacroSchemaError("{} must contain four numbers.".format(path))
        return {
            "x": int(region[0]),
            "y": int(region[1]),
            "w": int(region[2]),
            "h": int(region[3]),
        }
    if isinstance(region, dict):
        missing = [key for key in ("x", "y", "w", "h") if key not in region]
        if missing:
            raise MacroSchemaError("{} is missing {}.".format(path, ", ".join(missing)))
        return {
            "x": int(region["x"]),
            "y": int(region["y"]),
            "w": int(region["w"]),
            "h": int(region["h"]),
        }
    raise MacroSchemaError("{} must be [x, y, w, h] or {{x, y, w, h}}.".format(path))


def normalize_point(point, path):
    if isinstance(point, dict) and "x" in point and "y" in point:
        return {"x": int(point["x"]), "y": int(point["y"])}
    raise MacroSchemaError("{} must be an object with x and y.".format(path))
