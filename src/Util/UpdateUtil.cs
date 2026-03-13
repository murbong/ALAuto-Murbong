using System;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using System.Text.Json;
using ALAuto.Util;

namespace ALAuto.Util
{
    public class UpdateUtil
    {
        private Config _config;

        public UpdateUtil(Config config)
        {
            _config = config;
        }

        public async Task<bool> CheckUpdate()
        {
            string currentVersion = "";
            string latestVersion = "";

            try
            {
                string[] versionLines = await File.ReadAllLinesAsync("version.txt");

                if (_config.Updates.Channel == "Release")
                {
                    currentVersion = versionLines[0];

                    using (HttpClient client = new HttpClient())
                    {
                        client.DefaultRequestHeaders.Add("User-Agent", "ALAuto"); // GitHub API requires a User-Agent
                        string jsonString = await client.GetStringAsync("https://api.github.com/repos/egoistically/alauto/releases/latest");
                        using (JsonDocument doc = JsonDocument.Parse(jsonString))
                        {
                            if (doc.RootElement.TryGetProperty("tag_name", out JsonElement tagNameElement))
                            {
                                latestVersion = tagNameElement.GetString();
                            }
                        }
                    }
                }
                else // Development channel
                {
                    currentVersion = versionLines[1];

                    using (HttpClient client = new HttpClient())
                    {
                        string rawContent = await client.GetStringAsync("https://raw.githubusercontent.com/Egoistically/ALAuto/master/version.txt");
                        string[] rawLines = rawContent.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                        if (rawLines.Length > 1)
                        {
                            latestVersion = rawLines[1];
                        }
                    }
                }
            }
            catch (HttpRequestException e)
            {
                Logger.LogError($"Couldn't check for updates, {e.Message}.");
                return false;
            }
            catch (FileNotFoundException)
            {
                Logger.LogError("version.txt not found. Unable to check for updates.");
                return false;
            }
            catch (Exception e)
            {
                Logger.LogError($"An unexpected error occurred during update check: {e.Message}.");
                return false;
            }

            if (currentVersion != latestVersion)
            {
                Logger.LogDebug($"Current version: {currentVersion}");
                Logger.LogDebug($"Latest version: {latestVersion}");
                return true;
            }

            return false;
        }
    }
}