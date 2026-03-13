using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using ALAuto.Util;

namespace ALAuto.Util
{
    public class Config
    {
        private string _configFile;
        public bool Ok { get; private set; }
        public bool Initialized { get; private set; }
        public bool Changed { get; private set; }

        public NetworkConfig Network { get; private set; } = new NetworkConfig();
        public AssetsConfig Assets { get; private set; } = new AssetsConfig();
        public ScreenshotConfig Screenshot { get; private set; } = new ScreenshotConfig();
        public UpdatesConfig Updates { get; private set; } = new UpdatesConfig();
        public CombatConfig Combat { get; private set; } = new CombatConfig();
        public CommissionsConfig Commissions { get; private set; } = new CommissionsConfig();
        public EnhancementConfig Enhancement { get; private set; } = new EnhancementConfig();
        public MissionsConfig Missions { get; private set; } = new MissionsConfig();
        public RetirementConfig Retirement { get; private set; } = new RetirementConfig();
        public DormConfig Dorm { get; private set; } = new DormConfig();
        public AcademyConfig Academy { get; private set; } = new AcademyConfig();
        public ResearchConfig Research { get; private set; } = new ResearchConfig();
        public EventsConfig Events { get; private set; } = new EventsConfig();

        // Nested classes for configuration sections
        public class NetworkConfig { public string Service { get; set; } }
        public class AssetsConfig { public string Server { get; set; } }
        public class ScreenshotConfig { public UtilConsts.ScreenCapMode Mode { get; set; } }
        public class UpdatesConfig { public bool Enabled { get; set; } = false; public string Channel { get; set; } }
        public class CombatConfig
        {
            public bool Enabled { get; set; } = false;
            public string Map { get; set; }
            public int KillsBeforeBoss { get; set; }
            public bool BossFleet { get; set; }
            public int OilLimit { get; set; }
            public int RetireCycle { get; set; }
            public int RetreatAfter { get; set; }
            public bool IgnoreMysteryNodes { get; set; }
            public bool FocusOnMysteryNodes { get; set; }
            public bool ClearingMode { get; set; }
            public bool HideSubsHuntingRange { get; set; }
            public bool SmallBossIcon { get; set; }
            public bool SirenElites { get; set; }
            public bool IgnoreMorale { get; set; }
            public float LowMoodSleepTime { get; set; }
            public int SearchMode { get; set; }
        }
        public class CommissionsConfig { public bool Enabled { get; set; } = false; }
        public class EnhancementConfig { public bool Enabled { get; set; } = false; public bool SingleEnhancement { get; set; } }
        public class MissionsConfig { public bool Enabled { get; set; } = false; }
        public class RetirementConfig
        {
            public bool Enabled { get; set; } = false;
            public bool Rares { get; set; } = true;
            public bool Commons { get; set; } = true;
        }
        public class DormConfig { public bool Enabled { get; set; } = false; public List<int> AvailableSupplies { get; set; } }
        public class AcademyConfig { public bool Enabled { get; set; } = false; public int SkillBookTier { get; set; } }
        public class ResearchConfig
        {
            public bool Enabled { get; set; } = false;
            public bool AllowFreeProjects { get; set; }
            public bool AllowConsumingCoins { get; set; }
            public bool AllowConsumingCubes { get; set; }
            public bool WithoutRequirements { get; set; }
            public bool AwardMustContainPRBlueprint { get; set; }
            public bool Minutes30 { get; set; }
            public bool Hour1 { get; set; }
            public bool Hour1_30 { get; set; }
            public bool Hours2 { get; set; }
            public bool Hours2_30 { get; set; }
            public bool Hours4 { get; set; }
            public bool Hours5 { get; set; }
            public bool Hours6 { get; set; }
            public bool Hours8 { get; set; }
            public bool Hours12 { get; set; }
        }
        public class EventsConfig
        {
            public bool Enabled { get; set; } = false;
            public string Name { get; set; }
            public List<string> Levels { get; set; }
            public bool IgnoreRateUp { get; set; }
        }

        public Config(string configFile)
        {
            Logger.LogMsg("Initializing config module");
            _configFile = configFile;
            Read();
        }

        private int TryCastToInt(string val)
        {
            if (int.TryParse(val, out int result))
            {
                return result;
            }
            return 0; // Or throw an exception, depending on desired behavior
        }

