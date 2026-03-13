import configparser
import json
import re
import sys
from copy import deepcopy

import util.config_consts
from util.logger import Logger


class Config(object):
    """Application config loaded from JSON, with legacy INI support."""

    def __init__(self, config_file):
        Logger.log_msg("Initializing config module")
        self.config_file = config_file
        self.ok = False
        self.initialized = False
        self.changed = False
        self.updates = {"enabled": False}
        self.combat = {"enabled": False}
        self.commissions = {"enabled": False}
        self.enhancement = {"enabled": False}
        self.missions = {"enabled": False}
        self.retirement = {"enabled": False}
        self.dorm = {"enabled": False}
        self.academy = {"enabled": False}
        self.research = {"enabled": False}
        self.events = {"enabled": False}
        self.network = {}
        self.assets = {}
        self.screenshot = {}
        self.driver = {'type': 'adb'}
        self.read()

    @classmethod
    def from_dict(cls, data, source="<memory>"):
        instance = cls.__new__(cls)
        instance.config_file = source
        instance.ok = False
        instance.initialized = False
        instance.changed = False
        instance.updates = {"enabled": False}
        instance.combat = {"enabled": False}
        instance.commissions = {"enabled": False}
        instance.enhancement = {"enabled": False}
        instance.missions = {"enabled": False}
        instance.retirement = {"enabled": False}
        instance.dorm = {"enabled": False}
        instance.academy = {"enabled": False}
        instance.research = {"enabled": False}
        instance.events = {"enabled": False}
        instance.network = {}
        instance.assets = {}
        instance.screenshot = {}
        instance.driver = {'type': 'adb'}
        Logger.log_msg("Initializing config module")
        instance._apply_json_data(data)
        instance.validate()
        if not instance.ok:
            Logger.log_error("Invalid config. Please check your config file.")
            sys.exit(1)
        Logger.log_msg("Starting ALAuto!")
        if instance.combat["enabled"] and instance.combat["ignore_morale"]:
            Logger.log_warning("Ignore morale is enabled")
        instance.initialized = True
        instance.changed = True
        return instance

    def try_cast_to_int(self, val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return val

    def try_cast_to_float(self, val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return val

    def read(self):
        backup_config = deepcopy(self.__dict__)
        if str(self.config_file).lower().endswith(".json"):
            self._read_json_file()
        else:
            self._read_ini_file()

        self.validate()
        if self.ok and not self.initialized:
            Logger.log_msg("Starting ALAuto!")
            if self.combat["enabled"] and self.combat["ignore_morale"]:
                Logger.log_warning("Ignore morale is enabled")
            self.initialized = True
            self.changed = True
        elif not self.ok and not self.initialized:
            Logger.log_error("Invalid config. Please check your config file.")
            sys.exit(1)
        elif not self.ok and self.initialized:
            Logger.log_warning("Config change detected, but with problems. Rolling back config.")
            self._rollback_config(backup_config)
        elif self.ok and self.initialized and backup_config != self.__dict__:
            Logger.log_warning("Config change detected. Hot-reloading.")
            self.changed = True

    def _read_json_file(self):
        with open(self.config_file, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        self._apply_json_data(data)

    def _read_ini_file(self):
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding="utf-8-sig")
        self.network["service"] = config.get("Network", "Service")
        self._read_screenshot_ini(config)
        self.assets["server"] = config.get("Assets", "Server")

        if config.getboolean("Updates", "Enabled"):
            self._read_updates_ini(config)
        if config.getboolean("Combat", "Enabled"):
            self._read_combat_ini(config)
        if config.getboolean("Headquarters", "Dorm") or config.getboolean("Headquarters", "Academy"):
            self._read_headquarters_ini(config)

        self.commissions["enabled"] = config.getboolean("Modules", "Commissions")
        self.missions["enabled"] = config.getboolean("Modules", "Missions")

        if config.getboolean("Enhancement", "Enabled"):
            self._read_enhancement_ini(config)
        self._read_retirement_ini(config)
        if config.getboolean("Research", "Enabled"):
            self._read_research_ini(config)
        if config.getboolean("Events", "Enabled"):
            self._read_event_ini(config)

    def _apply_json_data(self, data):
        self.driver = self._merge_section({'type': 'adb'}, data.get('driver'))
        driver_type = str(self.driver.get('type', 'adb')).strip().lower()
        if driver_type == 'adb':
            self.network = {
                "service": self._require_string(data, ["network", "service"])
            }
            self.screenshot = {
                "mode": self._parse_screenshot_mode(self._require_value(data, ["screenshot", "mode"]))
            }
        else:
            self.network = self._merge_section({}, data.get('network'))
            screenshot = self._merge_section({}, data.get('screenshot'))
            if 'mode' in screenshot:
                screenshot['mode'] = self._parse_screenshot_mode(screenshot['mode'])
            self.screenshot = screenshot
        self.assets = {
            "server": self._require_string(data, ["assets", "server"]).upper()
        }

        self.updates = self._merge_section({"enabled": False}, data.get("updates"))
        self.combat = self._merge_section({"enabled": False}, data.get("combat"))
        self.commissions = self._merge_section({"enabled": False}, data.get("commissions"))
        self.enhancement = self._merge_section({"enabled": False}, data.get("enhancement"))
        self.missions = self._merge_section({"enabled": False}, data.get("missions"))
        self.retirement = self._merge_section({"enabled": False}, data.get("retirement"))
        self.dorm = self._merge_section({"enabled": False}, data.get("dorm"))
        self.academy = self._merge_section({"enabled": False}, data.get("academy"))
        self.research = self._merge_section({"enabled": False}, data.get("research"))
        self.events = self._merge_section({"enabled": False}, data.get("events"))

        if self.updates["enabled"]:
            self.updates["channel"] = self._require_string(data, ["updates", "channel"])
        if self.combat["enabled"]:
            self._normalize_combat_json()
        if self.dorm["enabled"]:
            self.dorm["AvailableSupplies"] = self._ensure_list(self.dorm.get("AvailableSupplies"))
        if self.academy["enabled"]:
            self.academy["skill_book_tier"] = self.try_cast_to_int(self.academy.get("skill_book_tier"))
        if self.enhancement["enabled"]:
            self.enhancement["single_enhancement"] = bool(self.enhancement.get("single_enhancement", False))
        if self.retirement["enabled"]:
            self.retirement["rares"] = bool(self.retirement.get("rares", True))
            self.retirement["commons"] = bool(self.retirement.get("commons", True))
        if self.research["enabled"]:
            self._normalize_research_json()
        if self.events["enabled"]:
            self.events["name"] = self._require_string(data, ["events", "name"])
            self.events["levels"] = self._ensure_list(self.events.get("levels"))
            self.events["ignore_rateup"] = bool(self.events.get("ignore_rateup", False))

    def _normalize_combat_json(self):
        self.combat["map"] = str(self.combat.get("map", ""))
        self.combat["kills_before_boss"] = self.try_cast_to_int(self.combat.get("kills_before_boss"))
        self.combat["boss_fleet"] = bool(self.combat.get("boss_fleet", False))
        self.combat["oil_limit"] = self.try_cast_to_int(self.combat.get("oil_limit"))
        self.combat["retire_cycle"] = self.try_cast_to_int(self.combat.get("retire_cycle"))
        self.combat["retreat_after"] = self.try_cast_to_int(self.combat.get("retreat_after"))
        self.combat["ignore_mystery_nodes"] = bool(self.combat.get("ignore_mystery_nodes", False))
        self.combat["focus_on_mystery_nodes"] = bool(self.combat.get("focus_on_mystery_nodes", False))
        self.combat["clearing_mode"] = bool(self.combat.get("clearing_mode", False))
        self.combat["hide_subs_hunting_range"] = bool(self.combat.get("hide_subs_hunting_range", False))
        self.combat["small_boss_icon"] = bool(self.combat.get("small_boss_icon", False))
        self.combat["siren_elites"] = bool(self.combat.get("siren_elites", False))
        self.combat["ignore_morale"] = bool(self.combat.get("ignore_morale", False))
        self.combat["low_mood_sleep_time"] = self.try_cast_to_float(self.combat.get("low_mood_sleep_time"))
        self.combat["search_mode"] = self.try_cast_to_int(self.combat.get("search_mode"))

    def _normalize_research_json(self):
        keys = [
            "AllowFreeProjects",
            "AllowConsumingCoins",
            "AllowConsumingCubes",
            "WithoutRequirements",
            "AwardMustContainPRBlueprint",
            "30Minutes",
            "1Hour",
            "1Hour30Minutes",
            "2Hours",
            "2Hours30Minutes",
            "4Hours",
            "5Hours",
            "6Hours",
            "8Hours",
            "12Hours",
        ]
        for key in keys:
            self.research[key] = bool(self.research.get(key, False))

    def _merge_section(self, defaults, value):
        merged = dict(defaults)
        if isinstance(value, dict):
            merged.update(value)
        return merged

    def _require_value(self, data, path):
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                raise KeyError("Missing config field: {}".format(".".join(path)))
            current = current[key]
        return current

    def _require_string(self, data, path):
        value = self._require_value(data, path)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Invalid config field: {}".format(".".join(path)))
        return value.strip()

    def _ensure_list(self, value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [part for part in re.split(r"\s*,\s*|\s+", value.strip()) if part]
        return []

    def _parse_screenshot_mode(self, raw):
        consts = util.config_consts.UtilConsts.ScreenCapMode
        key = str(raw).upper()
        mapping = {
            "SCREENCAP_PNG": consts.SCREENCAP_PNG,
            "SCREENCAP_RAW": consts.SCREENCAP_RAW,
            "ASCREENCAP": consts.ASCREENCAP,
        }
        if key not in mapping:
            raise ValueError("Unsupported screenshot mode: {}".format(raw))
        return mapping[key]

    def _read_retirement_ini(self, config):
        if "Retirement" in config:
            self.retirement["enabled"] = config.getboolean("Retirement", "enabled", fallback=False)
            self.retirement["rares"] = config.getboolean("Retirement", "Rares", fallback=True)
            self.retirement["commons"] = config.getboolean("Retirement", "Commons", fallback=True)
            return
        if config.has_option("Modules", "Retirement"):
            self.retirement["enabled"] = config.getboolean("Modules", "Retirement")
            self.retirement["rares"] = True
            self.retirement["commons"] = True

    def _read_screenshot_ini(self, config):
        consts = util.config_consts.UtilConsts.ScreenCapMode
        self.screenshot["mode"] = self._validate_list(
            config.get("Screenshot", "Mode"),
            min_len=1,
            max_len=1,
            valid_vals=["SCREENCAP_PNG", "SCREENCAP_RAW", "ASCREENCAP"],
            map_vals=[consts.SCREENCAP_PNG, consts.SCREENCAP_RAW, consts.ASCREENCAP],
            cast=lambda x: x.upper(),
        )[0]

    def _read_updates_ini(self, config):
        self.updates["enabled"] = True
        self.updates["channel"] = config.get("Updates", "Channel")

    def _read_combat_ini(self, config):
        self.combat["enabled"] = True
        self.combat["map"] = config.get("Combat", "Map")
        self.combat["kills_before_boss"] = self.try_cast_to_int(config.get("Combat", "KillsBeforeBoss"))
        self.combat["boss_fleet"] = config.getboolean("Combat", "BossFleet")
        self.combat["oil_limit"] = self.try_cast_to_int(config.get("Combat", "OilLimit"))
        self.combat["retire_cycle"] = self.try_cast_to_int(config.get("Combat", "RetireCycle"))
        self.combat["retreat_after"] = self.try_cast_to_int(config.get("Combat", "RetreatAfter"))
        self.combat["ignore_mystery_nodes"] = config.getboolean("Combat", "IgnoreMysteryNodes")
        self.combat["focus_on_mystery_nodes"] = config.getboolean("Combat", "FocusOnMysteryNodes")
        self.combat["clearing_mode"] = config.getboolean("Combat", "ClearingMode")
        self.combat["hide_subs_hunting_range"] = config.getboolean("Combat", "HideSubsHuntingRange")
        self.combat["small_boss_icon"] = config.getboolean("Combat", "SmallBossIcon")
        self.combat["siren_elites"] = config.getboolean("Combat", "SirenElites")
        self.combat["ignore_morale"] = config.getboolean("Combat", "IgnoreMorale")
        self.combat["low_mood_sleep_time"] = self.try_cast_to_float(config.get("Combat", "LowMoodSleepTime"))
        self.combat["search_mode"] = self.try_cast_to_int(config.get("Combat", "SearchMode"))

    def _read_headquarters_ini(self, config):
        self.dorm["enabled"] = config.getboolean("Headquarters", "Dorm")
        if self.dorm["enabled"]:
            self.dorm["AvailableSupplies"] = self._validate_list(
                config.get("Headquarters", "AvailableSupplies"),
                valid_vals=[1000, 2000, 3000, 5000, 10000, 20000],
                min_len=1,
                max_len=6,
                cast=int,
                unique=True,
            )
        self.academy["enabled"] = config.getboolean("Headquarters", "Academy")
        if self.academy["enabled"]:
            self.academy["skill_book_tier"] = self.try_cast_to_int(config.get("Headquarters", "SkillBookTier"))

    def _read_enhancement_ini(self, config):
        self.enhancement["enabled"] = True
        self.enhancement["single_enhancement"] = config.getboolean("Enhancement", "SingleEnhancement")

    def _read_research_ini(self, config):
        self.research["enabled"] = True
        self.research["AllowFreeProjects"] = config.getboolean("Research", "AllowFreeProjects")
        self.research["AllowConsumingCoins"] = config.getboolean("Research", "AllowConsumingCoins")
        self.research["AllowConsumingCubes"] = config.getboolean("Research", "AllowConsumingCubes")
        self.research["WithoutRequirements"] = config.getboolean("Research", "WithoutRequirements")
        self.research["AwardMustContainPRBlueprint"] = config.getboolean("Research", "AwardMustContainPRBlueprint")
        self.research["30Minutes"] = config.getboolean("Research", "30Minutes")
        self.research["1Hour"] = config.getboolean("Research", "1Hour")
        self.research["1Hour30Minutes"] = config.getboolean("Research", "1Hour30Minutes")
        self.research["2Hours"] = config.getboolean("Research", "2Hours")
        self.research["2Hours30Minutes"] = config.getboolean("Research", "2Hours30Minutes")
        self.research["4Hours"] = config.getboolean("Research", "4Hours")
        self.research["5Hours"] = config.getboolean("Research", "5Hours")
        self.research["6Hours"] = config.getboolean("Research", "6Hours")
        self.research["8Hours"] = config.getboolean("Research", "8Hours")
        self.research["12Hours"] = config.getboolean("Research", "12Hours")

    def _read_event_ini(self, config):
        self.events["enabled"] = True
        self.events["name"] = config.get("Events", "Event")
        self.events["levels"] = config.get("Events", "Levels").split(",")
        self.events["ignore_rateup"] = config.getboolean("Events", "IgnoreRateUp")

    def validate(self):
        if not self.initialized:
            Logger.log_msg("Validating config")
        self.ok = True

        valid_servers = ["EN", "JP", "KR"]
        if self.assets["server"] not in valid_servers:
            if len(valid_servers) < 2:
                Logger.log_error("Invalid server assets configured. Only {} is supported.".format("".join(valid_servers)))
            else:
                Logger.log_error(
                    "Invalid server assets configured. Only {} and {} are supported.".format(
                        ", ".join(valid_servers[:-1]), valid_servers[-1]
                    )
                )
            self.ok = False

        if not self.combat["enabled"] and not self.commissions["enabled"] and not self.enhancement["enabled"] \
           and not self.missions["enabled"] and not self.retirement["enabled"] and not self.research["enabled"] \
           and not self.events["enabled"] and not self.dorm["enabled"] and not self.academy["enabled"]:
            Logger.log_error("All modules are disabled, consider checking your config.")
            self.ok = False

        if self.updates["enabled"]:
            if self.updates["channel"] not in ("Release", "Development"):
                self.ok = False
                Logger.log_error("Invalid update channel, please check the wiki.")

        if self.combat["enabled"]:
            map_parts = self.combat["map"].split("-")
            valid_chapters = list(range(1, 14)) + ["E"]
            valid_levels = list(range(1, 5)) + [
                "A1", "A2", "A3", "A4",
                "B1", "B2", "B3", "B4",
                "C1", "C2", "C3", "C4",
                "D1", "D2", "D3", "D4",
                "SP1", "SP2", "SP3", "SP4", "SP5",
            ]
            if len(map_parts) != 2 or self.try_cast_to_int(map_parts[0]) not in valid_chapters or self.try_cast_to_int(map_parts[1]) not in valid_levels:
                self.ok = False
                Logger.log_error("Invalid Map Selected: '{}'.".format(self.combat["map"]))

            if not isinstance(self.combat["oil_limit"], int):
                self.ok = False
                Logger.log_error("Oil limit must be an integer.")
            if not isinstance(self.combat["retire_cycle"], int) or self.combat["retire_cycle"] <= 0:
                self.ok = False
                Logger.log_error("RetireCycle must be an integer > 0.")
            if map_parts[0] != "E" and self.combat["siren_elites"]:
                self.ok = False
                Logger.log_error("Story maps don't have elite units.")
            if not isinstance(self.combat["kills_before_boss"], int) or self.combat["kills_before_boss"] < 0:
                self.ok = False
                Logger.log_error("Invalid KillsBeforeBoss value: must be an integer >= 0.")
            if not isinstance(self.combat["retreat_after"], int) or self.combat["retreat_after"] < 0:
                self.ok = False
                Logger.log_error("Invalid RetreatAfter value: must be an integer >= 0.")
            if map_parts[0] != "E" and self.combat["small_boss_icon"]:
                self.ok = False
                Logger.log_error("Story maps don't have small boss icon.")
            if not isinstance(self.combat["low_mood_sleep_time"], float) or self.combat["low_mood_sleep_time"] < 0:
                self.ok = False
                Logger.log_error("LowMoodSleepTime must be a float > 0.")
            if self.combat["search_mode"] not in [0, 1]:
                self.ok = False
                Logger.log_error("Wrong search mode. Allowed values: [0, 1].")

        if self.academy["enabled"]:
            tier = self.academy["skill_book_tier"]
            if not isinstance(tier, int) or not 1 <= tier <= 3:
                self.ok = False
                Logger.log_error("Skill book tier must be an integer between 1 and 3.")

        if self.events["enabled"]:
            events = ["Crosswave", "Royal_Maids"]
            stages = ["EX", "H", "N", "E"]
            if self.events["name"] not in events or all(elem not in stages for elem in self.events["levels"]):
                self.ok = False
                Logger.log_error("Invalid event settings, please check the wiki.")

        if self.retirement["enabled"] and not (self.retirement["commons"] or self.retirement["rares"]):
            Logger.log_error("Retirement is enabled, but no ship rarities are selected.")
            self.ok = False

        if self.research["enabled"]:
            if not (
                self.research["30Minutes"] or self.research["1Hour"] or self.research["1Hour30Minutes"] or
                self.research["2Hours"] or self.research["2Hours30Minutes"] or self.research["4Hours"] or
                self.research["5Hours"] or self.research["6Hours"] or self.research["8Hours"] or self.research["12Hours"]
            ):
                Logger.log_error("Research is enabled, but without allowed times.")
                self.ok = False

    def _rollback_config(self, config):
        for key in config:
            setattr(self, key, config[key])

    def _validate_list(self, val, min_len=None, max_len=None, valid_vals=None, map_vals=None, cast=None, unique=False):
        s_list = re.split(r"\s*,\s*|\s+", val)
        if min_len is not None and len(s_list) < min_len:
            raise ValueError()
        if max_len is not None and len(s_list) > max_len:
            raise ValueError()
        if s_list is not None and cast is not None:
            for index in range(len(s_list)):
                s_list[index] = cast(s_list[index])
        if valid_vals is not None:
            for index, value in enumerate(s_list):
                if value not in valid_vals:
                    raise ValueError()
                if map_vals is not None:
                    s_list[index] = map_vals[valid_vals.index(value)]
        if unique and len(set(s_list)) != len(s_list):
            raise ValueError()
        return s_list
