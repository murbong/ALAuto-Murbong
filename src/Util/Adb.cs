using System;
using System.Diagnostics;
using System.Linq;
using System.Text;
using ALAuto.Util;

namespace ALAuto.Util
{
    public static class Adb
    {
        public static bool Legacy { get; set; } = false;
        public static string Service { get; set; } = "";
        public static string TransID { get; set; } = "";
        public static bool Tcp { get; set; } = false;

        public static bool Init()
        {
            KillServer();
            return StartServer();
        }

        public static void EnableLegacy()
        {
            Legacy = true;
        }

        public static bool StartServer()
        {
            RunAdbCommand("start-server");

            if (Tcp)
            {
                return ConnectTcp();
            }
            else
            {
                return ConnectUsb();
            }
        }

        public static bool ConnectTcp()
        {
            string response = RunAdbCommand($"connect {Service}", true);
            if (response.Contains("connected") || response.Contains("already"))
            {
                AssignSerial();
                if (!string.IsNullOrEmpty(TransID))
                {
                    return true;
                }
                Logger.LogError("Failure to assign transport_id.");
                Logger.LogError("Please try updating your ADB installation. Current ADB version:");
                PrintAdbVersion();
            }
            return false;
        }

        public static bool ConnectUsb()
        {
            AssignSerial();
            if (!string.IsNullOrEmpty(TransID))
            {
                Logger.LogMsg($"Waiting for device [{Service}] to be authorized...");
                RunAdbCommand($"-t {TransID} wait-for-device");
                Logger.LogMsg($"Device [{Service}] authorized and connected.");
                return true;
            }
            Logger.LogError("Failure to assign transport_id. Is your device connected? Or is \"transport_id\" not supported in current ADB version?");
            Logger.LogError("Try updating ADB if \"transport_id:\" does not exist in the info of your device when running \"adb devices -l\" in cmd.");
            Logger.LogError("Current ADB version:");
            PrintAdbVersion();
            return false;
        }

        public static void KillServer()
        {
            RunAdbCommand("kill-server");
        }

        public static byte[] ExecOut(string args)
        {
            return RunAdbCommand($"-t {TransID} exec-out {args}", true, true);
        }

        public static void Shell(string args)
        {
            Logger.LogDebug($"adb -t {TransID} shell {args}");
            RunAdbCommand($"-t {TransID} shell {args}");
        }

        public static byte[] Cmd(string args)
        {
            Logger.LogDebug($"adb -t {TransID} {args}");
            return RunAdbCommand($"-t {TransID} {args}", true, true);
        }

        public static void AssignSerial()
        {
            string response = RunAdbCommand("devices -l", true);
            var lines = response.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).ToList();
            SanitizeDeviceInfo(lines);

            if (!lines.Any())
            {
                Logger.LogError("adb devices -l yielded no lines with \"transport_id:\"");
            }
            TransID = GetSerialTrans(Service, lines);
        }

        private static void SanitizeDeviceInfo(System.Collections.Generic.List<string> stringList)
        {
            for (int i = stringList.Count - 1; i >= 0; i--)
            {
                if (!stringList[i].Contains("transport_id:"))
                {
                    stringList.RemoveAt(i);
                }
            }
        }

        private static string GetSerialTrans(string device, System.Collections.Generic.List<string> stringList)
        {
            foreach (var line in stringList)
            {
                if (line.Contains(device))
                {
                    int index = line.IndexOf("transport_id:");
                    if (index != -1)
                    {
                        return line.Substring(index + 13).Trim();
                    }
                }
            }
            return "";
        }

        public static void PrintAdbVersion()
        {
            string response = RunAdbCommand("--version", true);
            var versions = response.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var version in versions)
            {
                Logger.LogError(version);
            }
        }

        private static string RunAdbCommand(string arguments, bool captureOutput = false, bool returnBytes = false)
        {
            using (Process process = new Process())
            {
                process.StartInfo.FileName = "adb";
                process.StartInfo.Arguments = arguments;
                process.StartInfo.RedirectStandardOutput = true;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.CreateNoWindow = true;

                try
                {
                    process.Start();
                    if (captureOutput)
                    {
                        string output = process.StandardOutput.ReadToEnd();
                        string error = process.StandardError.ReadToEnd();
                        process.WaitForExit();

                        if (process.ExitCode != 0 && !string.IsNullOrEmpty(error))
                        {
                            Logger.LogError($"ADB command failed: {arguments}");
                            Logger.LogError($"Error: {error}");
                        }
                        return output + error;
                    }
                    else
                    {
                        process.WaitForExit();
                        if (process.ExitCode != 0)
                        {
                            string error = process.StandardError.ReadToEnd();
                            Logger.LogError($"ADB command failed: {arguments}");
                            Logger.LogError($"Error: {error}");
                        }
                        return "";
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogError($"Failed to execute ADB command: {arguments}");
                    Logger.LogError($"Exception: {ex.Message}");
                    return "";
                }
            }
        }

        private static byte[] RunAdbCommand(string arguments, bool captureOutput, bool isByteOutput)
        {
            using (Process process = new Process())
            {
                process.StartInfo.FileName = "adb";
                process.StartInfo.Arguments = arguments;
                process.StartInfo.RedirectStandardOutput = true;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.CreateNoWindow = true;

                try
                {
                    process.Start();
                    if (captureOutput)
                    {
                        using (var stream = process.StandardOutput.BaseStream)
                        {
                            byte[] buffer = new byte[4096];
                            using (var ms = new System.IO.MemoryStream())
                            {
                                int bytesRead;
                                while ((bytesRead = stream.Read(buffer, 0, buffer.Length)) > 0)
                                {
                                    ms.Write(buffer, 0, bytesRead);
                                }
                                process.WaitForExit();
                                return ms.ToArray();
                            }
                        }
                    }
                    else
                    {
                        process.WaitForExit();
                        if (process.ExitCode != 0)
                        {
                            string error = process.StandardError.ReadToEnd();
                            Logger.LogError($"ADB command failed: {arguments}");
                            Logger.LogError($"Error: {error}");
                        }
                        return new byte[0];
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogError($"Failed to execute ADB command: {arguments}");
                    Logger.LogError($"Exception: {ex.Message}");
                    return new byte[0];
                }
            }
        }
    }
}
