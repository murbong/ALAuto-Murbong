using System;
using ALAuto.Util;

namespace ALAuto.Util
{
    public class Stats
    {
        private DateTime _startTime;
        private Config _config;

        public int CommissionsStarted { get; private set; }
        public int CommissionsReceived { get; private set; }
        public int CombatAttempted { get; private set; }
        public int CombatDone { get; private set; }
        public int OffensiveSkillbook { get; private set; }
        public int DefensiveSkillbook { get; private set; }
        public int SupportSkillbook { get; private set; }

        public Stats(Config config)
        {
            _config = config;
            ResetStats();
        }

        public void ResetStats()
        {
            _startTime = DateTime.Now;
            CommissionsStarted = 0;
            CommissionsReceived = 0;
            CombatAttempted = 0;
            CombatDone = 0;
            OffensiveSkillbook = 0;
            DefensiveSkillbook = 0;
            SupportSkillbook = 0;
        }

        private string PrettyTimeDelta(TimeSpan delta)
        {
            string prettyString = delta.Days > 0 ? $"{delta.Days} days " : "";
            int hours = delta.Hours;
            int minutes = delta.Minutes;
            int seconds = delta.Seconds;

            prettyString += $"{hours} hours {minutes} minutes {seconds} seconds";
            return prettyString;
        }

        private string PrettyPerHour(int count, double hours)
        {
            if (hours < 1 || count == 0)
            {
                return count.ToString();
            }
            return $"{count} ({count / hours:0.00}/hr)";
        }

        public void PrintStats(int oil)
        {
            TimeSpan delta = DateTime.Now - _startTime;
            double hours = delta.TotalSeconds / 3600.0;

            if (oil != 0)
            {
                Logger.LogSuccess($"Current oil: {oil}");
            }
            if (_config.Commissions.Enabled)
            {
                Logger.LogSuccess(
                    $"Commissions sent: {PrettyPerHour(CommissionsStarted, hours)} / received: {PrettyPerHour(CommissionsReceived, hours)}");
            }

            if (_config.Academy.Enabled)
            {
                Logger.LogSuccess(
                    $"Skillbooks T{_config.Academy.SkillBookTier} used (offensive/defensive/support): {OffensiveSkillbook} / {DefensiveSkillbook} / {SupportSkillbook}");
            }

            if (_config.Combat.Enabled)
            {
                Logger.LogSuccess($"Combat done: {PrettyPerHour(CombatDone, hours)} / attempted: {PrettyPerHour(CombatAttempted, hours)}");
            }

            Logger.LogSuccess(
                $"ALAuto has been running for {PrettyTimeDelta(delta)} (started on {_startTime:yyyy-MM-dd HH:mm:ss})");
        }

        public void IncrementCommissionsStarted()
        {
            CommissionsStarted++;
        }

        public void IncrementCommissionsReceived()
        {
            CommissionsReceived++;
        }

        public void IncrementCombatAttempted()
        {
            CombatAttempted++;
        }

        public void IncrementCombatDone()
        {
            CombatDone++;
        }

        public void IncrementOffensiveSkillbookUsed()
        {
            OffensiveSkillbook++;
        }

        public void IncrementDefensiveSkillbookUsed()
        {
            DefensiveSkillbook++;
        }

        public void IncrementSupportSkillbookUsed()
        {
            SupportSkillbook++;
        }
    }
}
