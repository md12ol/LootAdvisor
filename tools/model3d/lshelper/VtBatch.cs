// Batch extraction of many textures from ONE BG3 virtual texture tile set with LSLib (parses the .gts once).
// usage: dotnet VtBatch.dll <lslib dir> <gts path> <page dir> <list file>
//   list file lines: <gtex name> <max size px> <out prefix>
//   picks the coarsest mip level whose width is still >= max size (or level 0), falls back to finer levels when a
//   level is not stored; writes <out prefix>_L<layer>.dds per layer. Prints one "ok"/"fail" line per texture.
using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;

public static class VtBatch {
  static string LibDir;
  public static int Main(string[] a) {
    LibDir = a[0];
    AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
      var p = Path.Combine(LibDir, new AssemblyName(e.Name).Name + ".dll");
      return File.Exists(p) ? Assembly.LoadFrom(p) : null;
    };
    return Run(a);
  }
  [MethodImpl(MethodImplOptions.NoInlining)]
  static int Run(string[] a) {
    var ts = new LSLib.VirtualTextures.VirtualTileSet(a[1], a[2]);
    var metas = ts.FourCCMetadata.ExtractTextureMetadata();
    int nlev = ts.TileSetLevels.Length;
    foreach (var line in File.ReadAllLines(a[3])) {
      var f = line.Trim().Split(' ');
      if (f.Length < 3) continue;
      string name = f[0]; int max = int.Parse(f[1]); string outp = f[2];
      bool done = false;
      foreach (var m in metas) {
        if (!string.Equals(m.Name, name, StringComparison.OrdinalIgnoreCase)) continue;
        int start = 0;
        while (start + 1 < nlev && (m.Width >> (start + 1)) >= max) start++;
        for (int level = start; level >= 0 && !done; level--) {
          try {
            int n = 0;
            for (int layer = 0; layer < ts.TileSetLayers.Length; layer++) {
              var tex = ts.ExtractTexture(level, layer, m);
              if (tex == null) continue;
              tex.SaveDDS(outp + "_L" + layer + ".dds");
              n++;
            }
            if (n > 0) { Console.WriteLine("ok " + name + " level " + level + " " + (m.Width >> level) + "px layers " + n); done = true; }
          } catch (Exception ex) { Console.WriteLine("level " + level + " error " + ex.Message); }
        }
        break;
      }
      if (!done) Console.WriteLine("fail " + name);
      ts.ReleasePageFiles();
    }
    return 0;
  }
}
