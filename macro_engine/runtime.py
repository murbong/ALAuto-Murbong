import copy
import json
import importlib
import os
import time
from random import uniform

from macro_engine.driver import create_macro_driver
from macro_engine.schema import MacroSchemaError, normalize_macro
from util.logger import Logger

try:
    from util.utils import Region, Utils
except ImportError:
    Region = None
    Utils = None


class MacroValidationError(Exception):
    """Raised when a macro file is malformed."""


class MacroBreak(Exception):
    """Loop control signal."""


class MacroContinue(Exception):
    """Loop control signal."""


class MacroReturn(Exception):
    """Routine return signal."""

    def __init__(self, value=None):
        super().__init__()
        self.value = value


class MacroStopRequested(Exception):
    """Raised when the host requests macro execution to stop."""


class MacroContext(object):
    def __init__(self, config, stats, driver, macro_path=None, runtime=None):
        self.config = config
        self.stats = stats
        self.driver = driver
        self.macro_path = macro_path
        self.runtime = runtime or {}
        self.variables = {}
        self.regions = {}
        self.routines = {}
        self.plugin_state = {}


class MacroRunner(object):
    def __init__(self, config, stats, driver=None, event_listener=None, stop_requested=None):
        self.config = config
        self.stats = stats
        self.driver = driver or create_macro_driver(config)
        self.event_listener = event_listener
        self.stop_requested = stop_requested
        self._plugin_cache = {}

    def _emit_event(self, event_type, **payload):
        if self.event_listener is None:
            return
        event = {"type": event_type}
        event.update(payload)
        self.event_listener(event)

    def _check_stop_requested(self):
        if self.stop_requested is not None and self.stop_requested():
            self._emit_event("macro_stopped")
            raise MacroStopRequested()

    def load_macro(self, path):
        with open(path, "r", encoding="utf-8-sig") as handle:
            macro = normalize_macro(json.load(handle))
        self.validate_macro(macro, path)
        return macro

    def validate_macro(self, macro, path="<memory>"):
        if not isinstance(macro, dict):
            raise MacroValidationError("{} must contain a JSON object.".format(path))
        try:
            macro = normalize_macro(macro)
        except MacroSchemaError as error:
            raise MacroValidationError(str(error))
        if not isinstance(macro.get("steps"), list):
            raise MacroValidationError("{} is missing a top-level 'steps' list.".format(path))
        if "regions" in macro and not isinstance(macro["regions"], dict):
            raise MacroValidationError("{} has an invalid 'regions' section.".format(path))
        if "routines" in macro and not isinstance(macro["routines"], dict):
            raise MacroValidationError("{} has an invalid 'routines' section.".format(path))
        self._validate_steps(macro["steps"], path)
        for name, steps in macro.get("routines", {}).items():
            if not isinstance(steps, list):
                raise MacroValidationError("{} routine '{}' must be a list.".format(path, name))
            self._validate_steps(steps, path)

    def _validate_steps(self, steps, path):
        for step in steps:
            if not isinstance(step, dict):
                raise MacroValidationError("{} contains a non-object step.".format(path))
            if "action" not in step:
                raise MacroValidationError("{} contains a step without 'action'.".format(path))
            action = step["action"]
            if action in ("if", "while") and "condition" not in step:
                raise MacroValidationError("{} contains '{}' without 'condition'.".format(path, action))
            if action in ("if", "while", "repeat") and "steps" not in step:
                raise MacroValidationError("{} contains '{}' without 'steps'.".format(path, action))

    def run_path(self, path, variables=None, runtime=None):
        macro = self.load_macro(path)
        return self.run_macro(macro, path=path, variables=variables, runtime=runtime)

    def run_macro(self, macro, path="<memory>", variables=None, runtime=None):
        resolved_runtime = self._merge_runtime(self.config, runtime)
        resolved_runtime = self._merge_runtime(resolved_runtime, macro.get("runtime") if isinstance(macro, dict) else None)
        context = MacroContext(self.config, self.stats, self.driver, path, runtime=resolved_runtime)
        context.variables.update(variables or {})
        for name, value in macro.get("regions", {}).items():
            context.regions[name] = self._build_region(name, value)
        context.routines.update(macro.get("routines", {}))

        macro_name = macro.get("name", path)
        Logger.log_msg("Running macro '{}'.".format(macro_name))
        self._emit_event("macro_start", macro=macro_name, path=path)
        try:
            self._run_steps(macro["steps"], context)
        except MacroReturn as signal:
            self._emit_event("macro_end", macro=macro_name, path=path, result=signal.value)
            return signal.value
        self._emit_event("macro_end", macro=macro_name, path=path, result=None)
        return None

    def _build_region(self, name, value):
        if not isinstance(value, dict):
            raise MacroValidationError("Region '{}' must be an object with x, y, w, h.".format(name))
        if Region is None:
            raise MacroValidationError("Runtime dependencies are unavailable. Install requirements before running macros.")
        return Region(value["x"], value["y"], value["w"], value["h"])

    def _run_steps(self, steps, context, path_prefix=None):
        path_prefix = list(path_prefix or [])
        for index, step in enumerate(steps):
            self._check_stop_requested()
            self._run_step(step, context, path_prefix + [index])

    def _run_step(self, step, context, step_path):
        self._check_stop_requested()
        action = step["action"]
        self._emit_event("step_start", macro=context.macro_path, action=action, step=step, step_path=list(step_path), variables=dict(context.variables))
        try:
    
            if action == "log":
                Logger.log_msg(self._render(step.get("message", ""), context))
                return
    
            if action == "sleep":
                self._script_sleep(step.get("seconds"), step.get("flex"))
                return
    
            if action == "update_screen":
                context.driver.update_screen()
                self._emit_event("screen_update", frame=self._capture_frame(context))
                return
    
            if action == "wait_update_screen":
                context.driver.wait_update_screen(step.get("seconds"))
                self._emit_event("screen_update", frame=self._capture_frame(context))
                return
    
            if action == "tap_region":
                context.driver.tap_region(self._resolve_region(step["region"], context))
                return
    
            if action == "tap_image":
                found = context.driver.tap_image(
                    step["image"],
                    step.get("similarity", self._default_similarity()),
                    step.get("color", False),
                    step.get("use_mask", False)
                )
                self._emit_event("image_action", image=step["image"], found=found, region=None, frame=self._capture_frame(context))
                if step.get("into"):
                    context.variables[step["into"]] = found
                return
    
            if action == "tap_found_image":
                region = self._find_region_from_step(step, context)
                if region is not None:
                    context.driver.tap_region(region)
                self._emit_event("image_action", image=step["image"], found=region is not None, region=self._region_to_dict(region), frame=self._capture_frame(context))
                if step.get("into"):
                    context.variables[step["into"]] = region is not None
                return
    
            if action == "back":
                context.driver.back()
                return
    
            if action == "swipe":
                context.driver.swipe(
                    step["from"]["x"],
                    step["from"]["y"],
                    step["to"]["x"],
                    step["to"]["y"],
                    step["duration_ms"]
                )
                return
    
            if action == "set":
                context.variables[step["var"]] = self._resolve_value(step.get("value"), context)
                return
    
            if action == "increment":
                name = step["var"]
                context.variables[name] = int(context.variables.get(name, 0)) + int(step.get("amount", 1))
                return
    
            if action == "stats_increment":
                method = getattr(context.stats, step["method"])
                method()
                return
    
            if action == "print_stats":
                oil_limit = self._resolve_value(step.get("oil_limit"), context)
                oil_value = context.driver.check_oil(oil_limit or 0)
                context.stats.print_stats(oil_value)
                return
    
            if action == "if":
                if self._evaluate_condition(step["condition"], context):
                    self._run_steps(step["steps"], context, step_path + ["steps"])
                else:
                    self._run_steps(step.get("else_steps", []), context, step_path + ["else_steps"])
                return
    
            if action == "while":
                max_iterations = step.get("max_iterations", 1000)
                iterations = 0
                while self._evaluate_condition(step["condition"], context):
                    self._check_stop_requested()
                    if iterations >= max_iterations:
                        Logger.log_warning("Macro loop reached max_iterations={}.".format(max_iterations))
                        break
                    iterations += 1
                    try:
                        self._run_steps(step["steps"], context, step_path + ["steps"])
                    except MacroContinue:
                        continue
                    except MacroBreak:
                        break
                return
    
            if action == "repeat":
                for _ in range(step.get("times", 1)):
                    self._check_stop_requested()
                    try:
                        self._run_steps(step["steps"], context, step_path + ["steps"])
                    except MacroContinue:
                        continue
                    except MacroBreak:
                        break
                return
    
            if action == "wait_for":
                condition = step["condition"]
                timeout = step.get("timeout", 10)
                poll = step.get("poll_seconds", 0.5)
                start = time.time()
                while time.time() - start <= timeout:
                    self._check_stop_requested()
                    context.driver.update_screen()
                    if self._evaluate_condition(condition, context):
                        if step.get("into"):
                            context.variables[step["into"]] = True
                        return
                    self._check_stop_requested()
                    self._interruptible_sleep(poll)
                if step.get("into"):
                    context.variables[step["into"]] = False
                self._run_steps(step.get("timeout_steps", []), context, step_path + ["timeout_steps"])
                return
    
            if action == "call":
                routine_name = step["routine"]
                if routine_name not in context.routines:
                    raise MacroValidationError("Unknown routine '{}'.".format(routine_name))
                try:
                    self._run_steps(context.routines[routine_name], context, ["routines", routine_name])
                    result = None
                except MacroReturn as signal:
                    result = signal.value
                if step.get("into"):
                    context.variables[step["into"]] = result
                return
    
            if action == "run_macro":
                macro_path = self._resolve_macro_path(step["path"], context)
                result = self.run_path(macro_path, variables=step.get("variables"), runtime=context.runtime)
                if step.get("into"):
                    context.variables[step["into"]] = result
                return

            if action == "plugin":
                result = self._run_plugin(step, context)
                if step.get("into"):
                    context.variables[step["into"]] = result
                return
    
            if action == "break":
                raise MacroBreak()
    
            if action == "continue":
                raise MacroContinue()
    
            if action == "return":
                raise MacroReturn(self._resolve_value(step.get("value"), context))
    
            raise MacroValidationError("Unsupported action '{}'.".format(action))
    
        finally:
            self._emit_event("step_end", macro=context.macro_path, action=action, step=step, variables=dict(context.variables))

    def _render(self, message, context):
        rendered = str(message)
        for name, value in context.variables.items():
            rendered = rendered.replace("{{" + name + "}}", str(value))
        return rendered

    def _resolve_region(self, name, context):
        if name not in context.regions:
            raise MacroValidationError("Unknown region '{}'.".format(name))
        return context.regions[name]

    def _resolve_value(self, value, context):
        if isinstance(value, dict) and value.get("ref") == "var":
            return context.variables.get(value["key"])
        if isinstance(value, dict) and value.get("ref") == "runtime":
            return self._resolve_runtime_value(value["key"], context)
        if isinstance(value, dict) and value.get("ref") == "stats":
            return self._resolve_stats_value(value["key"], context)
        if isinstance(value, dict) and "var" in value:
            return context.variables.get(value["var"])
        if isinstance(value, dict) and "runtime" in value:
            return self._resolve_runtime_value(value["runtime"], context)
        if isinstance(value, dict) and "stats" in value:
            return self._resolve_stats_value(value["stats"], context)
        return value

    def _resolve_runtime_value(self, path, context):
        if not path:
            return None
        current = context.runtime
        for part in str(path).split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                break
        return current

    def _runtime_to_data(self, value):
        if isinstance(value, dict):
            return {key: self._runtime_to_data(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._runtime_to_data(child) for child in value]
        if hasattr(value, "__dict__"):
            return {
                key: self._runtime_to_data(child)
                for key, child in vars(value).items()
                if not key.startswith("_")
            }
        return copy.deepcopy(value)

    def _resolve_stats_value(self, path, context):
        if not path:
            return None
        current = context.stats
        for part in str(path).split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                break
        return current

    def _merge_runtime(self, parent_runtime, local_runtime):
        merged = self._runtime_to_data(parent_runtime or {})
        incoming = self._runtime_to_data(local_runtime or {})
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_runtime(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    def _resolve_macro_path(self, path, context):
        if context.macro_path:
            base_dir = os.path.dirname(os.path.abspath(context.macro_path))
            candidate = os.path.abspath(os.path.join(base_dir, path))
            if os.path.exists(candidate):
                return candidate
        return path

    def _capture_frame(self, context):
        return context.driver.capture_frame()

    def _default_similarity(self):
        return getattr(Utils, 'DEFAULT_SIMILARITY', 0.95)

    def _script_sleep(self, seconds=None, flex=None):
        if seconds is None:
            duration = uniform(0.4, 0.7)
        else:
            base = float(seconds)
            extra = base if flex is None else float(flex)
            duration = uniform(base, base + max(0.0, extra))
        self._interruptible_sleep(duration)

    def _interruptible_sleep(self, duration, step=0.1):
        remaining = max(0.0, float(duration))
        while remaining > 0:
            self._check_stop_requested()
            current_step = min(step, remaining)
            time.sleep(current_step)
            remaining -= current_step

    def _region_to_dict(self, region):
        if region is None:
            return None
        return {"x": region.x, "y": region.y, "w": region.w, "h": region.h}

    def _find_region_from_step(self, step, context):
        return context.driver.find_image(
            step["image"],
            step.get("similarity", self._default_similarity()),
            step.get("color", False),
            step.get("interrupt_if_not_found", False),
            step.get("use_mask", False)
        )

    def _evaluate_condition(self, condition, context):
        if not isinstance(condition, dict):
            return bool(condition)

        condition_type = condition.get("type")

        if condition_type == "all":
            return all(self._evaluate_condition(item, context) for item in condition.get("items", []))
        if condition_type == "any":
            return any(self._evaluate_condition(item, context) for item in condition.get("items", []))
        if condition_type == "not":
            return not self._evaluate_condition(condition.get("item"), context)
        if condition_type == "always":
            return bool(condition.get("value", True))

        if condition_type == "image":
            region = context.driver.find_image(
                condition["image"],
                condition.get("similarity", self._default_similarity()),
                condition.get("color", False),
                condition.get("interrupt_if_not_found", False),
                condition.get("use_mask", False)
            )
            result = region is not None
            if result:
                x_between = condition.get("x_between")
                if x_between and not (x_between[0] < region.x < x_between[1]):
                    result = False
                y_between = condition.get("y_between")
                if y_between and not (y_between[0] < region.y < y_between[1]):
                    result = False
            self._emit_event("condition_image", image=condition["image"], found=result, region=self._region_to_dict(region), frame=self._capture_frame(context))
            return result

        if condition_type == "compare":
            source = condition["source"]
            if source == "var":
                left = context.variables.get(condition["key"])
            elif source == "runtime":
                left = self._resolve_runtime_value(condition["key"], context)
            else:
                left = None
            op = condition.get("op", "truthy")
            right = self._resolve_value(condition.get("value"), context)
            if op == "equals":
                return left == right
            if op == "not_equals":
                return left != right
            if op == "gt":
                return left is not None and left > right
            if op == "gte":
                return left is not None and left >= right
            if op == "lt":
                return left is not None and left < right
            if op == "lte":
                return left is not None and left <= right
            return bool(left)

        if condition_type == "region_color":
            spec = condition["region"]
            region = Region(spec["x"], spec["y"], spec["w"], spec["h"])
            color = context.driver.get_region_color_average(region)
            result = False
            match = condition.get("match")
            if match is not None:
                low = match.get("low")
                high = match.get("high")
                result = all(low[i] <= color[i] <= high[i] for i in range(3))
            else:
                channel = condition.get("channel", 0)
                op = condition.get("op", "gt")
                value = condition.get("value")
                if op == "gt":
                    result = color[channel] > value
                elif op == "lt":
                    result = color[channel] < value
                elif op == "gte":
                    result = color[channel] >= value
                elif op == "lte":
                    result = color[channel] <= value
                elif op == "equals":
                    result = color[channel] == value
            self._emit_event(
                "condition_region_color",
                region=self._region_to_dict(region),
                found=result,
                color=list(color),
                frame=self._capture_frame(context)
            )
            return result

        if condition_type == "plugin":
            result = bool(self._run_plugin(condition, context, is_condition=True))
            self._emit_event(
                "condition_plugin",
                plugin=condition.get("plugin"),
                found=result,
                frame=self._capture_frame(context)
            )
            return result

        return False

    def _run_plugin(self, spec, context, is_condition=False):
        plugin_name = spec.get("plugin")
        if not plugin_name:
            raise MacroValidationError("Plugin step/condition is missing 'plugin'.")
        plugin = self._load_plugin(plugin_name)
        payload = dict(spec)
        payload.pop("action", None)
        payload.pop("type", None)
        payload.pop("plugin", None)
        self._emit_event(
            "plugin_call",
            plugin=plugin_name,
            payload=payload,
            frame=self._capture_frame(context),
            is_condition=is_condition
        )
        return plugin(self, context, payload)

    def _load_plugin(self, plugin_name):
        module_name, _, function_name = str(plugin_name).rpartition(".")
        if not module_name or not function_name:
            raise MacroValidationError("Plugin '{}' must look like 'module.function'.".format(plugin_name))
        import_name = "macro_plugins.{}".format(module_name)
        try:
            module = importlib.import_module(import_name)
            module = importlib.reload(module)
        except ImportError as error:
            raise MacroValidationError("Failed to import plugin '{}': {}".format(plugin_name, error))
        plugin = getattr(module, function_name, None)
        if plugin is None or not callable(plugin):
            raise MacroValidationError("Plugin '{}' was not found.".format(plugin_name))
        self._plugin_cache[plugin_name] = plugin
        return plugin