        private float TryCastToFloat(string val)
        {
            if (float.TryParse(val, out float result))
            {
                return result;
            }
            return 0.0f; // Or throw an exception
        }

        public void Read()
        {
            // Simple INI parser placeholder
            var configData = new Dictionary<string, Dictionary<string, string>>();
            string currentSection = "";

            if (!File.Exists(_configFile))
            {
                Logger.LogError($"Config file not found: {_configFile}");
                Ok = false;
                return;
            }

            foreach (var line in File.ReadAllLines(_configFile))
            {
                string trimmedLine = line.Trim();
                if (string.IsNullOrWhiteSpace(trimmedLine) || trimmedLine.StartsWith(";") || trimmedLine.StartsWith("#"))
                {
                    continue; // Skip empty lines and comments
                }

                if (trimmedLine.StartsWith("[") && trimmedLine.EndsWith("]"))
                {
                    currentSection = trimmedLine.Substring(1, trimmedLine.Length - 2);
                    configData[currentSection] = new Dictionary<string, string>();
                }
                else if (currentSection != "" && trimmedLine.Contains("="))
                {
                    int eqIndex = trimmedLine.IndexOf('=');
                    string key = trimmedLine.Substring(0, eqIndex).Trim();
                    string value = trimmedLine.Substring(eqIndex + 1).Trim();
                    configData[currentSection][key] = value;
                }
            }

            // Populate properties from parsed data
            // Network
            Network.Service = GetConfigValue(configData, "Network", "Service");

            // Assets
            Assets.Server = GetConfigValue(configData, "Assets", "Server");

            // Screenshot
            _ReadScreenshot(configData);

            // Updates
            if (GetConfigBoolean(configData, "Updates", "Enabled"))
            {
                _ReadUpdates(configData);
            }

            // Combat
            if (GetConfigBoolean(configData, "Combat", "Enabled"))
            {
                _ReadCombat(configData);
            }

            // Headquarters
            if (GetConfigBoolean(configData, "Headquarters", "Dorm") || GetConfigBoolean(configData, "Headquarters", "Academy"))
            {
                _ReadHeadquarters(configData);
            }

            // Modules
            Commissions.Enabled = GetConfigBoolean(configData, "Modules", "Commissions");
            Missions.Enabled = GetConfigBoolean(configData, "Modules", "Missions");

            // Enhancement
            if (GetConfigBoolean(configData, "Enhancement", "Enabled"))
            {
                _ReadEnhancement(configData);
            }

            // Retirement
            if (configData.ContainsKey("Retirement"))
            {
                Retirement.Enabled = GetConfigBoolean(configData, "Retirement", "enabled", false);
                Retirement.Rares = GetConfigBoolean(configData, "Retirement", "Rares", true);
                Retirement.Commons = GetConfigBoolean(configData, "Retirement", "Commons", true);
            }
            else if (configData.ContainsKey("Modules") && configData["Modules"].ContainsKey("Retirement"))
            {
                Retirement.Enabled = GetConfigBoolean(configData, "Modules", "Retirement");
                Retirement.Rares = true;
                Retirement.Commons = true;
            }

            // Research
            if (GetConfigBoolean(configData, "Research", "Enabled"))
            {
                _ReadResearch(configData);
            }

            // Events
            if (GetConfigBoolean(configData, "Events", "Enabled"))
            {
                _ReadEvent(configData);
            }

            Validate();

            if (Ok && !Initialized)
            {
                Logger.LogMsg("Starting ALAuto!");
                if (Combat.Enabled && Combat.IgnoreMorale)
                {
                    Logger.LogWarning("Ignore morale is enabled");
                }
                Initialized = true;
                Changed = true;
            }
            else if (!Ok && !Initialized)
            {
                Logger.LogError("Invalid config. Please check your config file.");
                Environment.Exit(1);
            }
            else if (!Ok && Initialized)
            {
                Logger.LogWarning("Config change detected, but with problems. Rolling back config.");
                // _RollbackConfig(backup_config); // Need to implement deep copy for rollback
            }
            else if (Ok && Initialized)
            {
                // if (backup_config != this.__dict__) // Need to implement comparison
                // {
                //     Logger.LogWarning("Config change detected. Hot-reloading.");
                //     Changed = true;
                // }
            }
        }

