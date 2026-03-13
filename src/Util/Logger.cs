using System;
using System.Diagnostics;

namespace ALAuto.Util
{
    public static class Logger
    {
        public static bool Debug { get; set; } = false;

        // ANSI escape codes for colors (for compatibility, though Console.ForegroundColor is preferred in C#)
        // We will primarily use Console.ForegroundColor for better C# idiomatic style.
        private const string CLR_MSG = "\x1b[94m";
        private const string CLR_SUCCESS = "\x1b[92m";
        private const string CLR_WARNING = "\x1b[93m";
        private const string CLR_ERROR = "\x1b[91m";
        private const string CLR_INFO = "\x1b[35m";
        private const string CLR_END = "\x1b[0m";

        static Logger()
        {
            // In C#, console color handling is typically done via Console.ForegroundColor.
            // No direct equivalent to subprocess.call('', shell=True) is needed for color support setup.
        }

        public static void EnableDebugging()
        {
            Debug = true;
        }

        private static string LogFormat(string msg)
        {
            return $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {msg}";
        }

        private static void WriteLog(string msg, ConsoleColor color)
        {
            Console.ForegroundColor = color;
            Console.WriteLine(LogFormat(msg));
            Console.ResetColor(); // Reset to default color after logging
        }

        public static void LogMsg(string msg)
        {
            WriteLog(msg, ConsoleColor.Blue);
        }

        public static void LogSuccess(string msg)
        {
            WriteLog(msg, ConsoleColor.Green);
        }

        public static void LogWarning(string msg)
        {
            WriteLog(msg, ConsoleColor.Yellow);
        }

        public static void LogError(string msg)
        {
            WriteLog(msg, ConsoleColor.Red);
        }

        public static void LogInfo(string msg)
        {
            WriteLog(msg, ConsoleColor.Magenta);
        }

        public static void LogDebug(string msg)
        {
            if (!Debug) return;
            Console.WriteLine(LogFormat(msg)); // Debug messages typically don't need special colors
        }
    }
}
