using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class RefreshMedia
{
    [STAThread]
    private static int Main(string[] args)
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string exe = Path.Combine(folder, "museum.exe");
        bool quiet = args.Length == 1 && args[0] == "--quiet";
        try
        {
            var start = new ProcessStartInfo(exe, quiet ? "--refresh-media --quiet" : "--refresh-media");
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            if (!quiet)
                MessageBox.Show("Проверьте, что museum.exe лежит рядом с программой обновления.\n" + error.Message,
                                "Обновить архив");
            return 1;
        }
    }
}