        private string GetConfigValue(Dictionary<string, Dictionary<string, string>> configData, string section, string key, string defaultValue = null)
        {
            if (configData.ContainsKey(section) && configData[section].ContainsKey(key))
            {
                return configData[section][key];
            }
            return defaultValue;
        }

        private bool GetConfigBoolean(Dictionary<string, Dictionary<string, string>> configData, string section, string key, bool defaultValue = false)
        {
            string value = GetConfigValue(configData, section, key);
            if (bool.TryParse(value, out bool result))
            {
                return result;
            }
            return defaultValue;
        }

        private int GetConfigInt(Dictionary<string, Dictionary<string, string>> configData, string section, string key, int defaultValue = 0)
        {
            string value = GetConfigValue(configData, section, key);
            if (int.TryParse(value, out int result))
            {
                return result;
            }
            return defaultValue;
        }

        private float GetConfigFloat(Dictionary<string, Dictionary<string, string>> configData, string section, string key, float defaultValue = 0.0f)
        {
            string value = GetConfigValue(configData, section, key);
            if (float.TryParse(value, out float result))
            {
                return result;
            }
            return defaultValue;
        }

        private void _ReadScreenshot(Dictionary<string, Dictionary<string, string>> configData)
        {
            string modeStr = GetConfigValue(configData, "Screenshot", "Mode");
            if (Enum.TryParse(modeStr.ToUpper(), out UtilConsts.ScreenCapMode modeEnum))
            {
                Screenshot.Mode = modeEnum;
            }
            else
            {
                // Handle invalid mode string, perhaps default or log error
                Logger.LogError($"Invalid Screenshot Mode: {modeStr}");
                Ok = false;
            }
        }

        private void _ReadUpdates(Dictionary<string, Dictionary<string, string>> configData)
        {
            Updates.Enabled = true;
            Updates.Channel = GetConfigValue(configData, "Updates", "Channel");
        }

        private void _ReadCombat(Dictionary<string, Dictionary<string, string>> configData)
        {
            Combat.Enabled = true;
            Combat.Map = GetConfigValue(configData, "Combat", "Map");
            Combat.KillsBeforeBoss = GetConfigInt(configData, "Combat", "KillsBeforeBoss");
            Combat.BossFleet = GetConfigBoolean(configData, "Combat", "BossFleet");
            Combat.OilLimit = GetConfigInt(configData, "Combat", "OilLimit");
            Combat.RetireCycle = GetConfigInt(configData, "Combat", "RetireCycle");
            Combat.RetreatAfter = GetConfigInt(configData, "Combat", "RetreatAfter");
            Combat.IgnoreMysteryNodes = GetConfigBoolean(configData, "Combat", "IgnoreMysteryNodes");
            Combat.FocusOnMysteryNodes = GetConfigBoolean(configData, "Combat", "FocusOnMysteryNodes");
            Combat.ClearingMode = GetConfigBoolean(configData, "Combat", "ClearingMode");
            Combat.HideSubsHuntingRange = GetConfigBoolean(configData, "Combat", "HideSubsHuntingRange");
            Combat.SmallBossIcon = GetConfigBoolean(configData, "Combat", "SmallBossIcon");
            Combat.SirenElites = GetConfigBoolean(configData, "Combat", "SirenElites");
            Combat.IgnoreMorale = GetConfigBoolean(configData, "Combat", "IgnoreMorale");
            Combat.LowMoodSleepTime = GetConfigFloat(configData, "Combat", "LowMoodSleepTime");
            Combat.SearchMode = GetConfigInt(configData, "Combat", "SearchMode");
        }

        private void _ReadHeadquarters(Dictionary<string, Dictionary<string, string>> configData)
        {
            Dorm.Enabled = GetConfigBoolean(configData, "Headquarters", "Dorm");
            if (Dorm.Enabled)
            {
                Dorm.AvailableSupplies = ValidateList<int>(GetConfigValue(configData, "Headquarters", "AvailableSupplies"),
                                                                 new List<int> { 1000, 2000, 3000, 5000, 10000, 20000 },
                                                                 1, 6, true);
            }
            Academy.Enabled = GetConfigBoolean(configData, "Headquarters", "Academy");
            if (Academy.Enabled)
            {
                Academy.SkillBookTier = GetConfigInt(configData, "Headquarters", "SkillBookTier");
            }
        }

