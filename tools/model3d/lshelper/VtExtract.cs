// Extracts one texture (all layers) from a BG3 virtual texture tile set with LSLib.
// usage: dotnet VtExtract.dll <lslib dir> <gts path> <page dir> <gtex name> <level> <out prefix>
//        dotnet VtExtract.dll <lslib dir> <gts path> <page dir> --list
using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;

public static class VtExtract {
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
    if (a[3] == "--list") {
      foreach (var m in metas) Console.WriteLine(m.Name + " " + m.X + " " + m.Y + " " + m.Width + " " + m.Height);
      Console.WriteLine("layers " + ts.TileSetLayers.Length + " levels " + ts.TileSetLevels.Length);
      return 0;
    }
    int level = int.Parse(a[4]);
    foreach (var m in metas) {
      if (!string.Equals(m.Name, a[3], StringComparison.OrdinalIgnoreCase)) continue;
      Console.WriteLine("found " + m.Name + " " + m.Width + "x" + m.Height);
      for (int layer = 0; layer < ts.TileSetLayers.Length; layer++) {
        var tex = ts.ExtractTexture(level, layer, m);
        if (tex == null) { Console.WriteLine("layer " + layer + ": none"); continue; }
        var outp = a[5] + "_L" + layer + ".dds";
        tex.SaveDDS(outp);
        Console.WriteLine("layer " + layer + ": " + tex.Width + "x" + tex.Height + " -> " + outp);
      }
      ts.ReleasePageFiles();
      return 0;
    }
    Console.WriteLine("not found: " + a[3]);
    return 2;
  }
}