        private void _ReadEnhancement(Dictionary<string, Dictionary<string, string>> configData)
        {
            Enhancement.Enabled = true;
            Enhancement.SingleEnhancement = GetConfigBoolean(configData, "Enhancement", "SingleEnhancement");
        }

        private void _ReadResearch(Dictionary<string, Dictionary<string, string>> configData)
        {
            Research.Enabled = true;
            Research.AllowFreeProjects = GetConfigBoolean(configData, "Research", "AllowFreeProjects");
            Research.AllowConsumingCoins = GetConfigBoolean(configData, "Research", "AllowConsumingCoins");
            Research.AllowConsumingCubes = GetConfigBoolean(configData, "Research", "AllowConsumingCubes");
            Research.WithoutRequirements = GetConfigBoolean(configData, "Research", "WithoutRequirements");
            Research.AwardMustContainPRBlueprint = GetConfigBoolean(configData, "Research", "AwardMustContainPRBlueprint");
            Research.Minutes30 = GetConfigBoolean(configData, "Research", "30Minutes");
            Research.Hour1 = GetConfigBoolean(configData, "Research", "1Hour");
            Research.Hour1_30 = GetConfigBoolean(configData, "Research", "1Hour30Minutes");
            Research.Hours2 = GetConfigBoolean(configData, "Research", "2Hours");
            Research.Hours2_30 = GetConfigBoolean(configData, "Research", "2Hours30Minutes");
            Research.Hours4 = GetConfigBoolean(configData, "Research", "4Hours");
            Research.Hours5 = GetConfigBoolean(configData, "Research", "5Hours");
            Research.Hours6 = GetConfigBoolean(configData, "Research", "6Hours");
            Research.Hours8 = GetConfigBoolean(configData, "Research", "8Hours");
            Research.Hours12 = GetConfigBoolean(configData, "Research", "12Hours");
        }

        private void _ReadEvent(Dictionary<string, Dictionary<string, string>> configData)
        {
            Events.Enabled = true;
            Events.Name = GetConfigValue(configData, "Events", "Event");
            Events.Levels = GetConfigValue(configData, "Events", "Levels").Split(',').Select(s => s.Trim()).ToList();
            Events.IgnoreRateUp = GetConfigBoolean(configData, "Events", "IgnoreRateUp");
        }

        public void Validate()
        {
            if (!Initialized)
            {
                Logger.LogMsg("Validating config");
            }
            Ok = true;

            List<string> validServers = new List<string> { "EN", "JP", "KR" };
            if (!validServers.Contains(Assets.Server))
            {
                if (validServers.Count < 2)
                {
                    Logger.LogError($"Invalid server assets configured. Only {string.Join("", validServers)} is supported.");
                }
                else
                {
                    Logger.LogError($"Invalid server assets configured. Only {string.Join(", ", validServers.Take(validServers.Count - 1))} and {validServers.Last()} are supported.");
                }
                Ok = false;
            }

            if (!Combat.Enabled && !Commissions.Enabled && !Enhancement.Enabled &&
                !Missions.Enabled && !Retirement.Enabled && !Research.Enabled &&
                !Events.Enabled && !Dorm.Enabled && !Academy.Enabled)
            {
                Logger.LogError("All modules are disabled, consider checking your config.");
                Ok = false;
            }

            if (Updates.Enabled)
            {
                if (Updates.Channel != "Release" && Updates.Channel != "Development")
                {
                    Ok = false;
                    Logger.LogError("Invalid update channel, please check the wiki.");
                }
            }

            if (Combat.Enabled)
            {
                string[] mapParts = Combat.Map.Split('-');
                List<object> validChapters = Enumerable.Range(1, 13).Cast<object>().ToList();
                validChapters.Add("E");
                List<string> validLevels = Enumerable.Range(1, 4).Select(i => i.ToString()).ToList();
                validLevels.AddRange(new List<string> { "A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "D1", "D2", "D3", "D4", "SP1", "SP2", "SP3", "SP4", "SP5" });

                object chapterPart = TryCastToInt(mapParts[0]);
                if (chapterPart.Equals(0)) chapterPart = mapParts[0]; // If not int, keep as string for 'E'

                if (!validChapters.Contains(chapterPart) || !validLevels.Contains(mapParts[1]))
                {
                    Ok = false;
                    Logger.LogError($"Invalid Map Selected: '{Combat.Map}'.");
                }

                if (Combat.OilLimit < 0) // Python's isinstance(val, int) check is implicitly handled by TryCastToInt returning 0 for non-int
                {
                    Ok = false;
                    Logger.LogError("Oil limit must be an integer.");
                }

                if (Combat.RetireCycle <= 0)
                {
                    Ok = false;
                    Logger.LogError("RetireCycle must be an integer > 0.");
                }

                if (mapParts[0] != "E" && Combat.SirenElites)
                {
                    Ok = false;
                    Logger.LogError("Story maps don't have elite units.");
                }

                if (Combat.KillsBeforeBoss < 0)
                {
                    Ok = false;
                    Logger.LogError("Invalid KillsBeforeBoss value: must be an integer >= 0.");
                }

                if (Combat.RetreatAfter < 0)
                {
                    Ok = false;
                    Logger.LogError("Invalid RetreatAfter value: must be an integer >= 0.");
                }

                if (mapParts[0] != "E" && Combat.SmallBossIcon)
                {
                    Ok = false;
                    Logger.LogError("Story maps don't have small boss icon.");
                }

                if (Combat.LowMoodSleepTime < 0)
                {
                    Ok = false;
                    Logger.LogError("LowMoodSleepTime must be a float > 0.");
                }

                if (Combat.SearchMode != 0 && Combat.SearchMode != 1)
                {
                    Ok = false;
                    Logger.LogError("Wrong search mode. Allowed values: [0, 1].");
                }
            }

            if (Academy.Enabled)
            {
                int tier = Academy.SkillBookTier;
                if (tier < 1 || tier > 3)
                {
                    Logger.LogError("Skill book tier must be an integer between 1 and 3.");
                    Ok = false;
                }
            }

            if (Events.Enabled)
            {
                List<string> events = new List<string> { "Crosswave", "Royal_Maids" };
                List<string> stages = new List<string> { "EX", "H", "N", "E" };
                if (!events.Contains(Events.Name) || !Events.Levels.Any(level => stages.Contains(level)))
                {
                    Ok = false;
                    Logger.LogError("Invalid event settings, please check the wiki.");
                }
            }

            if (Retirement.Enabled)
            {
                if (!Retirement.Commons && !Retirement.Rares)
                {
                    Logger.LogError("Retirement is enabled, but no ship rarities are selected.");
                    Ok = false;
                }
            }

            if (Research.Enabled)
            {
                if (!(Research.Minutes30 || Research.Hour1 || Research.Hour1_30 || Research.Hours2 || Research.Hours2_30 ||
                      Research.Hours4 || Research.Hours5 || Research.Hours6 || Research.Hours8 || Research.Hours12))
                {
                    Logger.LogError("Research is enabled, but without allowed times.");
                    Ok = false;
                }
            }
        }

        // private void _RollbackConfig(Dictionary<string, object> config) // Need to implement deep copy
        // {
        //     foreach (var entry in config)
        //     {
        //         // This would require reflection or a more structured approach
        //         // to set properties dynamically.
        //     }
        // }

        private List<T> ValidateList<T>(string val, List<T> validVals, int minLen, int maxLen, bool unique)
        {
            List<string> sList = Regex.Split(val, @"\s*,\s*|\s+").ToList();
            List<T> resultList = new List<T>();

            if (sList.Count < minLen)
            {
                throw new ArgumentException($"List has fewer than {minLen} elements.");
            }
            if (sList.Count > maxLen)
            {
                throw new ArgumentException($"List has more than {maxLen} elements.");
            }

            foreach (string s in sList)
            {
                try
                {
                    T convertedValue = (T)Convert.ChangeType(s, typeof(T));
                    if (validVals != null && !validVals.Contains(convertedValue))
                    {
                        throw new ArgumentException($"Value '{s}' is not a valid option.");
                    }
                    resultList.Add(convertedValue);
                }
                catch (Exception ex)
                {
                    throw new ArgumentException($"Failed to convert '{s}' to type {typeof(T).Name} or invalid value: {ex.Message}");
                }
            }

            if (unique && resultList.Distinct().Count() != resultList.Count)
            {
                throw new ArgumentException("List contains duplicate values.");
            }

            return resultList;
        }
    }
}
